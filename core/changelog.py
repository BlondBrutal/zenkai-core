"""
Lecture du changelog de l'application (CHANGELOG.json, à la racine du
dépôt) : une entrée par version publiée, jamais de texte en dur dans le
code — pour publier une nouvelle version, il suffit d'ajouter une entrée en
TÊTE de ce fichier (voir sa structure ci-dessous), rien à changer dans le
code Python. La version affichée sur la page Paramètres (voir
current_version) est TOUJOURS celle de la première entrée de ce fichier :
une seule source de vérité, jamais une chaîne à resynchroniser à part.

Format de CHANGELOG.json (liste JSON, la plus RÉCENTE en premier) :
[
  {
    "version": "1.0",
    "date": "2026-08-16",
    "added": ["Ajout majeur 1", "Ajout majeur 2"],
    "fixed": ["Correction 1", "Correction 2"]
  },
  ...
]
"""
import json
import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger("zenkaiontop.changelog")

# core/changelog.py -> core -> racine du dépôt (même convention locale que
# _REPO_ROOT dans features/custom_script/ahk_detect.py, un niveau de moins
# ici puisque ce module vit directement sous core/).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CHANGELOG_PATH = os.path.join(_REPO_ROOT, "CHANGELOG.json")


@dataclass
class ChangelogEntry:
    version: str
    date: str
    added: list = field(default_factory=list)
    fixed: list = field(default_factory=list)


def load_changelog() -> list[ChangelogEntry]:
    """Liste des entrées, la plus récente en premier (ordre du fichier,
    jamais retrié) — ne lève jamais : liste vide si le fichier est
    absent/corrompu/mal formé, jamais un crash de la page Paramètres pour
    ça (même principe que core/security_log.py::read_events)."""
    try:
        with open(_CHANGELOG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError("CHANGELOG.json ne contient pas une liste JSON")
        return [
            ChangelogEntry(
                version=str(entry.get("version", "")),
                date=str(entry.get("date", "")),
                added=[str(item) for item in entry.get("added", [])],
                fixed=[str(item) for item in entry.get("fixed", [])],
            )
            for entry in data
        ]
    except Exception as exc:
        logger.warning("CHANGELOG.json illisible (%s) : %s", _CHANGELOG_PATH, exc)
        return []


def current_version() -> str:
    """Version affichée sur la carte "Notes des développeurs" : celle de
    l'entrée la plus récente (première du fichier) — "?" si le changelog
    est absent/vide, jamais une exception."""
    entries = load_changelog()
    return entries[0].version if entries else "?"
