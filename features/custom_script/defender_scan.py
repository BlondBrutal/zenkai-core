"""
Scan Windows Defender à la demande d'un fichier .ahk unique, via
MpCmdRun.exe -Scan -ScanType 3 -File <chemin>. Résolution du chemin par
glob sur le dossier versionné (même technique que
features/fastflags/launcher.py::find_roblox_player_exe : "le plus récent
dossier de version qui contient réellement l'exe gagne").

Code de sortie 0 = propre. TOUT AUTRE CAS (non-zéro, timeout, exception,
MpCmdRun introuvable) est traité comme "non confirmé propre" — jamais
"sûr" affiché dans l'UI, voir DefenderScanResult.clean (bool | None, jamais
un simple bool).
"""
import logging
import os
import subprocess

from features.performance.fixes import _hidden_subprocess_kwargs

logger = logging.getLogger("zenkaiontop.custom_script")

_DEFENDER_PLATFORM_DIR = os.path.join(
    os.environ.get("ProgramData", r"C:\ProgramData"), "Microsoft", "Windows Defender", "platform",
)
_SCAN_TIMEOUT_SECONDS = 90.0


class DefenderScanResult:
    def __init__(self, available: bool, clean: bool | None, exit_code: int | None, raw_output: str):
        self.available = available  # False = MpCmdRun.exe introuvable, aucun scan réel effectué
        self.clean = clean  # None = pas concluant (timeout/erreur) ; jamais interprété comme sûr
        self.exit_code = exit_code
        self.raw_output = raw_output


def find_mpcmdrun() -> str | None:
    if not os.path.isdir(_DEFENDER_PLATFORM_DIR):
        return None
    try:
        candidates = [
            e for e in os.listdir(_DEFENDER_PLATFORM_DIR)
            if os.path.isdir(os.path.join(_DEFENDER_PLATFORM_DIR, e))
        ]
    except OSError as exc:
        logger.warning("Impossible de lister %s (%s)", _DEFENDER_PLATFORM_DIR, exc)
        return None
    candidates.sort(key=lambda e: os.path.getmtime(os.path.join(_DEFENDER_PLATFORM_DIR, e)), reverse=True)
    for entry in candidates:
        exe = os.path.join(_DEFENDER_PLATFORM_DIR, entry, "MpCmdRun.exe")
        if os.path.isfile(exe):
            return exe
    return None


def scan_file(file_path: str, timeout_seconds: float = _SCAN_TIMEOUT_SECONDS) -> DefenderScanResult:
    exe = find_mpcmdrun()
    if exe is None:
        return DefenderScanResult(available=False, clean=None, exit_code=None, raw_output="")
    try:
        result = subprocess.run(
            [exe, "-Scan", "-ScanType", "3", "-File", file_path],
            capture_output=True, text=True, timeout=timeout_seconds, errors="replace",
            **_hidden_subprocess_kwargs(),
        )
        return DefenderScanResult(
            available=True, clean=(result.returncode == 0), exit_code=result.returncode,
            raw_output=(result.stdout or "") + (result.stderr or ""),
        )
    except subprocess.TimeoutExpired:
        logger.warning("Scan Defender interrompu par timeout (%s)", file_path)
        return DefenderScanResult(available=True, clean=None, exit_code=None, raw_output="timeout")
    except Exception as exc:
        logger.error("Échec du scan Defender (%s)", exc)
        return DefenderScanResult(available=True, clean=None, exit_code=None, raw_output=str(exc))
