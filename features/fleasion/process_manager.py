"""
Lancement/arrêt du process Fleasion — PARTAGÉ entre tous les presets actifs,
contrairement à AutoHotkey où chaque script a son propre interpréteur (voir
features/custom_script/process_manager.py) : Fleasion est une appli tray
unique qui charge elle-même tous les fichiers de configs\\ZenkaiCore\\ au
démarrage (voir features/fleasion/config_writer.py), il n'y a donc jamais
qu'UN SEUL process à suivre ici, jamais un par preset.

Même stratégie d'élévation que Custom Script : lancement dé-élevé via le
Planificateur de tâches (features/custom_script/deelevate.py, réutilisé TEL
QUEL — aucune logique spécifique à AutoHotkey dedans, voir sa docstring) si
l'app tourne élevée, subprocess.Popen direct sinon.

Le comptage de "combien de presets actifs ont besoin du process" reste dans
ui/pages/page_fleasion.py (comme CustomScriptPage._running) — ce module ne
connaît qu'un unique process partagé (start_fleasion/stop_fleasion), pas de
dict par entrée comme pour les scripts AutoHotkey.
"""
import logging
import os
import subprocess
import time
from dataclasses import dataclass

import psutil

from core.elevation import is_admin
from core.security_log import Category, log_event
from features.custom_script.deelevate import launch_deelevated
from features.fleasion.fleasion_detect import find_fleasion_interpreter
from features.performance.fixes import _hidden_subprocess_kwargs

logger = logging.getLogger("zenkaiontop.fleasion")

_KILL_CONFIRM_TIMEOUT_SECONDS = 3.0
_KILL_CONFIRM_POLL_INTERVAL_SECONDS = 0.05


@dataclass
class RunningFleasion:
    pid: int
    popen: "subprocess.Popen | None"  # présent seulement pour le chemin non-admin (handle direct)
    exe_path: str
    started_at: float


def start_fleasion() -> tuple[RunningFleasion | None, str | None]:
    """(RunningFleasion, None) si succès, (None, détail_erreur) sinon —
    (None, None) si l'exécutable Fleasion lui-même est introuvable (cas déjà
    couvert par un message dédié en amont, voir
    ui/pages/page_fleasion.py::fleasion_detect.health_check)."""
    exe_path = find_fleasion_interpreter()
    if exe_path is None:
        return None, None
    workdir = os.path.dirname(exe_path)

    if is_admin():
        result = launch_deelevated(exe_path, [], workdir)
        if result.error_detail is not None:
            log_event("fleasion_launch", Category.EXTERNAL_EXECUTION, f"Fleasion — {result.error_detail}", "error")
            return None, result.error_detail
        log_event("fleasion_launch", Category.EXTERNAL_EXECUTION, "Fleasion", "ok")
        return RunningFleasion(result.pid, None, exe_path, time.monotonic()), None

    try:
        proc = subprocess.Popen([exe_path], cwd=workdir, **_hidden_subprocess_kwargs())
    except OSError as exc:
        detail = str(exc)
        logger.error("Impossible de lancer %s : %s", exe_path, detail)
        log_event("fleasion_launch", Category.EXTERNAL_EXECUTION, f"Fleasion — {detail}", "error")
        return None, detail
    log_event("fleasion_launch", Category.EXTERNAL_EXECUTION, "Fleasion", "ok")
    return RunningFleasion(proc.pid, proc, exe_path, time.monotonic()), None


def stop_fleasion(running: RunningFleasion) -> bool:
    """Même politique d'arrêt immédiat/forcé que
    features/custom_script/process_manager.py::stop_script (voir sa
    docstring) : jamais de fermeture "propre" attendue, kill() direct avec
    confirmation bloquante courte. Jamais d'exception vers l'appelant —
    retourne False si l'arrêt n'a pas pu être confirmé."""
    if running.popen is not None and running.popen.poll() is not None:
        log_event("fleasion_stop", Category.EXTERNAL_EXECUTION, "Fleasion", "ok")
        return True
    try:
        proc = psutil.Process(running.pid)
        if not proc.is_running():
            log_event("fleasion_stop", Category.EXTERNAL_EXECUTION, "Fleasion", "ok")
            return True
    except psutil.NoSuchProcess:
        log_event("fleasion_stop", Category.EXTERNAL_EXECUTION, "Fleasion", "ok")
        return True

    try:
        if running.popen is not None:
            running.popen.kill()
            running.popen.wait(timeout=_KILL_CONFIRM_TIMEOUT_SECONDS)
        else:
            psutil.Process(running.pid).kill()
        deadline = time.monotonic() + _KILL_CONFIRM_TIMEOUT_SECONDS
        while time.monotonic() < deadline and psutil.pid_exists(running.pid):
            time.sleep(_KILL_CONFIRM_POLL_INTERVAL_SECONDS)
        if psutil.pid_exists(running.pid):
            raise RuntimeError("process still alive after kill")
    except Exception:
        logger.error("Impossible de confirmer l'arrêt du PID %s", running.pid)
        log_event("fleasion_stop", Category.EXTERNAL_EXECUTION, "Fleasion", "error")
        return False

    log_event("fleasion_stop", Category.EXTERNAL_EXECUTION, "Fleasion", "ok")
    return True
