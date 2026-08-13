"""
Journal de sécurité : trace les actions "sensibles" faites par l'app pour
le compte de l'utilisateur (écriture registre, modification de
ClientAppSettings.json, élévation UAC, exécution de binaires externes,
corrections Windows automatiques...) dans un fichier séparé du log
applicatif classique (core/logging_setup.py), pour que l'utilisateur
puisse les consulter lui-même (page Paramètres, bouton "Voir les logs" —
voir ui/pages/page_settings.py).

Format JSON Lines (une action = une ligne JSON) : ajouter une entrée ne
demande jamais de relire/réécrire tout le fichier, et une ligne corrompue
(écriture interrompue par une coupure de courant, édition manuelle...) ne
peut jamais casser la lecture des autres.

Stocké sous %APPDATA%\\ZenkaiCore\\logs (voir core/paths.py), donc TOUJOURS
en dehors du dépôt Git quel que soit l'endroit d'où l'app est lancée — rien
à exclure via .gitignore pour ce chemin précis, mais un nom de fichier y
est quand même déclaré par prudence (voir .gitignore) au cas où cette
fonction serait un jour appelée avec un chemin relatif au projet.
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


class Category:
    """Liste EXPLICITE des catégories d'actions journalisées — un appelant
    de log_event() doit toujours en choisir une, jamais une chaîne libre :
    ça garantit qu'aucun site d'appel n'oublie de classer correctement ce
    qu'il vient de faire (voir SENSITIVE_CATEGORIES ci-dessous, qui
    détermine ce qui déclenche un avertissement avant exécution — voir
    core/security_warning.py)."""

    REGISTRY_WRITE = "registry_write"  # ex. Mode Jeu, Xbox Game Bar/DVR (features/performance/fixes.py)
    FILE_MODIFY = "file_modify"  # ClientAppSettings.json : sauvegarde/restauration/injection
    SERVICE_CONTROL = "service_control"  # démarrage/arrêt/désactivation d'un service Windows (SysMain)
    PROTOCOL_HANDLER = "protocol_handler"  # (dés)enregistrement de roblox-player:// dans le registre
    EXTERNAL_EXECUTION = "external_execution"  # lancement d'un exécutable externe (Roblox, PresentMon, powercfg...)
    ELEVATION = "elevation"  # demande de droits administrateur (prompt UAC)
    SCRIPT_EXECUTION = "script_execution"  # lancement/arrêt d'un Custom Script (AutoHotkey)
    SCRIPT_SCAN = "script_scan"  # analyse heuristique + scan Windows Defender d'un Custom Script


# Catégories considérées "sensibles" : détermine la mise en évidence d'une
# ligne dans "Voir les logs" (voir ui/pages/page_settings.py). Toutes les
# catégories ci-dessus le sont actuellement (elles modifient toutes un
# état système ou lancent un binaire externe) — ce set reste néanmoins
# explicite et distinct de Category pour permettre d'ajouter, plus tard,
# une catégorie purement informative (diagnostic en lecture seule) sans la
# marquer sensible par erreur.
SENSITIVE_CATEGORIES = {
    Category.REGISTRY_WRITE,
    Category.FILE_MODIFY,
    Category.SERVICE_CONTROL,
    Category.PROTOCOL_HANDLER,
    Category.EXTERNAL_EXECUTION,
    Category.ELEVATION,
    Category.SCRIPT_EXECUTION,
    Category.SCRIPT_SCAN,
}


@dataclass
class SecurityEvent:
    timestamp: str  # ISO 8601, heure locale (voir log_event)
    action: str  # code court, ex. "protocol_register" — traduit à l'affichage
    category: str  # une des constantes Category ci-dessus
    target: str  # ce qui a été modifié/exécuté (chemin de fichier, clé de registre...)
    result: str  # "ok" ou "error"
    sensitive: bool  # = category in SENSITIVE_CATEGORIES au moment de l'écriture


def log_event(action: str, category: str, target: str, result: str) -> None:
    """Ajoute une ligne au journal de sécurité. Ne lève jamais : une erreur
    d'écriture ici (disque plein, permissions...) est seulement journalisée
    dans le log applicatif normal — enregistrer une action ne doit jamais
    faire échouer l'action elle-même (même principe que
    features/fastflags/launcher.py pour l'injection des Fast Flags).

    `sensitive` n'est PAS un paramètre : il se déduit toujours de
    `category` (voir SENSITIVE_CATEGORIES), pour qu'il soit impossible
    d'appeler log_event() avec une catégorie sensible tout en oubliant de
    la marquer comme telle."""
    event = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "action": action,
        "category": category,
        "target": target,
        "result": result,
        "sensitive": category in SENSITIVE_CATEGORIES,
    }
    try:
        with open(get_security_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.error("Impossible d'écrire dans le journal de sécurité (%s)", exc)


def read_events(limit: int = _DEFAULT_READ_LIMIT) -> list[SecurityEvent]:
    """Relit le journal et renvoie jusqu'à `limit` événements, les plus
    récents en premier (voir _SecurityLogDialog). Liste vide si le fichier
    n'existe pas encore (aucune action journalisée pour l'instant) — ce
    n'est jamais une erreur en soi."""
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
                category=data.get("category", ""),
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
