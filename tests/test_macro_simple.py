"""
Tests (pytest) de la sérialisation des macros Simple (.zkmacro), features/
macro_simple/macro_simple.py — dossier de macros redirigé vers tmp_path,
jamais le vrai %APPDATA%.
"""
import json
import os

import pytest

import features.macro_simple.macro_simple as macro_simple_mod
from features.macro_simple.macro_simple import (
    ACTION_KEY, ACTION_MOUSE, MACRO_TYPE, TRIGGER_HOLD, TRIGGER_REPEAT, TRIGGER_TOGGLE,
    MacroSimpleConfig, MacroStep, import_macro, list_macro_simple_macros, save_macro_simple,
)


@pytest.fixture(autouse=True)
def macros_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(macro_simple_mod, "get_macros_dir", lambda: str(tmp_path))
    return tmp_path


def _make_config(name="Test Macro") -> MacroSimpleConfig:
    return MacroSimpleConfig(
        name=name,
        hotkey="f6",
        trigger_mode=TRIGGER_TOGGLE,
        steps=[
            MacroStep(action=ACTION_KEY, value="a", hold_ms=40, delay_after_ms=60),
            MacroStep(action=ACTION_MOUSE, value="left", x=100, y=200, use_current_position=True),
        ],
    )


class TestMacroStepRoundTrip:
    def test_to_dict_from_dict_round_trip(self):
        step = MacroStep(action=ACTION_MOUSE, value="right", x=10, y=20, hold_ms=5, delay_after_ms=15, use_current_position=True)
        restored = MacroStep.from_dict(step.to_dict())
        assert restored == step

    def test_from_dict_defaults_missing_fields(self):
        step = MacroStep.from_dict({})
        assert step.action == ACTION_KEY
        assert step.value == ""
        assert step.x == 0 and step.y == 0
        assert step.hold_ms == 50
        assert step.delay_after_ms == 50
        assert step.use_current_position is False

    def test_from_dict_clamps_negative_durations_to_zero(self):
        step = MacroStep.from_dict({"hold_ms": -5, "delay_after_ms": -1})
        assert step.hold_ms == 0
        assert step.delay_after_ms == 0


class TestMacroSimpleConfigRoundTrip:
    def test_to_dict_from_dict_round_trip(self):
        config = _make_config()
        restored = MacroSimpleConfig.from_dict(config.to_dict())
        assert restored.name == config.name
        assert restored.hotkey == config.hotkey
        assert restored.trigger_mode == config.trigger_mode
        assert restored.steps == config.steps
        assert restored.type == MACRO_TYPE

    def test_from_dict_forces_type_to_simple_even_if_tampered(self):
        data = _make_config().to_dict()
        data["type"] = "pixel"
        restored = MacroSimpleConfig.from_dict(data)
        assert restored.type == MACRO_TYPE

    def test_from_dict_repeat_count_minimum_is_one(self):
        restored = MacroSimpleConfig.from_dict({"name": "x", "repeat_count": 0})
        assert restored.repeat_count == 1
        restored = MacroSimpleConfig.from_dict({"name": "x", "repeat_count": -5})
        assert restored.repeat_count == 1


class TestSaveAndList:
    def test_save_creates_file_and_list_finds_it(self, macros_dir):
        config = _make_config()
        path = save_macro_simple(config)
        assert os.path.isfile(path)
        assert path.endswith(".zkmacro")

        results = list_macro_simple_macros()
        assert len(results) == 1
        listed_path, listed_config = results[0]
        assert listed_path == path
        assert listed_config.name == "Test Macro"
        assert len(listed_config.steps) == 2

    def test_save_reuses_existing_path(self, macros_dir):
        config = _make_config()
        path1 = save_macro_simple(config)
        config.name = "Renamed"
        path2 = save_macro_simple(config, existing_path=path1)
        assert path1 == path2
        assert len(list_macro_simple_macros()) == 1

    def test_list_ignores_other_macro_types(self, macros_dir):
        pixel_path = os.path.join(macros_dir, "other.zkmacro")
        with open(pixel_path, "w", encoding="utf-8") as f:
            json.dump({"name": "Other", "type": "pixel"}, f)
        save_macro_simple(_make_config())
        results = list_macro_simple_macros()
        assert len(results) == 1
        assert results[0][1].name == "Test Macro"

    def test_list_ignores_corrupted_file(self, macros_dir):
        corrupt_path = os.path.join(macros_dir, "corrupt.zkmacro")
        with open(corrupt_path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        save_macro_simple(_make_config())
        results = list_macro_simple_macros()
        assert len(results) == 1

    def test_list_ignores_non_zkmacro_files(self, macros_dir):
        with open(os.path.join(macros_dir, "readme.txt"), "w", encoding="utf-8") as f:
            f.write("not a macro")
        assert list_macro_simple_macros() == []


class TestImportMacro:
    def test_import_copies_into_macros_dir(self, macros_dir, tmp_path):
        external_dir = tmp_path / "external"
        external_dir.mkdir()
        source = external_dir / "shared.zkmacro"
        config = _make_config("Shared Macro")
        with open(source, "w", encoding="utf-8") as f:
            json.dump(config.to_dict(), f)

        dest_path, imported = import_macro(str(source))
        assert os.path.isfile(dest_path)
        assert os.path.dirname(dest_path) == str(macros_dir)
        assert imported.name == "Shared Macro"
        assert list_macro_simple_macros()

    def test_import_rejects_wrong_type(self, tmp_path):
        source = tmp_path / "pixel.zkmacro"
        with open(source, "w", encoding="utf-8") as f:
            json.dump({"name": "x", "type": "pixel"}, f)
        with pytest.raises(ValueError):
            import_macro(str(source))
