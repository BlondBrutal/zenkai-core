"""
Tests (pytest) de la construction des cartes de statut Performance (features/
performance/status_cards.py) — dataclasses pures, aucun mock nécessaire.
"""
from features.performance.status_cards import HIGH_PERFORMANCE_GUID, build_status_cards
from features.performance.system_info import SystemSpecs


def _ids(cards):
    return [c.card_id for c in cards]


def test_all_healthy_specs_produce_no_cards():
    specs = SystemSpecs(
        power_plan_guid=HIGH_PERFORMANCE_GUID, power_plan_name="Haute performance",
        game_mode_enabled=True, game_dvr_enabled=False, sysmain_running=False,
        disk_free_gb=200.0, disk_free_percent=50.0, ram_total_gb=16.0,
        roblox_version_folder="version-abc123",
    )
    assert build_status_cards(specs) == []


def test_unknown_power_plan_is_warning():
    specs = SystemSpecs(power_plan_guid=None)
    cards = build_status_cards(specs)
    card = next(c for c in cards if c.card_id == "power_plan")
    assert card.level == "warning"
    assert card.desc_key == "performance.card.power_plan.desc_unknown"
    assert card.can_auto_fix is False


def test_non_high_performance_plan_is_fixable_warning():
    specs = SystemSpecs(power_plan_guid="some-other-guid", power_plan_name="Équilibré")
    card = next(c for c in build_status_cards(specs) if c.card_id == "power_plan")
    assert card.level == "warning"
    assert card.can_auto_fix is True
    assert card.fix_steps_key == "performance.card.power_plan.fix_steps"


def test_game_mode_disabled_is_fixable_warning():
    specs = SystemSpecs(game_mode_enabled=False)
    card = next(c for c in build_status_cards(specs) if c.card_id == "game_mode")
    assert card.level == "warning"
    assert card.can_auto_fix is True


def test_game_mode_none_is_not_reported_as_warning():
    # None = "on n'a pas pu vérifier", pas "désactivé" — ne doit pas
    # afficher un faux avertissement.
    specs = SystemSpecs(game_mode_enabled=None)
    assert "game_mode" not in _ids(build_status_cards(specs))


def test_game_dvr_enabled_is_warning():
    specs = SystemSpecs(game_dvr_enabled=True)
    card = next(c for c in build_status_cards(specs) if c.card_id == "game_dvr")
    assert card.level == "warning"


def test_sysmain_running_is_warning_not_running_is_ok_filtered_out():
    specs_running = SystemSpecs(sysmain_running=True)
    card = next(c for c in build_status_cards(specs_running) if c.card_id == "sysmain")
    assert card.level == "warning"

    specs_stopped = SystemSpecs(sysmain_running=False)
    assert "sysmain" not in _ids(build_status_cards(specs_stopped))

    specs_unknown = SystemSpecs(sysmain_running=None)
    assert "sysmain" not in _ids(build_status_cards(specs_unknown))


def test_disk_space_critical_below_5_percent_or_10gb():
    specs = SystemSpecs(disk_free_gb=8.0, disk_free_percent=20.0)
    card = next(c for c in build_status_cards(specs) if c.card_id == "disk_space")
    assert card.level == "critical"


def test_disk_space_warning_between_thresholds():
    specs = SystemSpecs(disk_free_gb=20.0, disk_free_percent=10.0)
    card = next(c for c in build_status_cards(specs) if c.card_id == "disk_space")
    assert card.level == "warning"


def test_disk_space_ok_is_filtered_out():
    specs = SystemSpecs(disk_free_gb=200.0, disk_free_percent=60.0)
    assert "disk_space" not in _ids(build_status_cards(specs))


def test_disk_space_card_absent_when_data_unavailable():
    specs = SystemSpecs(disk_free_gb=None, disk_free_percent=None)
    assert "disk_space" not in _ids(build_status_cards(specs))


def test_ram_total_low_is_warning():
    specs = SystemSpecs(ram_total_gb=4.0)
    card = next(c for c in build_status_cards(specs) if c.card_id == "ram_total")
    assert card.level == "warning"


def test_ram_total_sufficient_is_filtered_out():
    specs = SystemSpecs(ram_total_gb=16.0)
    assert "ram_total" not in _ids(build_status_cards(specs))


def test_roblox_missing_is_critical():
    specs = SystemSpecs(roblox_version_folder=None)
    card = next(c for c in build_status_cards(specs) if c.card_id == "roblox_detected")
    assert card.level == "critical"


def test_roblox_detected_is_filtered_out():
    specs = SystemSpecs(roblox_version_folder="version-xyz")
    assert "roblox_detected" not in _ids(build_status_cards(specs))


def test_cards_sorted_critical_before_warning():
    specs = SystemSpecs(
        power_plan_guid=None,  # warning
        roblox_version_folder=None,  # critical
    )
    cards = build_status_cards(specs)
    levels = [c.level for c in cards]
    assert levels.index("critical") < levels.index("warning")
