"""
Journal de sécurité : trace les actions "sensibles" faites par l'app pour
le compte de l'utilisateur (écriture registre, modification de
ClientAppSettings.json, élévation UAC, corrections Windows automatiques...)
dans un fichier séparé du log applicatif classique (core/logging_setup.py),
pour que l'utilisateur puisse les consulter lui-même (page Paramètres,
bouton "Voir les logs" — voir ui/pages/page_settings.py).

Format JSON Lines (une action = une ligne JSON) : ajouter une entrée ne
demande jamais de relire/réécrire tout le fichier, et une ligne corrompue
(écriture interrompue par une coupure de courant, édition manuelle...) ne
peut jamais casser la lecture des autres.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime

from core.paths import get_security_log_path

logger = logging.getLogger("zenkaiontop.security")

# Au-delà de ce nombre d'entrées, seules les plus récentes ont un intérêt
# pour l'affichage (voir read_events) — le fichier lui-même n'est jamais
# tronqué, seule la LECTURE s'arrête plus tôt.
_DEFAULT_READ_LIMIT = 500


@dataclass
class SecurityEvent:
    timestamp: str  # ISO 8601, heure locale (voir log_event)
    action: str  # code court, ex. "protocol_register" — traduit à l'affichage
    target: str  # ce qui a été modifié (chemin de fichier, clé de registre...)
    result: str  # "ok" ou "error"
    sensitive: bool  # affiché en évidence (couleur d'avertissement) côté UI


def log_event(action: str, target: str, result: str, sensitive: bool = False) -> None:
    """Ajoute une ligne au journal de sécurité. Ne lève jamais : une erreur
    d'écriture ici (disque plein, permissions...) est seulement journalisée
    dans le log applicatif normal — enregistrer une action ne doit jamais
    faire échouer l'action elle-même (même principe que
    features/fastflags/launcher.py pour l'injection des Fast Flags)."""
    event = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "action": action,
        "target": target,
        "result": result,
        "sensitive": sensitive,
    }
    try:
        with open(get_security_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.error("Impossible d'écrire dans le journal de sécurité (%s)", exc)


def read_events(limit: int = _DEFAULT_READ_LIMIT) -> list[SecurityEvent]:
    """Relit le journal et renvoie jusqu'à `limit` événements, les plus
    récents en premier (voir _SecurityLogDialog). Liste vide si le fichier
    n'existe pas encore (aucune action sensible journalisée pour l'instant)
    — ce n'est jamais une erreur en soi."""
    events: list[SecurityEvent] = []
    try:
        with open(get_security_log_path(), "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return events

    # Le fichier est écrit dans l'ordre chronologique (append-only) : on le
    # relit à l'envers pour obtenir directement "le plus récent en premier"
    # sans avoir à trier après coup.
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            events.append(SecurityEvent(
                timestamp=data["timestamp"],
                action=data["action"],
                target=data["target"],
                result=data["result"],
                sensitive=bool(data.get("sensitive", False)),
            ))
        except (json.JSONDecodeError, KeyError):
            # Ligne corrompue (écriture interrompue, édition manuelle...) :
            # ignorée plutôt que de faire échouer toute la lecture.
            continue
        if len(events) >= limit:
            break
    return events
