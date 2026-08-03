"""
Configuration des logs de l'application (fichier + rotation simple).
"""
import logging
import os
from logging.handlers import RotatingFileHandler

from core.paths import get_logs_dir


def setup_logging() -> None:
    log_path = os.path.join(get_logs_dir(), "zenkaiontop.log")
    handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))

    root = logging.getLogger("zenkaiontop")
    root.setLevel(logging.INFO)
    root.addHandler(handler)
