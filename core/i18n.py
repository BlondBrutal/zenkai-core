"""
Système de traduction minimal. Charge translations/<lang>.json au démarrage
et expose une fonction t("clé") utilisable partout dans l'app.
"""
import json
import logging
import os

logger = logging.getLogger("zenkaiontop.i18n")

_TRANSLATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "translations")

_cache: dict[str, dict] = {}
_current_lang = "fr"


def _load_lang(lang: str) -> dict:
    if lang in _cache:
        return _cache[lang]
    path = os.path.join(_TRANSLATIONS_DIR, f"{lang}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        logger.error("Impossible de charger la langue '%s' (%s), repli sur clés brutes", lang, exc)
        data = {}
    _cache[lang] = data
    return data


def set_language(lang: str) -> None:
    global _current_lang
    _current_lang = lang
    _load_lang(lang)


def get_language() -> str:
    return _current_lang


def t(key: str) -> str:
    """Retourne la traduction de `key` dans la langue courante.
    Si la clé est absente, retourne la clé elle-même (jamais de crash)."""
    data = _load_lang(_current_lang)
    return data.get(key, key)
