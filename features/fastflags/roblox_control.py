"""
Arrêt immédiat du client Roblox déjà lancé ("Kill Roblox", page Fast Flags)
— action GUI ponctuelle, distincte de launcher.py (qui doit rester léger,
utilisé aussi par le chemin headless du protocole roblox-player://, voir sa
docstring) : psutil n'est importé QUE dans ce module.
"""
import logging

import psutil

from core.security_log import Category, log_event

logger = logging.getLogger("zenkaiontop.fastflags.roblox_control")

_ROBLOX_PROCESS_NAME = "RobloxPlayerBeta.exe"


def kill_roblox() -> bool:
    """Termine tous les process RobloxPlayerBeta.exe trouvés (généralement
    un seul, mais rien n'empêche plusieurs instances) — kill() direct (pas
    terminate()) : fermer Roblox instantanément est tout le but de ce
    bouton, pas lui laisser le temps de réagir à un signal de fermeture
    propre. Renvoie True si au moins un process a été trouvé et tué, False
    si Roblox n'était simplement pas lancé (pas une erreur en soi)."""
    killed_any = False
    for proc in psutil.process_iter(["name"]):
        if proc.info.get("name") != _ROBLOX_PROCESS_NAME:
            continue
        try:
            proc.kill()
            killed_any = True
        except (psutil.AccessDenied, psutil.NoSuchProcess) as exc:
            logger.warning("Impossible de terminer %s (pid=%s) : %s", _ROBLOX_PROCESS_NAME, proc.pid, exc)

    log_event("roblox_kill", Category.EXTERNAL_EXECUTION, _ROBLOX_PROCESS_NAME, "ok" if killed_any else "error")
    return killed_any
