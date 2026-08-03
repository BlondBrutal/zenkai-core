"""
Chargement des petits fichiers de config statiques du projet (dossier config/),
distincts de la config utilisateur persistante (%APPDATA%, voir core/config.py).
Jamais de crash si le fichier est absent ou invalide : on retombe sur un dict vide.
"""
import json
import logging
import os

logger = logging.getLogger("zenkaiontop.static_config")

_CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")


def load_json_config(filename: str) -> dict:
    path = os.path.join(_CONFIG_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("le fichier ne contient pas un objet JSON")
        return data
    except Exception as exc:
        logger.error("Impossible de charger config/%s (%s)", filename, exc)
        return {}
