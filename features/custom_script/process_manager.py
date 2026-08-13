"""
Suivi et arrêt fiable des scripts AHK lancés depuis la page Custom Script —
aucun pattern équivalent n'existait encore dans le repo (aucun
psutil.pid_exists, aucun taskkill nulle part ailleurs). Deux chemins de
lancement selon core.elevation.is_admin() :

- App PAS élevée : subprocess.Popen direct (pas de jeton élevé à retirer) —
  on garde le vrai handle Popen.
- App élevée : passage obligé par deelevate.py (lancement dé-élevé via une
  tâche planifiée jetable — voir sa docstring pour le pourquoi de ce choix,
  CreateProcessAsUser ayant été abandonné après diagnostic), qui renvoie
  déjà un vrai PID.

Dans les deux cas, RunningScript.pid est donc TOUJOURS connu immédiatement
(pas de recherche de PID a posteriori par correspondance de ligne de
commande, contrairement à l'astuce "Shell.Application via explorer.exe"
écartée lors de la conception).

Arrêt INSTANTANÉ et forcé — même principe qu'un "Quitter" déclenché depuis
la zone de notification Windows (clic droit sur l'icône -> Quitter) :
aucune tentative de fermeture "propre" (plus de WM_CLOSE, plus d'attente
avant de forcer) — kill() immédiat, avec seulement une confirmation
bloquante (courte) pour garantir que le process a bien disparu avant de
rendre la main. Jamais d'exception vers l'appelant — stop_script retourne
False si l'arrêt n'a pas pu être confirmé, l'UI doit alors avertir plutôt
que prétendre "arrêté".
"""
import logging
import os
import subprocess
import time
from dataclasses import dataclass

import psutil

from core.elevation import is_admin
from core.security_log import Category, log_event
from features.custom_script.ahk_detect import find_ahk_interpreter
from features.custom_script.deelevate import launch_deelevated
from features.custom_script.script_store import CustomScriptEntry, ahk_companion_path
from features.performance.fixes import _hidden_subprocess_kwargs

logger = logging.getLogger("zenkaiontop.custom_script")

_KILL_CONFIRM_TIMEOUT_SECONDS = 3.0
_KILL_CONFIRM_POLL_INTERVAL_SECONDS = 0.05


@dataclass
class RunningScript:
    entry_id: str
    pid: int
    popen: "subprocess.Popen | None"  # présent seulement pour le chemin non-admin (handle direct)
    exe_path: str
    script_path: str
    started_at: float


def write_companion_ahk_file(entry: CustomScriptEntry, zkscript_path: str) -> str:
    """Régénère TOUJOURS le .ahk juste avant un lancement/scan, à partir de
    entry.script_text (source de vérité) — jamais réutilisé d'un lancement
    précédent, pour garantir que ce qui tourne/est scanné correspond
    exactement au texte qui vient d'être analysé/sauvegardé."""
    ahk_path = ahk_companion_path(zkscript_path)
    with open(ahk_path, "w", encoding="utf-8") as f:
        f.write(entry.script_text)
    return ahk_path


def start_script(entry: CustomScriptEntry, zkscript_path: str) -> tuple[RunningScript | None, str | None]:
    """(RunningScript, None) si succès, (None, détail_erreur) sinon —
    détail_erreur est un message diagnostique lisible (inclut le code
    d'erreur Windows réel pour un échec côté lancement dé-élevé, voir
    deelevate.py::DeelevationResult) destiné à être affiché tel quel dans
    l'UI, pas seulement journalisé. `None` pour les deux si l'interpréteur
    AutoHotkey lui-même est introuvable (cas déjà couvert par un message
    dédié en amont, voir page_custom_script.py::ahk_detect.health_check)."""
    exe_path = find_ahk_interpreter()
    if exe_path is None:
        return None, None
    script_path = write_companion_ahk_file(entry, zkscript_path)
    workdir = os.path.dirname(exe_path)

    if is_admin():
        result = launch_deelevated(exe_path, [script_path], workdir)
        if result.error_detail is not None:
            log_event(
                "custom_script_launch", Category.SCRIPT_EXECUTION,
                f"{entry.name} — {result.error_detail}", "error",
            )
            return None, result.error_detail
        log_event("custom_script_launch", Category.SCRIPT_EXECUTION, entry.name, "ok")
        return RunningScript(entry.id, result.pid, None, exe_path, script_path, time.monotonic()), None

    try:
        proc = subprocess.Popen([exe_path, script_path], cwd=workdir, **_hidden_subprocess_kwargs())
    except OSError as exc:
        detail = str(exc)
        logger.error("Impossible de lancer %s : %s", exe_path, detail)
        log_event("custom_script_launch", Category.SCRIPT_EXECUTION, f"{entry.name} — {detail}", "error")
        return None, detail
    log_event("custom_script_launch", Category.SCRIPT_EXECUTION, entry.name, "ok")
    return RunningScript(entry.id, proc.pid, proc, exe_path, script_path, time.monotonic()), None


def stop_script(running: RunningScript) -> bool:
    """Poll .poll()/psutil d'abord (déjà sorti tout seul ?), puis kill()
    immédiat — aucune tentative de fermeture propre, aucune attente avant
    de forcer (équivalent "Quitter" depuis la zone de notification
    Windows). Jamais d'exception vers l'appelant — retourne False si
    l'arrêt n'a pas pu être confirmé."""
    if running.popen is not None and running.popen.poll() is not None:
        log_event("custom_script_stop", Category.SCRIPT_EXECUTION, running.script_path, "ok")
        return True
    try:
        proc = psutil.Process(running.pid)
        if not proc.is_running():
            log_event("custom_script_stop", Category.SCRIPT_EXECUTION, running.script_path, "ok")
            return True
    except psutil.NoSuchProcess:
        log_event("custom_script_stop", Category.SCRIPT_EXECUTION, running.script_path, "ok")
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
        log_event("custom_script_stop", Category.SCRIPT_EXECUTION, running.script_path, "error")
        return False

    log_event("custom_script_stop", Category.SCRIPT_EXECUTION, running.script_path, "ok")
    return True
