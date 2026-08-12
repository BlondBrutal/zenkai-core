"""
Bootstrapper Roblox : détection de l'installation, sauvegarde/restauration
du vrai ClientAppSettings.json, et orchestration "injecte les Fast Flags
PUIS lance le vrai client" — utilisé à la fois par le bouton "Lancer
Roblox" (page_fastflags.py) et par le lancement headless déclenché par le
protocole roblox-player:// (voir main.py).

Principe de sécurité central (voir aussi protocol.py) : AUCUNE étape
d'injection/sauvegarde ne doit jamais empêcher Roblox de démarrer — toute
erreur ici est absorbée et journalisée, jamais laissée remonter. Le seul
cas où lancer_roblox() renonce légitimement est "Roblox introuvable sur le
disque" (rien à lancer), signalé clairement à l'appelant via LaunchResult,
jamais en échouant silencieusement.

Ne réimporte PAS features/performance/system_info.py (qui entraîne
psutil/wmi/PyQt6 pour des besoins de diagnostic sans rapport) : ce module
doit rester rapide et dépendre du minimum, puisqu'il est aussi exécuté par
le chemin headless (voir main.py) qui doit répondre quasi instantanément à
chaque clic sur "Jouer".
"""
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass

from core.config import config
from core.paths import (
    get_fastflags_active_config_path, get_fastflags_backup_marker_path,
    get_fastflags_backup_path,
)
from core.security_log import log_event
from features.fastflags.manager import (
    export_flags_file, get_client_app_settings_path, load_custom_preset,
    write_flags,
)

logger = logging.getLogger("zenkaiontop.fastflags.launcher")


def find_roblox_player_exe() -> str | None:
    """Cherche RobloxPlayerBeta.exe dans le dossier d'installation le plus
    récent (%LOCALAPPDATA%\\Roblox\\Versions\\version-*). Contrairement à
    features/performance/system_info.py::find_roblox_install, vérifie
    RÉELLEMENT que l'exécutable existe dans le dossier avant de le retenir
    (un dossier de version présent mais incomplet/corrompu ne doit jamais
    être choisi) : essaie les dossiers du plus récent au plus ancien tant
    qu'aucun ne contient l'exe. None si Roblox n'est pas installé du tout,
    ou si aucun dossier de version ne contient l'exe."""
    versions_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Roblox", "Versions")
    if not os.path.isdir(versions_dir):
        return None
    try:
        candidates = [
            entry for entry in os.listdir(versions_dir)
            if entry.startswith("version-") and os.path.isdir(os.path.join(versions_dir, entry))
        ]
    except OSError as exc:
        logger.warning("Impossible de lister %s (%s)", versions_dir, exc)
        return None
    candidates.sort(key=lambda e: os.path.getmtime(os.path.join(versions_dir, e)), reverse=True)
    for entry in candidates:
        exe_path = os.path.join(versions_dir, entry, "RobloxPlayerBeta.exe")
        if os.path.isfile(exe_path):
            return exe_path
    return None


def ensure_backup_exists() -> None:
    """Sauvegarde le VRAI ClientAppSettings.json une seule fois, la toute
    première fois que cette app s'apprête à y écrire — jamais retouché
    ensuite (voir get_fastflags_backup_marker_path). N'est appelé qu'à
    l'intérieur de launch_roblox(), toujours dans un contexte où une erreur
    ici ne doit jamais empêcher la suite (voir docstring du module) : ne
    lève donc jamais, log seulement en cas d'échec (une sauvegarde ratée
    réduit le filet de sécurité mais ne doit pas bloquer le lancement)."""
    marker_path = get_fastflags_backup_marker_path()
    if os.path.isfile(marker_path):
        return
    real_path = get_client_app_settings_path()
    try:
        existed = os.path.isfile(real_path)
        if existed:
            shutil.copy2(real_path, get_fastflags_backup_path())
        export_flags_file({"existed": existed}, marker_path)
        log_event("fastflags_backup", real_path, "ok", sensitive=True)
    except Exception as exc:
        logger.error("Sauvegarde de ClientAppSettings.json impossible (%s)", exc)
        log_event("fastflags_backup", real_path, "error", sensitive=True)


def restore_original() -> bool:
    """Restaure le vrai ClientAppSettings.json tel qu'il était juste avant
    la toute première écriture de cette app (ou le supprime, s'il n'existait
    pas à ce moment-là). Ne lève jamais, retourne False si la sauvegarde
    n'a jamais été prise (rien à restaurer) ou en cas d'erreur disque."""
    marker_path = get_fastflags_backup_marker_path()
    if not os.path.isfile(marker_path):
        return False
    real_path = get_client_app_settings_path()
    try:
        marker = load_custom_preset(marker_path)
        if marker.get("existed"):
            shutil.copy2(get_fastflags_backup_path(), real_path)
        elif os.path.isfile(real_path):
            os.remove(real_path)
        log_event("fastflags_restore", real_path, "ok", sensitive=True)
        return True
    except Exception as exc:
        logger.error("Restauration de ClientAppSettings.json impossible (%s)", exc)
        log_event("fastflags_restore", real_path, "error", sensitive=True)
        return False


@dataclass
class LaunchResult:
    started: bool
    roblox_found: bool
    injection_ok: bool
    error: str | None = None


def launch_roblox(original_args: list[str], flags_override: dict | None = None) -> LaunchResult:
    """Point d'entrée unique du bootstrapper, appelé à la fois par le
    bouton "Lancer Roblox" (flags_override = contenu du tableau) et par le
    lancement headless via le protocole roblox-player:// (flags_override =
    None, aucun tableau vivant à consulter — voir main.py).

    `original_args` est transmis tel quel à RobloxPlayerBeta.exe (le ticket
    d'authentification etc. que Roblox a fourni) : [] pour un lancement
    manuel depuis le bouton (équivalent à double-cliquer le raccourci),
    sys.argv[1:] pour un lancement intercepté (jamais juste sys.argv[1],
    pour transmettre aussi tout argument supplémentaire éventuel)."""
    injection_ok = True
    real_path = get_client_app_settings_path()
    try:
        ensure_backup_exists()
        globally_enabled = bool(config.get("fastflags_globally_enabled", True))
        if not globally_enabled:
            # L'interrupteur "Fast Flags actifs" prime toujours : même un
            # lancement bouton n'écrit rien tant qu'il est coupé (voir
            # _on_kill_switch_toggled, qui vide déjà le vrai fichier).
            write_flags({})
        elif flags_override is not None:
            # Lancement depuis le bouton GUI : le tableau fait foi, et
            # devient la nouvelle configuration active pour les PROCHAINS
            # lancements (y compris ceux déclenchés sans l'app ouverte).
            export_flags_file(flags_override, get_fastflags_active_config_path())
            write_flags(flags_override)
        else:
            # Lancement headless (protocole) : pas de tableau vivant, on
            # réaffirme la dernière configuration active connue — jamais le
            # contenu volatil du vrai fichier (voir docstring du module).
            active_path = get_fastflags_active_config_path()
            if os.path.isfile(active_path):
                write_flags(load_custom_preset(active_path))
            # Sinon : l'utilisateur n'a jamais lancé via cette app, on ne
            # touche à rien (comportement Roblox par défaut, sûr par
            # construction).
    except Exception as exc:
        logger.error("Injection des Fast Flags échouée, lancement quand même : %s", exc)
        injection_ok = False
    log_event("fastflags_inject", real_path, "ok" if injection_ok else "error", sensitive=True)

    exe_path = find_roblox_player_exe()
    if exe_path is None:
        return LaunchResult(started=False, roblox_found=False, injection_ok=injection_ok,
                             error="Roblox introuvable sur ce PC.")

    try:
        subprocess.Popen([exe_path] + original_args, cwd=os.path.dirname(exe_path))
    except OSError as exc:
        logger.error("Impossible de lancer RobloxPlayerBeta.exe (%s)", exc)
        return LaunchResult(started=False, roblox_found=True, injection_ok=injection_ok, error=str(exc))

    return LaunchResult(started=True, roblox_found=True, injection_ok=injection_ok)


def clear_active_config() -> None:
    """Vide la configuration active (voir _on_reset dans page_fastflags.py) :
    sans ça, un "Réinitialiser" resterait sans effet sur les FUTURS
    lancements déclenchés par le protocole (qui réappliqueraient l'ancienne
    configuration active mémorisée)."""
    export_flags_file({}, get_fastflags_active_config_path())
