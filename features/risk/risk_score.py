"""
Estimation heuristique du risque de bannissement (Partie 6 du brief) — un
score interne, PAS une mesure garantie ni un chiffre officiel Roblox. À
présenter dans l'UI comme une estimation, jamais comme un fait établi.

Basé uniquement sur ce qui est réellement vérifiable dans l'app aujourd'hui :
- le preset Fast Flags actif (s'il y en a un) — rester sur un preset fourni
  (graphique/perf uniquement) limite déjà le risque ; un preset "custom"
  (flags importés/édités à la main, non vérifiés par la communauté) compte
  un peu plus.
- les macros n'ont PAS encore de moteur d'exécution réel (Simple/Pixel/Combo
  restent des squelettes, Partie 5 — Z/M1 Boost — pas encore portée) : leur
  contribution reste à 0 tant que ça n'existe pas. À compléter ici une fois
  ce moteur implémenté (le kill switch de page_macro.py devra alimenter ce
  calcul : quelles macros sont actives, laquelle est un freeze/glitch plus
  sensible qu'un simple replay d'inputs).
"""
from dataclasses import dataclass, field

from core.config import config

LOW_RISK_MAX = 30
MODERATE_RISK_MAX = 70


@dataclass
class RiskEstimate:
    score: int  # 0-100, estimation heuristique
    level: str  # "low" | "moderate" | "high"
    contributor_keys: list = field(default_factory=list)
    recommendation_keys: list = field(default_factory=list)


def compute_risk_estimate() -> RiskEstimate:
    score = 0
    contributor_keys: list = []
    recommendation_keys: list = []

    preset = config.get("active_fastflags_preset")
    if preset == "custom":
        score += 15
        contributor_keys.append("risk.contributor.fastflags_custom")
        recommendation_keys.append("risk.recommendation.fastflags_custom")
    elif preset in ("hard", "balanced", "quality"):
        score += 5
        contributor_keys.append("risk.contributor.fastflags_preset")

    score = max(0, min(100, score))
    if score <= LOW_RISK_MAX:
        level = "low"
    elif score <= MODERATE_RISK_MAX:
        level = "moderate"
    else:
        level = "high"

    return RiskEstimate(score=score, level=level, contributor_keys=contributor_keys, recommendation_keys=recommendation_keys)
