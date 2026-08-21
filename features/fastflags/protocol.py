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

PIÈGE CRITIQUE (déjà rencontré, cause probable d'un "register() réussit
mais Windows n'invoque quand même jamais l'app") — "UserChoice" : depuis
Windows 8, dès qu'un navigateur (ou l'Explorateur) doit lancer une URI
d'un protocole donné, il ne se contente PAS de résoudre directement
"roblox-player\\shell\\open\\command" (HKCU en surcouche de HKCR, voir
plus haut) — il consulte D'ABORD
HKCU\\Software\\Microsoft\\Windows\\Shell\\Associations\\UrlAssociations\\
roblox-player\\UserChoice\\ProgId. Si un "choix utilisateur" y est déjà
enregistré (ex: la première fois que Roblox lui-même a été installé/lancé
et qu'un chooser "Ouvrir avec ?" a déjà été validé une fois pour ce
protocole, AVANT même que cette app existe sur la machine), Windows/le
navigateur invoque DIRECTEMENT la commande de CE ProgId — sans jamais
relire "roblox-player\\shell\\open\\command" lui-même, donc sans jamais
voir notre écriture, même parfaitement correcte. register()/health_check()
ci-dessous ne regardent QUE cette dernière clé : un health_check() "ok"
ne garantit donc PAS que Windows invoquera réellement cette app — voir
has_user_choice_conflict() pour le détecter, et reset_user_choice() pour
la seule remédiation possible (voir sa docstring : Windows protège cette
clé contre une réécriture SILENCIEUSE par un tiers, mesure anti-hijacking
volontaire — on peut seulement forcer un nouveau choix, jamais l'imposer).
Problème déjà documenté par d'autres outils communautaires équivalents
pour Roblox (ex: Bloxstrap), pas une hypothèse isolée à ce projet.
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
# Voir le paragraphe "PIÈGE CRITIQUE" de la docstring du module.
_USER_CHOICE_SUBKEY = (
    f"Software\\Microsoft\\Windows\\Shell\\Associations\\UrlAssociations\\{_PROTOCOL_NAME}\\UserChoice"
)


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


def get_user_choice_progid() -> str | None:
    """Lit le ProgId mémorisé par Windows comme "choix utilisateur" pour ce
    protocole (voir "PIÈGE CRITIQUE" dans la docstring du module) — None si
    aucun choix explicite n'a jamais été enregistré pour "roblox-player"
    précisément (jamais d'exception)."""
    try:
        with winreg.OpenKey(_ROOT_HIVE, _USER_CHOICE_SUBKEY, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, "ProgId")
            return value
    except OSError:
        return None


def _progid_command(progid: str) -> str | None:
    """Commande "shell\\open\\command" d'un ProgId donné — HKCU\\Software\\
    Classes d'abord (ProgId personnalisé d'un utilitaire tiers, comme
    "roblox-player" lui-même l'est pour nous), HKEY_CLASSES_ROOT ensuite
    (installeur classique avec droits admin, cas du vrai client Roblox).
    None si introuvable dans aucun des deux (jamais d'exception)."""
    for hive, subkey in (
        (winreg.HKEY_CURRENT_USER, f"Software\\Classes\\{progid}\\shell\\open\\command"),
        (winreg.HKEY_CLASSES_ROOT, f"{progid}\\shell\\open\\command"),
    ):
        try:
            with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ) as key:
                value, _ = winreg.QueryValueEx(key, "")
                return value
        except OSError:
            continue
    return None


def has_user_choice_conflict() -> bool:
    """True si Windows a déjà un "choix utilisateur" (UserChoice) enregistré
    pour "roblox-player" qui pointe vers une commande DIFFÉRENTE de la
    nôtre — dans ce cas, un lancement depuis un navigateur invoque
    directement cette autre commande, sans jamais consulter
    "roblox-player\\shell\\open\\command" (donc sans jamais voir
    register(), même correctement écrit). Voir "PIÈGE CRITIQUE" dans la
    docstring du module. False si aucun choix n'existe encore (Windows
    résoudra alors normalement via "roblox-player\\shell\\open\\command",
    ou proposera un chooser au tout premier lancement)."""
    progid = get_user_choice_progid()
    if progid is None:
        return False
    command = _progid_command(progid)
    return command is not None and command != get_expected_command()


def reset_user_choice() -> bool:
    """Supprime l'entrée UserChoice existante pour "roblox-player", pour
    forcer Windows à redemander explicitement à l'utilisateur au prochain
    lancement intercepté plutôt que de continuer à invoquer en silence un
    AUTRE gestionnaire déjà mémorisé (voir has_user_choice_conflict()).

    NE PEUT PAS imposer directement notre app comme nouveau choix : Windows
    protège volontairement cette clé contre toute réécriture SILENCIEUSE
    par un programme tiers (mesure anti-hijacking de navigateur introduite
    avec Windows 10) — seul un vrai choix de l'utilisateur (le chooser qui
    réapparaîtra, ou Paramètres Windows > Applications > Applications par
    défaut > rechercher "roblox-player") peut reposer ce choix. Retourne
    False (jamais d'exception) si la clé n'existe pas (rien à faire) ou si
    Windows refuse la suppression (ACL protégée selon la version de
    Windows) — dans ce dernier cas, Paramètres Windows reste la seule
    option fiable, à indiquer clairement à l'utilisateur plutôt que de
    prétendre avoir résolu le conflit."""
    try:
        winreg.DeleteKey(_ROOT_HIVE, _USER_CHOICE_SUBKEY)
        log_event("protocol_reset_user_choice", Category.PROTOCOL_HANDLER, f"HKCU\\{_USER_CHOICE_SUBKEY}", "ok")
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.error("Impossible de supprimer UserChoice pour roblox-player:// (%s)", exc)
        log_event("protocol_reset_user_choice", Category.PROTOCOL_HANDLER, f"HKCU\\{_USER_CHOICE_SUBKEY}", "error")
        return False


def health_check() -> str:
    """Retourne "ok" (correctement enregistré, l'exe référencé existe
    toujours, ET aucun conflit UserChoice détecté), "missing" (aucune
    clé — jamais enregistré, ou supprimé par l'utilisateur/Windows/un
    nettoyeur de registre), "stale" (clé présente mais commande différente
    de celle qu'on écrirait aujourd'hui, ou l'exécutable qu'elle référence
    n'existe plus sur disque — ex. réinstallation Python, app déplacée), ou
    "user_choice_conflict" (notre clé est correcte, mais Windows a déjà un
    autre choix mémorisé pour ce protocole — voir has_user_choice_conflict()
    et le "PIÈGE CRITIQUE" en tête de ce module : re-register() ne répare
    RIEN dans ce cas précis, inutile de le retenter)."""
    registered = get_registered_command()
    if registered is None:
        return "missing"
    exe_path = _extract_exe_path(registered)
    if exe_path is None or not os.path.isfile(exe_path):
        return "stale"
    if registered != get_expected_command():
        return "stale"
    if has_user_choice_conflict():
        return "user_choice_conflict"
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
