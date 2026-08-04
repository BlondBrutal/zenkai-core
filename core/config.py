"""
Gestion de la configuration persistante de l'application (settings.json).
Sauvegarde immédiate à chaque modification, restauration des valeurs par
défaut si le fichier est corrompu (jamais de crash au démarrage pour ça).
"""
import json
import logging
import os

from core.paths import get_settings_path

logger = logging.getLogger("zenkaiontop.config")

DEFAULT_SETTINGS = {
    "language": "fr",
    "first_run_done": False,
    "auto_apply_fastflags_on_launch": False,
    "active_fastflags_preset": None,
    "performance_live_monitoring_enabled": True,
    "macros_globally_enabled": True,
    "risk_analysis_enabled": True,
    "cursor_general_image_path": "",
    "cursor_general_size": 32,
    "cursor_roblox_image_path": "",
    "cursor_roblox_size": 32,
    "performance_overlay_enabled": False,
    "performance_overlay_elements": ["cpu", "ram", "gpu", "disk"],
    "performance_overlay_bg_opacity": 85,
    "performance_overlay_text_opacity": 100,
    "performance_overlay_font_size": 13,
    "performance_overlay_pos_x": None,
    "performance_overlay_pos_y": None,
}


class ConfigManager:
    """Petit gestionnaire de config JSON, en mémoire + sauvegarde disque."""

    def __init__(self):
        self._path = get_settings_path()
        self._data = dict(DEFAULT_SETTINGS)
        self.load()

    def load(self) -> None:
        if not os.path.exists(self._path):
            self.save()
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                raise ValueError("settings.json ne contient pas un objet JSON valide")
            merged = dict(DEFAULT_SETTINGS)
            merged.update(loaded)
            self._data = merged
        except Exception as exc:
            logger.error("settings.json corrompu ou illisible (%s), restauration des valeurs par défaut", exc)
            self._data = dict(DEFAULT_SETTINGS)
            self.save()

    def save(self) -> None:
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.error("Impossible d'écrire settings.json : %s", exc)

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        self._data[key] = value
        self.save()


# Instance unique partagée par toute l'app
config = ConfigManager()
