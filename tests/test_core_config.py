"""
Tests (pytest) du gestionnaire de configuration persistante (core/config.py)
— chemin settings.json redirigé vers tmp_path. Instancie TOUJOURS un
ConfigManager() frais avec le chemin mocké AVANT construction (jamais le
singleton module-level `config`, qui pointe vers le vrai %APPDATA% de la
machine et est déjà partagé par tout le reste de l'app importée dans ce
process de test).
"""
import json

import core.config as config_mod
from core.config import DEFAULT_SETTINGS, ConfigManager


def _make_manager(tmp_path, monkeypatch, filename="settings.json"):
    path = str(tmp_path / filename)
    monkeypatch.setattr(config_mod, "get_settings_path", lambda: path)
    return ConfigManager(), path


def test_creates_default_settings_file_if_missing(tmp_path, monkeypatch):
    manager, path = _make_manager(tmp_path, monkeypatch)
    with open(path, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved == DEFAULT_SETTINGS
    assert manager.get("language") == DEFAULT_SETTINGS["language"]


def test_get_returns_default_for_unknown_key(tmp_path, monkeypatch):
    manager, _ = _make_manager(tmp_path, monkeypatch)
    assert manager.get("does_not_exist") is None
    assert manager.get("does_not_exist", "fallback") == "fallback"


def test_set_persists_immediately(tmp_path, monkeypatch):
    manager, path = _make_manager(tmp_path, monkeypatch)
    manager.set("language", "en")
    assert manager.get("language") == "en"
    with open(path, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["language"] == "en"


def test_reload_from_disk_picks_up_external_change(tmp_path, monkeypatch):
    manager, path = _make_manager(tmp_path, monkeypatch)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"language": "en", "custom_key": "custom_value"}, f)
    manager.load()
    assert manager.get("language") == "en"
    assert manager.get("custom_key") == "custom_value"


def test_load_merges_partial_file_with_defaults(tmp_path, monkeypatch):
    # Un settings.json d'une version antérieure (avant l'ajout d'un nouveau
    # réglage) ne doit jamais faire disparaître les valeurs par défaut des
    # clés qu'il ne connaît pas encore.
    manager, path = _make_manager(tmp_path, monkeypatch)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"language": "en"}, f)
    manager.load()
    assert manager.get("language") == "en"
    assert manager.get("macros_globally_enabled") == DEFAULT_SETTINGS["macros_globally_enabled"]


def test_corrupted_file_falls_back_to_defaults(tmp_path, monkeypatch):
    path = str(tmp_path / "settings.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not valid json")
    monkeypatch.setattr(config_mod, "get_settings_path", lambda: path)
    manager = ConfigManager()
    assert manager.get("language") == DEFAULT_SETTINGS["language"]
    # La restauration réécrit aussi un fichier valide sur disque.
    with open(path, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved == DEFAULT_SETTINGS


def test_non_dict_json_falls_back_to_defaults(tmp_path, monkeypatch):
    path = str(tmp_path / "settings.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump([1, 2, 3], f)
    monkeypatch.setattr(config_mod, "get_settings_path", lambda: path)
    manager = ConfigManager()
    assert manager.get("language") == DEFAULT_SETTINGS["language"]


def test_save_failure_does_not_raise(tmp_path, monkeypatch):
    # Chemin dans un dossier qui n'existe pas et ne sera jamais créé : save()
    # doit avaler l'erreur (jamais lever), pas planter l'appelant.
    bad_path = str(tmp_path / "no" / "such" / "dir" / "settings.json")
    monkeypatch.setattr(config_mod, "get_settings_path", lambda: bad_path)
    manager = ConfigManager()  # load() -> save() échoue silencieusement
    manager.set("language", "en")  # ne doit jamais lever
    assert manager.get("language") == "en"
