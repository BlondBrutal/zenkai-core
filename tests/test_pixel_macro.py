"""
Tests (pytest) de la sérialisation des macros Pixel (.zkmacro), features/
macro_pixel/pixel_macro.py — dossier de macros redirigé vers tmp_path,
jamais le vrai %APPDATA%.
"""
import json
import os

import pytest

import features.macro_pixel.pixel_macro as pixel_macro_mod
from features.macro_pixel.pixel_macro import (
    MACRO_TYPE, PixelMacroConfig, delete_macro, export_macro, import_macro,
    list_pixel_macros, save_pixel_macro,
)


@pytest.fixture(autouse=True)
def macros_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(pixel_macro_mod, "get_macros_dir", lambda: str(tmp_path))
    return tmp_path


def _make_config(name="Test Pixel") -> PixelMacroConfig:
    return PixelMacroConfig(
        name=name, x=640, y=360, target_color=(255, 0, 128),
        key="mouse_left", swap_key="f8", swap_target_key="mouse_right", cooldown_seconds=1.5,
    )


class TestPixelMacroConfigRoundTrip:
    def test_to_dict_from_dict_round_trip(self):
        config = _make_config()
        restored = PixelMacroConfig.from_dict(config.to_dict())
        assert restored == config

    def test_to_dict_stores_color_as_list(self):
        data = _make_config().to_dict()
        assert data["target_color"] == [255, 0, 128]
        assert isinstance(data["target_color"], list)

    def test_from_dict_truncates_extra_color_components(self):
        restored = PixelMacroConfig.from_dict({"name": "x", "x": 1, "y": 2, "target_color": [1, 2, 3, 4]})
        assert restored.target_color == (1, 2, 3)

    def test_from_dict_defaults_missing_color_to_black(self):
        restored = PixelMacroConfig.from_dict({"name": "x", "x": 1, "y": 2})
        assert restored.target_color == (0, 0, 0)

    def test_from_dict_forces_type_to_pixel_even_if_tampered(self):
        data = _make_config().to_dict()
        data["type"] = "simple"
        restored = PixelMacroConfig.from_dict(data)
        assert restored.type == MACRO_TYPE

    def test_from_dict_requires_x_and_y(self):
        with pytest.raises(KeyError):
            PixelMacroConfig.from_dict({"name": "x"})


class TestSaveAndList:
    def test_save_creates_file_and_list_finds_it(self, macros_dir):
        path = save_pixel_macro(_make_config())
        assert os.path.isfile(path)
        results = list_pixel_macros()
        assert len(results) == 1
        assert results[0][1].name == "Test Pixel"

    def test_save_reuses_existing_path(self, macros_dir):
        config = _make_config()
        path1 = save_pixel_macro(config)
        config.name = "Renamed"
        path2 = save_pixel_macro(config, existing_path=path1)
        assert path1 == path2
        assert len(list_pixel_macros()) == 1

    def test_list_ignores_other_macro_types(self, macros_dir):
        simple_path = os.path.join(macros_dir, "other.zkmacro")
        with open(simple_path, "w", encoding="utf-8") as f:
            json.dump({"name": "Other", "type": "simple"}, f)
        save_pixel_macro(_make_config())
        results = list_pixel_macros()
        assert len(results) == 1
        assert results[0][1].name == "Test Pixel"

    def test_list_ignores_corrupted_file(self, macros_dir):
        corrupt_path = os.path.join(macros_dir, "corrupt.zkmacro")
        with open(corrupt_path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        save_pixel_macro(_make_config())
        assert len(list_pixel_macros()) == 1


class TestDeleteMacro:
    def test_delete_removes_file(self, macros_dir):
        path = save_pixel_macro(_make_config())
        delete_macro(path)
        assert not os.path.isfile(path)

    def test_delete_missing_file_does_not_raise(self, macros_dir):
        delete_macro(os.path.join(macros_dir, "does-not-exist.zkmacro"))


class TestImportExport:
    def test_import_copies_into_macros_dir(self, macros_dir, tmp_path):
        external_dir = tmp_path / "external"
        external_dir.mkdir()
        source = external_dir / "shared.zkmacro"
        with open(source, "w", encoding="utf-8") as f:
            json.dump(_make_config("Shared").to_dict(), f)

        dest_path, imported = import_macro(str(source))
        assert os.path.dirname(dest_path) == str(macros_dir)
        assert imported.name == "Shared"

    def test_import_rejects_wrong_type(self, tmp_path):
        source = tmp_path / "simple.zkmacro"
        with open(source, "w", encoding="utf-8") as f:
            json.dump({"name": "x", "type": "simple"}, f)
        with pytest.raises(ValueError):
            import_macro(str(source))

    def test_export_copies_raw_content(self, macros_dir, tmp_path):
        source_path = save_pixel_macro(_make_config())
        dest_path = tmp_path / "exported.zkmacro"
        export_macro(source_path, str(dest_path))
        with open(source_path, encoding="utf-8") as f:
            original = f.read()
        with open(dest_path, encoding="utf-8") as f:
            exported = f.read()
        assert original == exported
