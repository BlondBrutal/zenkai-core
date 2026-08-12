"""
Centralise tous les chemins de données de l'application (config, logs, licence).
Utilise %APPDATA% sous Windows. En dehors de Windows (tests/dev), retombe sur
un dossier local pour ne jamais planter pendant le développement.
"""
import os
import sys

APP_NAME = "ZenkaiCore"


def get_app_data_dir() -> str:
    """Retourne (et crée si besoin) le dossier de données de l'app."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        # Environnement de dev/test non-Windows : dossier local équivalent
        base = os.path.join(os.path.expanduser("~"), ".zenkaiontop_appdata")
    app_dir = os.path.join(base, APP_NAME)
    os.makedirs(app_dir, exist_ok=True)
    return app_dir


def get_logs_dir() -> str:
    logs_dir = os.path.join(get_app_data_dir(), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    return logs_dir


def get_settings_path() -> str:
    return os.path.join(get_app_data_dir(), "settings.json")


def get_license_path() -> str:
    return os.path.join(get_app_data_dir(), "license.dat")


def get_macros_dir() -> str:
    macros_dir = os.path.join(get_app_data_dir(), "macros")
    os.makedirs(macros_dir, exist_ok=True)
    return macros_dir


def get_cursors_dir() -> str:
    cursors_dir = os.path.join(get_app_data_dir(), "cursors")
    os.makedirs(cursors_dir, exist_ok=True)
    return cursors_dir


def get_fastflags_presets_dir() -> str:
    """Dossier des presets Fast Flags personnalisés (enregistrés depuis
    l'éditeur, ou importés depuis un fichier externe) — voir
    features/fastflags/manager.py."""
    presets_dir = os.path.join(get_app_data_dir(), "fastflags_presets")
    os.makedirs(presets_dir, exist_ok=True)
    return presets_dir


def get_fastflags_known_flags_path() -> str:
    """Fichier des noms de flags "appris" au fil des imports de
    l'utilisateur (voir features/fastflags/manager.py:get_known_flags) —
    séparé du dossier des presets pour ne pas apparaître comme un preset."""
    return os.path.join(get_app_data_dir(), "fastflags_known_learned.json")


def get_fastflags_active_config_path() -> str:
    """Configuration Fast Flags "active" : celle que le bootstrapper (voir
    features/fastflags/launcher.py) réinjecte dans le vrai fichier Roblox à
    CHAQUE lancement, y compris quand ce lancement est déclenché par le
    protocole roblox-player:// (sans que l'app/le tableau ne soit ouvert).
    Distincte à la fois du vrai fichier Roblox (volatil, Roblox peut le
    modifier) et de la bibliothèque de presets (fastflags_presets/,
    alimentée par "Enregistrer") : ce fichier représente uniquement
    "la dernière configuration que l'utilisateur a explicitement lancée"."""
    return os.path.join(get_app_data_dir(), "active_fastflags.json")


def get_fastflags_backup_path() -> str:
    """Copie du VRAI ClientAppSettings.json telle qu'elle était juste avant
    la toute première écriture faite par cette app — jamais réécrite après
    coup (voir features/fastflags/launcher.py:ensure_backup_exists)."""
    return os.path.join(get_app_data_dir(), "ClientAppSettings.json.bak")


def get_security_log_path() -> str:
    """Journal de sécurité (voir core/security_log.py) : une ligne JSON par
    action "sensible" (écriture registre, modification de
    ClientAppSettings.json, élévation UAC...), consultable depuis la page
    Paramètres. Séparé du log applicatif classique
    (get_logs_dir()/zenkaiontop.log) pour rester lisible même quand
    celui-ci devient verbeux (erreurs techniques, traces de debug...)."""
    return os.path.join(get_logs_dir(), "security_events.jsonl")


def get_fastflags_backup_marker_path() -> str:
    """Marqueur JSON ({"existed": bool}) indiquant si la sauvegarde
    ci-dessus a déjà été prise, et si le vrai fichier existait à ce
    moment-là (sinon "restaurer l'original" doit supprimer le fichier
    plutôt que d'y recopier un contenu qui n'a jamais existé)."""
    return os.path.join(get_app_data_dir(), "fastflags_backup_marker.json")
