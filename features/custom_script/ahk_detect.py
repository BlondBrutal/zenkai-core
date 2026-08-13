"""
Détection de l'interpréteur AutoHotkey v2 utilisé par la page Custom Script.

Priorité à la copie PORTABLE embarquée dans le dépôt
(assets/runtime/ahk/AutoHotkey64.exe, repli AutoHotkey32.exe) — c'est elle
qui tourne en usage normal, aucune installation système n'est nécessaire.
La détection d'une installation système existante (registre
HKLM/HKCU\\SOFTWARE\\AutoHotkey, ou %ProgramFiles%\\AutoHotkey) ne reste
qu'un REPLI secondaire, pour le cas résiduel où la copie embarquée serait
absente/corrompue (fichier supprimé manuellement, build incomplet...).

Cible les noms d'exécutables v2 (AutoHotkey64.exe/AutoHotkey32.exe/
AutoHotkeyUX.exe) EN PRIORITÉ, mais reconnaît aussi les noms v1.1 classiques
(AutoHotkeyU64.exe/AutoHotkeyU32.exe/AutoHotkey.exe/AutoHotkeyA32.exe) dans
le repli système, au cas où seule une installation v1.1 serait présente sur
le PC — mieux vaut lancer un script avec CET interpréteur-là (une syntaxe
proche mais pas garantie identique) que de ne rien trouver du tout.
"""
import logging
import os
import sys

logger = logging.getLogger("zenkaiontop.custom_script")

# features/custom_script/ahk_detect.py -> features/custom_script -> features
# -> racine du dépôt (même convention locale que ASSETS_DIR dans
# ui/sidebar.py, ui/main_window.py, etc. — un niveau de dossier en plus ici
# puisque ce module vit sous features/custom_script/, pas directement sous
# une des racines ui/ features/ core/).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_EMBEDDED_AHK_DIR = os.path.join(_REPO_ROOT, "assets", "runtime", "ahk")

_EMBEDDED_EXE_NAMES = ["AutoHotkey64.exe", "AutoHotkey32.exe"]
_V2_EXE_NAMES = ["AutoHotkey64.exe", "AutoHotkey32.exe", "AutoHotkeyUX.exe"]
_V1_EXE_NAMES = ["AutoHotkeyU64.exe", "AutoHotkeyU32.exe", "AutoHotkey.exe", "AutoHotkeyA32.exe"]


def find_embedded_ahk_interpreter() -> str | None:
    for exe_name in _EMBEDDED_EXE_NAMES:
        candidate = os.path.join(_EMBEDDED_AHK_DIR, exe_name)
        if os.path.isfile(candidate):
            return candidate
    return None


def _registry_install_dirs() -> list[str]:
    if sys.platform != "win32":
        return []
    import winreg

    dirs = []
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, r"SOFTWARE\AutoHotkey", 0, winreg.KEY_READ) as key:
                value, _ = winreg.QueryValueEx(key, "InstallDir")
                if value:
                    dirs.append(value)
        except OSError:
            continue
    return dirs


def _fallback_dirs() -> list[str]:
    return [
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "AutoHotkey"),
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "AutoHotkey"),
    ]


def find_system_ahk_interpreter() -> str | None:
    for base in _registry_install_dirs() + _fallback_dirs():
        for exe_name in _V2_EXE_NAMES + _V1_EXE_NAMES:
            candidate = os.path.join(base, exe_name)
            if os.path.isfile(candidate):
                return candidate
    return None


def find_ahk_interpreter() -> str | None:
    embedded = find_embedded_ahk_interpreter()
    if embedded is not None:
        return embedded
    logger.warning(
        "Interpréteur AutoHotkey embarqué introuvable (%s) : repli sur une installation système.",
        _EMBEDDED_AHK_DIR,
    )
    return find_system_ahk_interpreter()


def health_check() -> str:
    """"ok" | "missing" — même convention que
    features/fastflags/protocol.py::health_check()."""
    return "ok" if find_ahk_interpreter() else "missing"
