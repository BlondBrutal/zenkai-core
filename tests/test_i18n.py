"""
Tests (pytest) du système de traduction minimal (core/i18n.py) — dossier de
traductions redirigé vers tmp_path (jamais le vrai translations/), cache
module-level réinitialisé avant/après chaque test pour ne jamais laisser un
test polluer l'état global partagé (_cache/_current_lang) pour le suivant.
"""
import json

import pytest

import core.i18n as i18n_mod
from core.i18n import get_language, set_language, t


@pytest.fixture(autouse=True)
def isolated_translations(tmp_path, monkeypatch):
    monkeypatch.setattr(i18n_mod, "_TRANSLATIONS_DIR", str(tmp_path))
    monkeypatch.setattr(i18n_mod, "_cache", {})
    monkeypatch.setattr(i18n_mod, "_current_lang", "fr")

    with open(tmp_path / "fr.json", "w", encoding="utf-8") as f:
        json.dump({"greeting": "Bonjour", "app_name": "Zenkai Core"}, f)
    with open(tmp_path / "en.json", "w", encoding="utf-8") as f:
        json.dump({"greeting": "Hello"}, f)

    return tmp_path


def test_t_returns_translation_in_current_language():
    assert t("greeting") == "Bonjour"


def test_t_returns_key_itself_when_missing():
    assert t("does.not.exist") == "does.not.exist"


def test_set_language_switches_translations():
    set_language("en")
    assert t("greeting") == "Hello"
    assert get_language() == "en"


def test_set_language_back_to_fr_still_works():
    set_language("en")
    set_language("fr")
    assert t("greeting") == "Bonjour"


def test_missing_language_file_falls_back_to_raw_key():
    set_language("de")  # de.json n'existe pas
    assert t("greeting") == "greeting"
    assert get_language() == "de"


def test_corrupted_language_file_falls_back_to_raw_key(tmp_path):
    with open(tmp_path / "es.json", "w", encoding="utf-8") as f:
        f.write("{not valid json")
    set_language("es")
    assert t("greeting") == "greeting"


def test_get_language_defaults_to_fr_before_any_set_language():
    assert get_language() == "fr"


def test_language_file_loaded_only_once_then_cached(tmp_path):
    set_language("fr")
    t("greeting")
    # Modifie le fichier APRÈS le premier chargement : le cache doit
    # continuer à servir l'ancienne valeur tant que set_language() ne
    # redéclenche pas un rechargement.
    with open(tmp_path / "fr.json", "w", encoding="utf-8") as f:
        json.dump({"greeting": "Salut (modifié)"}, f)
    assert t("greeting") == "Bonjour"
