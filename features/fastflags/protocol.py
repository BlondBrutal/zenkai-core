"""
Enregistrement du protocole roblox-player:// dans le registre Windows, pour
intercepter les lancements de Roblox (bouton "Jouer" du site, raccourci
existant) et les faire passer par cette app avant le vrai client — voir
features/fastflags/launcher.py pour ce qui se passe une fois interceptée.

Écrit UNIQUEMENT dans HKEY_CURRENT_USER\\Software\\Classes\\roblox-player —
jamais dans HKEY_CLASSES_ROOT (où Roblox enregistre son propre gestionnaire
à l'installation, avec des droits admin). Windows résout un protocole en
consultant HKCU\\Software\\Classes AVANT HKEY_CLASSES_ROOT : une simple
surcouche HKCU suffit donc à intercepter, sans jamais toucher à l'entrée
Roblox elle-même. Conséquences :
- Aucun droit admin nécessaire (HKCU est toujours accessible en écriture
  par l'utilisateur courant).
- "Se désinscrire" = supprimer cette seule clé HKCU → retour instantané et
  parfait au comportement Roblox d'origine (HKEY_CLASSES_ROOT reprend la
  main automatiquement, intact, jamais modifié).
- Résiste normalement aux mises à jour Roblox (qui réécrivent HKCR, pas
  HKCU).

Ce module ne fait QUE de la lecture/écriture registre : aucune écriture sur
ClientAppSettings.json, aucun lancement de process (voir launcher.py).
"""
import logging
import os
import sys
import winreg

from core.elevation import _dev_mode_executable
from core.security_log import Category, log_event

logger = logging.getLogger("zenkaiontop.fastflags.protocol")

_PROTOCOL_NAME = "roblox-player"
_ROOT_HIVE = winreg.HKEY_CURRENT_USER
_ROOT_SUBKEY = f"Software\\Classes\\{_PROTOCOL_NAME}"
_COMMAND_SUBKEY = f"{_ROOT_SUBKEY}\\shell\\open\\command"


def get_expected_command() -> str:
    """Commande que CETTE app écrirait aujourd'hui si on (ré)enregistrait le
    protocole — sert à la fois à register() et à health_check() (comparer
    "ce qui est écrit" à "ce qui devrait l'être")."""
    if getattr(sys, "frozen", False):
        # Exécutable compilé (PyInstaller) : sys.executable EST déjà l'app.
        return f'"{sys.executable}" "%1"'
    # Mode développement : pythonw.exe (pas de console, voir
    # core/elevation.py::_dev_mode_executable) + chemin du script + l'URI
    # d'origine transmise par Windows en %1.
    return f'"{_dev_mode_executable()}" "{os.path.abspath(sys.argv[0])}" "%1"'


def get_registered_command() -> str | None:
    """Valeur par défaut de ...\\shell\\open\\command actuellement dans le
    registre, ou None si absente/illisible — ne lève jamais."""
    try:
        with winreg.OpenKey(_ROOT_HIVE, _COMMAND_SUBKEY, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, "")
            return value
    except OSError:
        return None


def _extract_exe_path(command: str) -> str | None:
    """Extrait le chemin de l'exécutable (premier segment entre guillemets)
    d'une commande de la forme '"<exe>" "<script>" "%1"' ou '"<exe>" "%1"'."""
    if not command.startswith('"'):
        return None
    end = command.find('"', 1)
    if end == -1:
        return None
    return command[1:end]


def health_check() -> str:
    """Retourne "ok" (correctement enregistré et l'exe référencé existe
    toujours), "missing" (aucune clé — jamais enregistré, ou supprimé par
    l'utilisateur/Windows/un nettoyeur de registre), ou "stale" (clé
    présente mais commande différente de celle qu'on écrirait aujourd'hui,
    ou l'exécutable qu'elle référence n'existe plus sur disque — ex.
    réinstallation Python, app déplacée)."""
    registered = get_registered_command()
    if registered is None:
        return "missing"
    exe_path = _extract_exe_path(registered)
    if exe_path is None or not os.path.isfile(exe_path):
        return "stale"
    if registered != get_expected_command():
        return "stale"
    return "ok"


def is_registered() -> bool:
    return health_check() == "ok"


def register() -> bool:
    """Écrit la clé HKCU complète (Default, "URL Protocol", commande).
    Jamais d'exception : False sur tout échec (registre verrouillé, accès
    refusé — improbable sous HKCU mais jamais supposé impossible)."""
    try:
        with winreg.CreateKeyEx(_ROOT_HIVE, _ROOT_SUBKEY, 0, winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:Roblox Protocol")
            # Marqueur obligatoire pour que Windows traite cette clé comme un
            # gestionnaire de protocole (pas un ProgID de fichier ordinaire).
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKeyEx(_ROOT_HIVE, _COMMAND_SUBKEY, 0, winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, get_expected_command())
        log_event("protocol_register", Category.PROTOCOL_HANDLER, f"HKCU\\{_ROOT_SUBKEY}", "ok")
        return True
    except OSError as exc:
        logger.error("Impossible d'enregistrer le protocole roblox-player:// (%s)", exc)
        log_event("protocol_register", Category.PROTOCOL_HANDLER, f"HKCU\\{_ROOT_SUBKEY}", "error")
        return False


def _delete_key_recursive(hive, subkey: str) -> None:
    """Supprime `subkey` et TOUT son contenu, à n'importe quelle profondeur
    — contrairement à winreg.DeleteKey (une seule clé, et seulement si elle
    n'a AUCUNE sous-clé). Nécessaire ici : la clé "roblox-player" créée par
    l'installeur Roblox contient, en plus de "shell\\open\\command" (la
    seule sous-clé que register()/l'ancienne version de cette fonction
    connaissait), une sous-clé "DefaultIcon" — la supprimer "à la main" en
    ne visant que 4 chemins fixes échouait dès que CETTE sous-clé
    inattendue restait présente (winreg.DeleteKey refuse de supprimer une
    clé qui a encore des enfants, avec un OSError générique — PAS un
    FileNotFoundError, donc jamais rattrapé par l'ancien code). Cette
    version énumère et supprime récursivement TOUTES les sous-clés,
    quelles qu'elles soient, avant de supprimer la clé elle-même — robuste
    à n'importe quelle structure ajoutée par Roblox, Windows, ou un usage
    antérieur de cette fonction. Ne lève jamais si la clé n'existe déjà
    plus (à ce niveau ou plus haut) : rien à faire, pas une erreur."""
    try:
        key = winreg.OpenKey(hive, subkey, 0, winreg.KEY_ALL_ACCESS)
    except FileNotFoundError:
        return
    try:
        # Toujours ré-interroger l'index 0 : EnumKey énumère par position,
        # et supprimer un enfant décale les index suivants vers le bas —
        # avancer l'index comme dans une boucle for classique sauterait des
        # sous-clés à chaque suppression.
        while True:
            try:
                child_name = winreg.EnumKey(key, 0)
            except OSError:
                break
            _delete_key_recursive(hive, f"{subkey}\\{child_name}")
    finally:
        key.Close()
    try:
        winreg.DeleteKey(hive, subkey)
    except FileNotFoundError:
        pass


def unregister() -> bool:
    """Supprime la clé HKCU "roblox-player" et tout son contenu, quelle que
    soit sa structure réelle (voir _delete_key_recursive) — jamais
    d'exception, False seulement sur un échec disque/registre inattendu
    (permissions, etc.)."""
    try:
        _delete_key_recursive(_ROOT_HIVE, _ROOT_SUBKEY)
        log_event("protocol_unregister", Category.PROTOCOL_HANDLER, f"HKCU\\{_ROOT_SUBKEY}", "ok")
        return True
    except OSError as exc:
        logger.error("Impossible de désinscrire le protocole roblox-player:// (%s)", exc)
        log_event("protocol_unregister", Category.PROTOCOL_HANDLER, f"HKCU\\{_ROOT_SUBKEY}", "error")
        return False
