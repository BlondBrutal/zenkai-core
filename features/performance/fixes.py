"""
Corrections automatiques sûres pour les cartes de statut : uniquement des
réglages Windows officiels, réversibles depuis les Paramètres Windows. Rien
qui touche à Roblox ou à un anti-cheat.

La plupart s'appliquent par utilisateur courant (pas de droits admin). Le
service SysMain est l'exception : Windows exige les droits administrateur
pour changer l'état d'un service — on demande l'élévation UAC au moment du
clic (via ShellExecute "runas"), plutôt que de faire tourner toute
l'application en admin en permanence (ça resterait la moindre-surprise :
un seul geste explicite, limité à cette action précise).
"""
import ctypes
import logging
import subprocess
import sys
import winreg
from ctypes import wintypes

from core.elevation import is_admin
from core.security_log import log_event
from features.performance.status_cards import HIGH_PERFORMANCE_GUID

logger = logging.getLogger("zenkaiontop.performance")

_UAC_TIMEOUT_MS = 120_000  # le temps de répondre au prompt UAC ne doit pas nous faire abandonner trop tôt


def _hidden_subprocess_kwargs() -> dict:
    """creationflags/startupinfo pour ne jamais afficher de fenêtre de
    console (CREATE_NO_WINDOW seul suffit généralement, le STARTUPINFO
    SW_HIDE est là pour plus de fiabilité — même technique que
    features/performance/live_monitor.py, voir sa docstring pour le bug que
    ça corrige : une fenêtre de console visible, en boucle)."""
    if sys.platform != "win32":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {"creationflags": subprocess.CREATE_NO_WINDOW, "startupinfo": startupinfo}


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", ctypes.c_ulong),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hKeyClass", wintypes.HANDLE),
        ("dwHotKey", wintypes.DWORD),
        ("hIcon", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


def _run_elevated_powershell(command: str) -> bool:
    """Lance une commande PowerShell avec élévation UAC (prompt Windows natif),
    attend sa fin, et retourne True si son code de sortie vaut 0. Si
    l'utilisateur refuse le prompt UAC, ShellExecuteExW échoue directement
    (traité comme un échec de la correction, pas une exception).

    Si le process courant est déjà élevé (voir core/elevation.py — l'app
    entière se relance en admin au démarrage), un simple subprocess.run
    suffit : pas besoin de redemander un prompt UAC individuel ici."""
    if is_admin():
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", command],
                capture_output=True, timeout=_UAC_TIMEOUT_MS / 1000,
                **_hidden_subprocess_kwargs(),
            )
            return result.returncode == 0
        except Exception as exc:
            logger.error("Échec de la commande PowerShell (déjà élevé) : %s", exc)
            return False

    see = _ShellExecuteInfo()
    see.cbSize = ctypes.sizeof(_ShellExecuteInfo)
    see.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS : on récupère hProcess pour attendre la fin
    see.lpVerb = "runas"
    see.lpFile = "powershell.exe"
    see.lpParameters = f'-NoProfile -WindowStyle Hidden -Command "{command}"'
    see.nShow = 0  # SW_HIDE

    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(see)):
        logger.warning("Élévation UAC refusée ou impossible à lancer.")
        return False

    if not see.hProcess:
        return True

    ctypes.windll.kernel32.WaitForSingleObject(see.hProcess, _UAC_TIMEOUT_MS)
    exit_code = wintypes.DWORD()
    ctypes.windll.kernel32.GetExitCodeProcess(see.hProcess, ctypes.byref(exit_code))
    ctypes.windll.kernel32.CloseHandle(see.hProcess)
    return exit_code.value == 0


def set_power_plan_high_performance() -> bool:
    try:
        result = subprocess.run(
            ["powercfg", "/setactive", HIGH_PERFORMANCE_GUID],
            capture_output=True, text=True, timeout=5, errors="replace",
            **_hidden_subprocess_kwargs(),
        )
        success = result.returncode == 0
        log_event("fix_power_plan", HIGH_PERFORMANCE_GUID, "ok" if success else "error", sensitive=True)
        return success
    except Exception as exc:
        logger.error("Impossible de changer le plan d'alimentation : %s", exc)
        log_event("fix_power_plan", HIGH_PERFORMANCE_GUID, "error", sensitive=True)
        return False


def enable_game_mode() -> bool:
    target = r"HKCU\Software\Microsoft\GameBar"
    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\GameBar")
        with key:
            winreg.SetValueEx(key, "AllowAutoGameMode", 0, winreg.REG_DWORD, 1)
        log_event("fix_game_mode", target, "ok", sensitive=True)
        return True
    except Exception as exc:
        logger.error("Impossible d'activer le Mode Jeu : %s", exc)
        log_event("fix_game_mode", target, "error", sensitive=True)
        return False


def disable_game_dvr() -> bool:
    target = r"HKCU\System\GameConfigStore"
    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"System\GameConfigStore")
        with key:
            winreg.SetValueEx(key, "GameDVR_Enabled", 0, winreg.REG_DWORD, 0)
        log_event("fix_game_dvr", target, "ok", sensitive=True)
        return True
    except Exception as exc:
        logger.error("Impossible de désactiver Xbox Game Bar / DVR : %s", exc)
        log_event("fix_game_dvr", target, "error", sensitive=True)
        return False


def disable_sysmain() -> bool:
    """Arrête et désactive le service SysMain (Superfetch). Nécessite les
    droits administrateur : déclenche un prompt UAC natif au moment de
    l'appel plutôt qu'un mode d'emploi manuel."""
    command = (
        "Stop-Service -Name SysMain -Force -ErrorAction SilentlyContinue; "
        "Set-Service -Name SysMain -StartupType Disabled"
    )
    try:
        success = _run_elevated_powershell(command)
        log_event("fix_sysmain", "SysMain", "ok" if success else "error", sensitive=True)
        return success
    except Exception as exc:
        logger.error("Impossible de désactiver SysMain : %s", exc)
        log_event("fix_sysmain", "SysMain", "error", sensitive=True)
        return False
