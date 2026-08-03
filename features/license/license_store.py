"""
Lecture/écriture du fichier local license.dat (clé + cache de dernière
vérification réussie). Contenu légèrement obfusqué (voir crypto_utils),
jamais en clair sur le disque. Aucun crash possible : un fichier corrompu
est simplement ignoré et supprimé pour repartir proprement.
"""
import json
import logging
import os
from typing import Optional, TypedDict

from core.paths import get_license_path
from features.license.crypto_utils import deobfuscate, obfuscate

logger = logging.getLogger("zenkaiontop.license")


class LicenseData(TypedDict, total=False):
    key: str
    nom: str
    last_check_ok: Optional[str]  # ISO 8601 UTC de la dernière vérification en ligne réussie


def load_license() -> Optional[LicenseData]:
    path = get_license_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            obfuscated = f.read()
        data = json.loads(deobfuscate(obfuscated))
        if not isinstance(data, dict) or not data.get("key"):
            raise ValueError("license.dat ne contient pas les champs attendus")
        return data
    except Exception as exc:
        logger.error("license.dat corrompu ou illisible (%s), suppression pour repartir proprement", exc)
        clear_license()
        return None


def save_license(data: LicenseData) -> None:
    path = get_license_path()
    try:
        obfuscated = obfuscate(json.dumps(data, ensure_ascii=False))
        with open(path, "w", encoding="utf-8") as f:
            f.write(obfuscated)
    except Exception as exc:
        logger.error("Impossible d'écrire license.dat : %s", exc)


def clear_license() -> None:
    path = get_license_path()
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as exc:
        logger.error("Impossible de supprimer license.dat : %s", exc)
