"""
Logique de vérification de licence : format de clé, appel réseau vers le
registre central (Gist GitHub privé, voir Partie 4.3 du brief), grâce
hors-ligne de 3 jours, et thread dédié pour ne jamais bloquer l'UI pendant
la requête réseau (timeout court, ~3s).
"""
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

import requests
from PyQt6.QtCore import QThread, pyqtSignal

from core.static_config import load_json_config
from features.license.license_store import LicenseData, clear_license, load_license, save_license

logger = logging.getLogger("zenkaiontop.license")

KEY_FORMAT_RE = re.compile(r"^ZK-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$")


class LicenseStatus(Enum):
    VALID = "valid"                      # clé active, vérifiée en ligne à l'instant
    VALID_OFFLINE_GRACE = "grace"        # pas d'accès réseau, mais dans la fenêtre de grâce de 3 jours
    NO_KEY = "no_key"                    # aucune clé enregistrée localement
    NOT_FOUND = "not_found"              # clé absente du registre (ou plus jamais valide)
    DEACTIVATED = "deactivated"          # clé présente mais actif=false
    OFFLINE_EXPIRED = "offline_expired"  # pas de réseau et grâce dépassée
    REGISTRY_ERROR = "registry_error"    # registre injoignable et pas de cache local exploitable


@dataclass
class LicenseCheckResult:
    status: LicenseStatus
    nom: Optional[str] = None
    days_left: Optional[int] = None


def _mask_key(key: str) -> str:
    """Ne jamais logger une clé en clair (Partie 4.4 du brief)."""
    return "ZK-****-****-" + key[-4:] if len(key) >= 4 else "****"


def validate_key_format(key: str) -> bool:
    return bool(KEY_FORMAT_RE.match(key.strip().upper()))


def _license_config() -> dict:
    return load_json_config("license_config.json")


def _check_offline_grace(local: LicenseData) -> LicenseCheckResult:
    last_check = local.get("last_check_ok")
    if not last_check:
        return LicenseCheckResult(LicenseStatus.OFFLINE_EXPIRED)
    try:
        last_dt = datetime.fromisoformat(last_check)
    except ValueError:
        return LicenseCheckResult(LicenseStatus.OFFLINE_EXPIRED)

    grace_days = int(_license_config().get("grace_days", 3))
    remaining = timedelta(days=grace_days) - (datetime.now(timezone.utc) - last_dt)
    if remaining.total_seconds() > 0:
        return LicenseCheckResult(
            LicenseStatus.VALID_OFFLINE_GRACE,
            nom=local.get("nom"),
            days_left=max(1, remaining.days + 1),
        )
    return LicenseCheckResult(LicenseStatus.OFFLINE_EXPIRED)


def check_key_online(key: str) -> LicenseCheckResult:
    """Vérifie une clé auprès du registre central. Ne lève jamais d'exception :
    tout problème réseau retombe sur la grâce hors-ligne locale si disponible."""
    key = key.strip().upper()
    local = load_license()
    cfg = _license_config()
    url = cfg.get("registry_url", "")

    if not url:
        logger.error("Aucune registry_url configurée dans config/license_config.json")
        return LicenseCheckResult(LicenseStatus.REGISTRY_ERROR)

    try:
        timeout = float(cfg.get("network_timeout_seconds", 3))
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        registry = response.json()
        if not isinstance(registry, dict):
            raise ValueError("registre distant mal formé")
    except Exception as exc:
        logger.warning("Registre de licences injoignable (%s) pour la clé %s", exc, _mask_key(key))
        if local and local.get("key") == key:
            return _check_offline_grace(local)
        return LicenseCheckResult(LicenseStatus.REGISTRY_ERROR)

    entry = registry.get(key)
    if entry is None:
        logger.info("Clé %s absente du registre", _mask_key(key))
        # Réponse définitive du serveur : on efface le cache local pour fermer
        # toute fenêtre de grâce hors-ligne restante sur cette clé.
        clear_license()
        return LicenseCheckResult(LicenseStatus.NOT_FOUND)

    if not entry.get("actif", False):
        logger.info("Clé %s désactivée côté registre", _mask_key(key))
        clear_license()
        return LicenseCheckResult(LicenseStatus.DEACTIVATED)

    now_iso = datetime.now(timezone.utc).isoformat()
    save_license({"key": key, "nom": entry.get("nom", ""), "last_check_ok": now_iso})
    logger.info("Clé %s validée en ligne", _mask_key(key))
    return LicenseCheckResult(LicenseStatus.VALID, nom=entry.get("nom"))


def check_saved_license() -> LicenseCheckResult:
    """À utiliser au démarrage / bouton Revérifier : reprend la clé locale si
    elle existe et la revérifie en ligne."""
    local = load_license()
    if not local or not local.get("key"):
        return LicenseCheckResult(LicenseStatus.NO_KEY)
    return check_key_online(local["key"])


class LicenseCheckWorker(QThread):
    """Exécute la vérification réseau dans un thread séparé pour ne jamais
    geler l'UI, même si le timeout de 3s est atteint."""

    finished_check = pyqtSignal(object)  # LicenseCheckResult

    def __init__(self, key: Optional[str] = None, parent=None):
        super().__init__(parent)
        self._key = key

    def run(self) -> None:
        result = check_key_online(self._key) if self._key is not None else check_saved_license()
        self.finished_check.emit(result)
