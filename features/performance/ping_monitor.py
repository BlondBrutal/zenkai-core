"""
Ping vers le serveur de jeu auquel Roblox (ROBLOX_PROCESS_NAME, voir
page_performance.py) est connecté, pour l'élément "Ping" de l'overlay
Performance.

L'IP à pinguer n'est jamais codée en dur : elle se déduit dynamiquement de la
première connexion TCP établie du processus ciblé (voir _resolve_remote_ip)
plutôt que de viser une IP Roblox fixe, qui varie selon le serveur de jeu
assigné à la session en cours.
"""
import logging
import re
import subprocess
import sys
import time
from typing import Optional

import psutil
from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger("zenkaiontop.performance")

_PING_INTERVAL_SECONDS = 1.5
_PING_TIMEOUT_MS = 1000
_TIME_PATTERN = re.compile(r"(?:temps|time)[<=](\d+)\s*ms", re.IGNORECASE)


def _hidden_subprocess_kwargs() -> dict:
    """creationflags/startupinfo pour ne jamais afficher de fenêtre de
    console (CREATE_NO_WINDOW seul suffit généralement, le STARTUPINFO
    SW_HIDE est là pour plus de fiabilité) — ce ping tourne en boucle tant
    que l'overlay affiche l'élément "Ping", même principe que le bug
    nvidia-smi corrigé dans live_monitor.py."""
    if sys.platform != "win32":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {"creationflags": subprocess.CREATE_NO_WINDOW, "startupinfo": startupinfo}


class PingMonitorThread(QThread):
    """Un ping par cycle vers l'IP distante du processus ciblé. `ping_ready`
    envoie None (pas une valeur inventée) si le processus est introuvable ou
    n'a aucune connexion établie pour le moment."""

    ping_ready = pyqtSignal(object)  # Optional[float] (ms)

    def __init__(self, process_name: str, parent=None):
        super().__init__(parent)
        self._process_name = process_name
        self._running = False
        self._last_ip: Optional[str] = None

    def run(self) -> None:
        self._running = True
        while self._running:
            ip = self._resolve_remote_ip()
            ping_ms = self._ping(ip) if ip else None
            self.ping_ready.emit(ping_ms)

            # Attente découpée en petits pas : réagit vite à stop() plutôt que
            # de bloquer jusqu'à _PING_INTERVAL_SECONDS entières.
            for _ in range(int(_PING_INTERVAL_SECONDS * 10)):
                if not self._running:
                    break
                time.sleep(0.1)

    def stop(self) -> None:
        self._running = False

    def _resolve_remote_ip(self) -> Optional[str]:
        try:
            for proc in psutil.process_iter(["name"]):
                if proc.info.get("name") != self._process_name:
                    continue
                try:
                    connections = proc.net_connections(kind="tcp")
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    continue
                for conn in connections:
                    if conn.status == psutil.CONN_ESTABLISHED and conn.raddr:
                        self._last_ip = conn.raddr.ip
                        return self._last_ip
        except Exception:
            logger.exception("Erreur pendant la résolution de l'IP distante pour le ping")
        return self._last_ip

    def _ping(self, ip: str) -> Optional[float]:
        try:
            result = subprocess.run(
                ["ping", "-n", "1", "-w", str(_PING_TIMEOUT_MS), ip],
                capture_output=True,
                text=True,
                timeout=(_PING_TIMEOUT_MS / 1000) + 1,
                **_hidden_subprocess_kwargs(),
            )
            match = _TIME_PATTERN.search(result.stdout)
            if match:
                return float(match.group(1))
        except Exception:
            logger.warning("Ping échoué vers %s", ip)
        return None
