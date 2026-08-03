"""
Construit la liste des cartes de statut (Partie 2.1 du brief) à partir des
specs système : une carte par aspect vérifié, avec un niveau parmi
"ok" / "warning" / "critical" (jamais d'emoji, la couleur suffit — voir
page_performance.py). Logique pure, testable sans Qt.
"""
from dataclasses import dataclass, field
from typing import Optional

from features.performance.system_info import SystemSpecs

# GUID stable du plan "Haute performance" intégré à Windows, quelle que soit
# la langue du système (contrairement au nom affiché par powercfg).
HIGH_PERFORMANCE_GUID = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"

_LEVEL_ORDER = {"critical": 0, "warning": 1, "ok": 2}


@dataclass
class StatusCard:
    card_id: str
    level: str  # "ok" | "warning" | "critical"
    title_key: str
    desc_key: str
    desc_kwargs: dict = field(default_factory=dict)
    fix_steps_key: Optional[str] = None
    can_auto_fix: bool = False


def build_status_cards(specs: SystemSpecs) -> list[StatusCard]:
    cards: list[StatusCard] = []

    # --- Plan d'alimentation ---
    if specs.power_plan_guid is None:
        cards.append(StatusCard(
            "power_plan", "warning",
            "performance.card.power_plan.title", "performance.card.power_plan.desc_unknown",
        ))
    elif specs.power_plan_guid == HIGH_PERFORMANCE_GUID:
        cards.append(StatusCard(
            "power_plan", "ok",
            "performance.card.power_plan.title", "performance.card.power_plan.desc_ok",
            {"name": specs.power_plan_name or ""},
        ))
    else:
        cards.append(StatusCard(
            "power_plan", "warning",
            "performance.card.power_plan.title", "performance.card.power_plan.desc_warning",
            {"name": specs.power_plan_name or "?"},
            fix_steps_key="performance.card.power_plan.fix_steps",
            can_auto_fix=True,
        ))

    # --- Mode Jeu ---
    if specs.game_mode_enabled is False:
        cards.append(StatusCard(
            "game_mode", "warning",
            "performance.card.game_mode.title", "performance.card.game_mode.desc_warning",
            fix_steps_key="performance.card.game_mode.fix_steps",
            can_auto_fix=True,
        ))
    else:
        cards.append(StatusCard(
            "game_mode", "ok",
            "performance.card.game_mode.title", "performance.card.game_mode.desc_ok",
        ))

    # --- Xbox Game Bar / enregistrement en arrière-plan ---
    if specs.game_dvr_enabled is True:
        cards.append(StatusCard(
            "game_dvr", "warning",
            "performance.card.game_dvr.title", "performance.card.game_dvr.desc_warning",
            fix_steps_key="performance.card.game_dvr.fix_steps",
            can_auto_fix=True,
        ))
    else:
        cards.append(StatusCard(
            "game_dvr", "ok",
            "performance.card.game_dvr.title", "performance.card.game_dvr.desc_ok",
        ))

    # --- Service SysMain (Superfetch) ---
    if specs.sysmain_running is True:
        cards.append(StatusCard(
            "sysmain", "warning",
            "performance.card.sysmain.title", "performance.card.sysmain.desc_warning",
            can_auto_fix=True,
        ))
    elif specs.sysmain_running is False:
        cards.append(StatusCard(
            "sysmain", "ok",
            "performance.card.sysmain.title", "performance.card.sysmain.desc_ok",
        ))

    # --- Espace disque ---
    if specs.disk_free_gb is not None and specs.disk_free_percent is not None:
        if specs.disk_free_percent < 5 or specs.disk_free_gb < 10:
            cards.append(StatusCard(
                "disk_space", "critical",
                "performance.card.disk_space.title", "performance.card.disk_space.desc_critical",
                {"free_gb": specs.disk_free_gb, "percent": specs.disk_free_percent},
            ))
        elif specs.disk_free_percent < 15 or specs.disk_free_gb < 25:
            cards.append(StatusCard(
                "disk_space", "warning",
                "performance.card.disk_space.title", "performance.card.disk_space.desc_warning",
                {"free_gb": specs.disk_free_gb, "percent": specs.disk_free_percent},
            ))
        else:
            cards.append(StatusCard(
                "disk_space", "ok",
                "performance.card.disk_space.title", "performance.card.disk_space.desc_ok",
                {"free_gb": specs.disk_free_gb, "percent": specs.disk_free_percent},
            ))

    # --- RAM totale ---
    if specs.ram_total_gb is not None:
        if specs.ram_total_gb < 8:
            cards.append(StatusCard(
                "ram_total", "warning",
                "performance.card.ram_total.title", "performance.card.ram_total.desc_warning",
                {"total": specs.ram_total_gb},
            ))
        else:
            cards.append(StatusCard(
                "ram_total", "ok",
                "performance.card.ram_total.title", "performance.card.ram_total.desc_ok",
                {"total": specs.ram_total_gb},
            ))

    # --- Détection de Roblox ---
    if specs.roblox_version_folder is None:
        cards.append(StatusCard(
            "roblox_detected", "critical",
            "performance.card.roblox.title", "performance.card.roblox.desc_missing",
        ))
    else:
        cards.append(StatusCard(
            "roblox_detected", "ok",
            "performance.card.roblox.title", "performance.card.roblox.desc_ok",
            {"version": specs.roblox_version_folder},
        ))

    # Seuls les points qui demandent une action méritent une carte : ceux déjà
    # "ok" n'apporteraient rien à part occuper de la place.
    cards = [c for c in cards if c.level != "ok"]
    cards.sort(key=lambda c: _LEVEL_ORDER.get(c.level, 3))
    return cards
