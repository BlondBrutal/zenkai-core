"""
Tests (pytest) de la gestion des Fast Flags (features/fastflags/manager.py)
— fichier ClientAppSettings.json et dossiers de presets redirigés vers
tmp_path, jamais le vrai %LOCALAPPDATA%\\Roblox ni le vrai %APPDATA%.
PRESETS (Hard/Balanced/Quality) reste chargé depuis les vrais fichiers du
dépôt (assets/fastflags_presets/*.json) — jamais mocké, ce sont de vrais
presets fournis par l'utilisateur, pas des données de test.
"""
import json
import os

import pytest

import features.fastflags.manager as ffm
from features.fastflags.manager import (
    PRESETS, delete_custom_preset, detect_active_preset, detect_value_type,
    export_flags_file, get_known_flags, import_flags_file, list_custom_presets,
    load_custom_preset, read_current_flags, reset_to_default, save_custom_preset, write_flags,
)


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path, monkeypatch):
    """Redirige le VRAI fichier Roblox, le dossier des presets personnalisés
    et le fichier des flags "appris" vers tmp_path — jamais le vrai
    %LOCALAPPDATA%/%APPDATA% de l'utilisateur qui lance ces tests."""
    client_settings = tmp_path / "ClientAppSettings.json"
    presets_dir = tmp_path / "presets"
    presets_dir.mkdir()
    known_flags_path = tmp_path / "known_learned.json"

    monkeypatch.setattr(ffm, "get_client_app_settings_path", lambda: str(client_settings))
    monkeypatch.setattr(ffm, "get_fastflags_presets_dir", lambda: str(presets_dir))
    monkeypatch.setattr(ffm, "get_fastflags_known_flags_path", lambda: str(known_flags_path))
    return {"client_settings": client_settings, "presets_dir": presets_dir, "known_flags_path": known_flags_path}


class TestDetectValueType:
    @pytest.mark.parametrize("value,expected", [
        ("True", "BOOL"), ("false", "BOOL"), ("FALSE", "BOOL"),
        ("42", "INT"), ("-3", "INT"), ("  7  ", "INT"),
        ("Hello", "STRING"), ("", "STRING"), ("1.5", "STRING"),
    ])
    def test_detect_value_type(self, value, expected):
        assert detect_value_type(value) == expected


class TestBuiltinPresets:
    def test_all_three_presets_loaded_from_real_repo_files(self):
        assert set(PRESETS.keys()) == {"hard", "balanced", "quality"}
        for key, flags in PRESETS.items():
            assert isinstance(flags, dict)
            assert flags, f"preset intégré '{key}' ne devrait jamais être vide (voir assets/fastflags_presets/)"


class TestReadWriteRoundTrip:
    def test_read_current_flags_empty_when_file_missing(self, isolated_paths):
        assert read_current_flags() == {}

    def test_write_then_read_round_trip(self, isolated_paths):
        flags = {"FFlagFoo": "True", "DFIntBar": "5"}
        assert write_flags(flags) is True
        assert read_current_flags() == flags
        assert os.path.isfile(isolated_paths["client_settings"])

    def test_write_creates_parent_directory(self, tmp_path, monkeypatch):
        nested = tmp_path / "does" / "not" / "exist" / "ClientAppSettings.json"
        monkeypatch.setattr(ffm, "get_client_app_settings_path", lambda: str(nested))
        assert write_flags({"A": "1"}) is True
        assert os.path.isfile(nested)

    def test_read_current_flags_empty_on_corrupted_file(self, isolated_paths):
        with open(isolated_paths["client_settings"], "w", encoding="utf-8") as f:
            f.write("{not valid json")
        assert read_current_flags() == {}

    def test_read_current_flags_empty_when_json_is_not_an_object(self, isolated_paths):
        with open(isolated_paths["client_settings"], "w", encoding="utf-8") as f:
            json.dump([1, 2, 3], f)
        assert read_current_flags() == {}

    def test_reset_to_default_empties_the_file(self, isolated_paths):
        write_flags({"A": "1"})
        assert reset_to_default() is True
        assert read_current_flags() == {}


class TestDetectActivePreset:
    def test_none_when_file_empty(self, isolated_paths):
        assert detect_active_preset() is None

    def test_matches_exact_builtin_preset(self, isolated_paths):
        write_flags(dict(PRESETS["hard"]))
        assert detect_active_preset() == "hard"

    def test_none_for_custom_flags(self, isolated_paths):
        write_flags({"SomeRandomFlag": "True"})
        assert detect_active_preset() is None

    def test_none_when_subset_of_a_preset(self, isolated_paths):
        # Une correspondance PARTIELLE ne doit jamais compter comme "actif" —
        # seule une égalité EXACTE avec le preset entier compte.
        hard_flags = dict(PRESETS["hard"])
        if len(hard_flags) > 1:
            partial = dict(list(hard_flags.items())[:1])
            write_flags(partial)
            assert detect_active_preset() is None


class TestCustomPresets:
    def test_save_and_list_round_trip(self, isolated_paths):
        path = save_custom_preset("My Preset", {"A": "1"})
        assert path is not None
        assert os.path.isfile(path)
        results = list_custom_presets()
        assert results == [(path, "My Preset")]

    def test_save_sanitizes_unsafe_characters_from_name(self, isolated_paths):
        path = save_custom_preset("Weird/Name:*?", {"A": "1"})
        assert path is not None
        assert os.path.isfile(path)

    def test_save_collision_appends_numeric_suffix(self, isolated_paths):
        path1 = save_custom_preset("Dup", {"A": "1"})
        path2 = save_custom_preset("Dup", {"B": "2"})
        assert path1 != path2
        assert path2.endswith("Dup (2).json")
        # Le premier fichier n'est jamais écrasé.
        assert load_custom_preset(path1) == {"A": "1"}
        assert load_custom_preset(path2) == {"B": "2"}

    def test_load_custom_preset_missing_file_returns_empty_dict(self, isolated_paths):
        assert load_custom_preset(str(isolated_paths["presets_dir"] / "nope.json")) == {}

    def test_delete_custom_preset_removes_file(self, isolated_paths):
        path = save_custom_preset("ToDelete", {"A": "1"})
        delete_custom_preset(path)
        assert not os.path.isfile(path)

    def test_delete_missing_preset_does_not_raise(self, isolated_paths):
        delete_custom_preset(str(isolated_paths["presets_dir"] / "nope.json"))

    def test_list_custom_presets_sorted_case_insensitively(self, isolated_paths):
        save_custom_preset("zebra", {})
        save_custom_preset("Alpha", {})
        names = [name for _, name in list_custom_presets()]
        assert names == ["Alpha", "zebra"]

    def test_list_custom_presets_ignores_non_json_files(self, isolated_paths):
        with open(isolated_paths["presets_dir"] / "readme.txt", "w") as f:
            f.write("not a preset")
        assert list_custom_presets() == []


class TestImportExportFlagsFile:
    def test_export_then_import_round_trip(self, isolated_paths, tmp_path):
        exported_path = tmp_path / "exported.json"
        assert export_flags_file({"A": "1", "B": "True"}, str(exported_path)) is True

        imported_preset_path = import_flags_file(str(exported_path))
        assert imported_preset_path is not None
        assert load_custom_preset(imported_preset_path) == {"A": "1", "B": "True"}

    def test_import_rejects_non_dict_json(self, tmp_path, isolated_paths):
        bad_file = tmp_path / "bad.json"
        with open(bad_file, "w", encoding="utf-8") as f:
            json.dump([1, 2, 3], f)
        assert import_flags_file(str(bad_file)) is None

    def test_import_rejects_invalid_json(self, tmp_path, isolated_paths):
        bad_file = tmp_path / "bad.json"
        with open(bad_file, "w", encoding="utf-8") as f:
            f.write("{not valid")
        assert import_flags_file(str(bad_file)) is None

    def test_import_learns_new_flag_names(self, tmp_path, isolated_paths):
        source = tmp_path / "custom.json"
        with open(source, "w", encoding="utf-8") as f:
            json.dump({"BrandNewFlagNeverSeenBefore": "True"}, f)
        import_flags_file(str(source))
        known = get_known_flags()
        assert known.get("BrandNewFlagNeverSeenBefore") == "BOOL"

    def test_import_does_not_relearn_seed_flags(self, tmp_path, isolated_paths):
        # Un flag déjà présent dans le seed intégré ne doit jamais être
        # réécrit dans le fichier "appris" (get_known_flags fusionne les deux
        # de toute façon, mais _learn_flags_from ne doit pas dupliquer).
        seed = ffm._read_json_dict(ffm._KNOWN_FLAGS_SEED_PATH)
        if seed:
            seeded_name = next(iter(seed))
            source = tmp_path / "custom.json"
            with open(source, "w", encoding="utf-8") as f:
                json.dump({seeded_name: "someothervalue"}, f)
            import_flags_file(str(source))
            learned = ffm._read_json_dict(isolated_paths["known_flags_path"])
            assert seeded_name not in learned
