"""
Tests (pytest) du chargement des fichiers de config statiques (core/
static_config.py) — dossier config/ redirigé vers tmp_path.
"""
import json

import core.static_config as static_config_mod
from core.static_config import load_json_config


def test_loads_valid_json_object(tmp_path, monkeypatch):
    monkeypatch.setattr(static_config_mod, "_CONFIG_DIR", str(tmp_path))
    with open(tmp_path / "settings.json", "w", encoding="utf-8") as f:
        json.dump({"a": 1, "b": "two"}, f)
    assert load_json_config("settings.json") == {"a": 1, "b": "two"}


def test_missing_file_returns_empty_dict(tmp_path, monkeypatch):
    monkeypatch.setattr(static_config_mod, "_CONFIG_DIR", str(tmp_path))
    assert load_json_config("does_not_exist.json") == {}


def test_corrupted_json_returns_empty_dict(tmp_path, monkeypatch):
    monkeypatch.setattr(static_config_mod, "_CONFIG_DIR", str(tmp_path))
    with open(tmp_path / "corrupt.json", "w", encoding="utf-8") as f:
        f.write("{not valid json")
    assert load_json_config("corrupt.json") == {}


def test_non_object_json_returns_empty_dict(tmp_path, monkeypatch):
    monkeypatch.setattr(static_config_mod, "_CONFIG_DIR", str(tmp_path))
    with open(tmp_path / "list.json", "w", encoding="utf-8") as f:
        json.dump([1, 2, 3], f)
    assert load_json_config("list.json") == {}
