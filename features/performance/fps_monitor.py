"""
FPS réel par processus pour l'overlay Performance, via PresentMon (Intel,
open-source, MIT) embarqué dans vendor/presentmon/ — c'est la même technique
utilisée par MSI Afterburner/RTSS : capture ETW des appels Present() du jeu
ciblé, pas une estimation basée sur le taux de rafraîchissement de l'écran.

Contrainte de cette technique (documentée par Intel, pas un choix de notre
part) : démarrer une session de capture ETW demande soit les droits
administrateur, soit d'appartenir au groupe Windows "Performance Log Users"
— l'élévation est gérée nous-mêmes via ShellExecuteExW (voir
_run_elevated_hidden), qui déclenche une invite UAC si nécessaire. Sans ça,
on échoue proprement (fps_ready(None)) plutôt que d'inventer une valeur.

Élévation gérée nous-mêmes (ShellExecuteExW + nShow=SW_HIDE) plutôt que via
le propre --restart_as_admin de PresentMon : ce dernier relance PresentMon
en processus élevé séparé dont NOUS ne contrôlons pas la fenêtre (les
creationflags passés à notre subprocess.Popen ne s'appliquent qu'au premier
processus, non-élevé, qui se contente de déclencher le relancement — la
console du second, élevé, reste visible quoi qu'on fasse de ce côté). En
gérant l'élévation nous-mêmes, `nShow=SW_HIDE` s'applique directement au
process élevé : sa console ne s'affiche jamais, contrairement à
`Start-Process -WindowStyle Hidden -Verb RunAs` (PowerShell), qui n'honore
pas fiablement ce paramètre pour un verbe RunAs.

Impossible de lire la sortie d'un process élevé via un pipe stdout hérité
(ce n'est pas un vrai enfant du nôtre) : on lui fait donc écrire un CSV dans
un fichier temporaire et on le "tail" nous-mêmes (--output_file), plutôt que
--output_stdout.
"""
import csv
import ctypes
import logging
import os
import subprocess
import tempfile
import time
from collections import deque
from ctypes import wintypes
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from core.elevation import is_admin

logger = logging.getLogger("zenkaiontop.performance")

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PRESENTMON_EXE = os.path.join(_ROOT_DIR, "vendor", "presentmon", "PresentMon-2.5.1-x64.exe")

_SESSION_NAME = "ZenkaiFpsOverlay"
_POLL_INTERVAL_SECONDS = 0.4
# Si aucune ligne de données n'est apparue dans le CSV après ce délai (UAC
# refusé, session bloquée par la stratégie de groupe, processus introuvable),
# on arrête d'attendre et on signale l'indisponibilité plutôt que de rester
# muet indéfiniment.
_STARTUP_TIMEOUT_SECONDS = 15.0

_SW_HIDE = 0
_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_SEE_MASK_NOASYNC = 0x00000100
_WAIT_FAILED = 0xFFFFFFFF


class _ShellExecuteInfoW(ctypes.Structure):
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
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIconOrMonitor", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


def _run_elevated_hidden(exe_path: str, args: list[str], wait_seconds: Optional[float] = None) -> None:
    """Lance exe_path élevé (invite UAC gérée par Windows) avec sa fenêtre
    cachée (nShow=SW_HIDE) — voir la docstring du module pour pourquoi ça ne
    peut pas passer par subprocess.Popen(creationflags=...) ni par
    PresentMon's --restart_as_admin. `wait_seconds` bloque jusqu'à la fin du
    process élevé (utilisé pour --terminate_existing_session, où on veut
    attendre que l'arrêt soit effectif) ; None ne bloque pas (démarrage
    normal, suivi ensuite via le fichier CSV taillé). Si le process courant
    est déjà élevé (voir core/elevation.py — l'app entière se relance en
    admin au démarrage), un simple subprocess.Popen suffit : pas besoin de
    redemander un prompt UAC individuel pour cette action."""
    if is_admin():
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        proc = subprocess.Popen(
            [exe_path, *args], creationflags=subprocess.CREATE_NO_WINDOW, startupinfo=startupinfo,
        )
        if wait_seconds is not None:
            try:
                proc.wait(timeout=wait_seconds)
            except subprocess.TimeoutExpired:
                logger.warning("Timeout en attendant PresentMon (déjà élevé)")
        return

    info = _ShellExecuteInfoW()
    info.cbSize = ctypes.sizeof(_ShellExecuteInfoW)
    info.fMask = _SEE_MASK_NOCLOSEPROCESS | _SEE_MASK_NOASYNC
    info.lpVerb = "runas"
    info.lpFile = exe_path
    info.lpParameters = subprocess.list2cmdline(args)
    info.nShow = _SW_HIDE

    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())

    if not info.hProcess:
        return
    try:
        if wait_seconds is not None:
            timeout_ms = max(0, round(wait_seconds * 1000))
            result = ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, timeout_ms)
            if result == _WAIT_FAILED:
                logger.warning("WaitForSingleObject a échoué en attendant PresentMon élevé")
    finally:
        ctypes.windll.kernel32.CloseHandle(info.hProcess)


_ROLLING_WINDOW = 45  # ~0.5-1s de moyenne glissante à 60-90 FPS


class FpsMonitorThread(QThread):
    """`fps_ready` envoie None (pas 0 ni une valeur inventée) tant qu'aucune
    frame réelle n'a été capturée — que ce soit au démarrage (élévation en
    attente/refusée) ou si le jeu ciblé se ferme en cours de route."""

    fps_ready = pyqtSignal(object)  # Optional[float]

    def __init__(self, process_name: str, parent=None):
        super().__init__(parent)
        self._process_name = process_name
        self._running = False
        self._tmp_csv = os.path.join(
            tempfile.gettempdir(), f"zenkai_fps_{os.getpid()}_{int(time.time())}.csv"
        )

    def run(self) -> None:
        self._running = True
        if not os.path.isfile(PRESENTMON_EXE):
            logger.error("PresentMon introuvable (%s)", PRESENTMON_EXE)
            self.fps_ready.emit(None)
            return

        try:
            _run_elevated_hidden(
                PRESENTMON_EXE,
                [
                    "--process_name", self._process_name,
                    "--output_file", self._tmp_csv,
                    "--no_console_stats",
                    "--terminate_on_proc_exit",
                    "--stop_existing_session",
                    "--session_name", _SESSION_NAME,
                ],
            )
        except Exception:
            logger.exception("Impossible de lancer PresentMon")
            self.fps_ready.emit(None)
            return

        self._tail_csv_until_stopped()
        self._terminate_session()
        self._cleanup_tmp_file()

    def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    def _tail_csv_until_stopped(self) -> None:
        offset = 0
        buffer = ""
        header_idx: Optional[int] = None
        values: deque = deque(maxlen=_ROLLING_WINDOW)
        got_any_row = False
        start = time.monotonic()

        while self._running:
            time.sleep(_POLL_INTERVAL_SECONDS)

            if not os.path.isfile(self._tmp_csv):
                if not got_any_row and time.monotonic() - start > _STARTUP_TIMEOUT_SECONDS:
                    self.fps_ready.emit(None)
                    return
                continue

            try:
                with open(self._tmp_csv, "r", newline="", encoding="utf-8", errors="ignore") as f:
                    f.seek(offset)
                    chunk = f.read()
                    offset = f.tell()
            except OSError:
                continue

            if not chunk:
                if not got_any_row and time.monotonic() - start > _STARTUP_TIMEOUT_SECONDS:
                    self.fps_ready.emit(None)
                    return
                continue

            buffer += chunk
            lines = buffer.split("\n")
            buffer = lines.pop()  # ligne potentiellement incomplète : gardée pour le prochain tour

            for line in lines:
                line = line.strip("\r")
                if not line:
                    continue
                fields = next(csv.reader([line]))

                if header_idx is None:
                    try:
                        header_idx = fields.index("MsBetweenPresents")
                    except ValueError:
                        header_idx = -1
                    continue

                if header_idx == -1 or header_idx >= len(fields):
                    continue
                try:
                    ms_between_presents = float(fields[header_idx])
                except ValueError:
                    continue
                if ms_between_presents > 0:
                    values.append(1000.0 / ms_between_presents)
                    got_any_row = True

            if values:
                self.fps_ready.emit(round(sum(values) / len(values), 1))

    def _terminate_session(self) -> None:
        try:
            _run_elevated_hidden(
                PRESENTMON_EXE,
                ["--session_name", _SESSION_NAME, "--terminate_existing_session"],
                wait_seconds=10,
            )
        except Exception:
            logger.warning("Impossible d'arrêter proprement la session PresentMon %s", _SESSION_NAME)

    def _cleanup_tmp_file(self) -> None:
        try:
            if os.path.isfile(self._tmp_csv):
                os.remove(self._tmp_csv)
        except OSError:
            pass
