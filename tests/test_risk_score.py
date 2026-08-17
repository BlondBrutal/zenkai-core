"""
Tests (pytest) de l'estimation heuristique de risque (features/risk/
risk_score.py) — core.config.config mocké, jamais le vrai settings.json.
"""
from unittest.mock import patch

from features.risk.risk_score import LOW_RISK_MAX, MODERATE_RISK_MAX, compute_risk_estimate


def test_no_preset_configured_gives_zero_score():
    with patch("features.risk.risk_score.config.get", return_value=None):
        estimate = compute_risk_estimate()
    assert estimate.score == 0
    assert estimate.level == "low"
    assert estimate.contributor_keys == []


def test_custom_preset_increases_score_and_flags_contributor():
    with patch("features.risk.risk_score.config.get", return_value="custom"):
        estimate = compute_risk_estimate()
    assert estimate.score == 15
    assert "risk.contributor.fastflags_custom" in estimate.contributor_keys
    assert "risk.recommendation.fastflags_custom" in estimate.recommendation_keys


def test_builtin_preset_gives_small_score_no_recommendation():
    for preset in ("hard", "balanced", "quality"):
        with patch("features.risk.risk_score.config.get", return_value=preset):
            estimate = compute_risk_estimate()
        assert estimate.score == 5
        assert "risk.contributor.fastflags_preset" in estimate.contributor_keys
        assert estimate.recommendation_keys == []


def test_unknown_preset_value_gives_zero_score():
    with patch("features.risk.risk_score.config.get", return_value="something_unrecognized"):
        estimate = compute_risk_estimate()
    assert estimate.score == 0


def test_score_never_exceeds_bounds():
    with patch("features.risk.risk_score.config.get", return_value="custom"):
        estimate = compute_risk_estimate()
    assert 0 <= estimate.score <= 100


def test_level_thresholds():
    assert LOW_RISK_MAX < MODERATE_RISK_MAX
    # Avec la logique actuelle (max 15 points), le niveau ne peut jamais
    # dépasser "low" — vérifie que le score obtenu reste bien sous le seuil.
    with patch("features.risk.risk_score.config.get", return_value="custom"):
        estimate = compute_risk_estimate()
    assert estimate.score <= LOW_RISK_MAX
    assert estimate.level == "low"
