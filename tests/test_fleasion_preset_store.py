"""
Tests de la persistance des presets Fleasion (features/fleasion/
preset_store.py) — isolés dans un dossier temporaire (jamais le vrai
%APPDATA%), même esprit que tests/test_custom_script_store.py.
"""
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from features.fleasion.preset_store import (
    MODE_ID, MODE_LOCAL, FleasionPresetEntry, FleasionRule, delete_preset, export_preset,
    import_preset, list_presets, preset_assets_dir, save_preset,
)


class TestPresetStore(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.mkdtemp(prefix="zenkai_fleasion_test_")
        self._patcher = patch(
            "features.fleasion.preset_store.get_fleasion_presets_dir", return_value=self._temp_dir,
        )
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def _make_entry(self, name="Test Preset") -> FleasionPresetEntry:
        return FleasionPresetEntry(
            id="abcdef1234", name=name,
            rules=[FleasionRule(asset_ids="111", mode=MODE_ID, target="222", enabled=True)],
        )

    def test_save_and_list_round_trip(self):
        entry = self._make_entry()
        path = save_preset(entry)
        self.assertTrue(os.path.isfile(path))

        results = list_presets()
        self.assertEqual(len(results), 1)
        listed_path, listed_entry = results[0]
        self.assertEqual(listed_path, path)
        self.assertEqual(listed_entry.name, "Test Preset")
        self.assertEqual(len(listed_entry.rules), 1)
        self.assertEqual(listed_entry.rules[0].asset_ids, "111")

    def test_save_reuses_existing_path(self):
        entry = self._make_entry()
        path1 = save_preset(entry)
        entry.name = "Renamed"
        path2 = save_preset(entry, existing_path=path1)
        self.assertEqual(path1, path2)
        self.assertEqual(len(list_presets()), 1)

    def test_assets_dir_stable_across_rename(self):
        """Renommer le preset APRÈS avoir importé un fichier local ne doit
        jamais casser le chemin vers le dossier d'assets déjà utilisé
        (nommé d'après l'id, jamais le nom slugifié)."""
        entry = self._make_entry()
        assets_dir_before = preset_assets_dir(entry)
        with open(os.path.join(assets_dir_before, "texture.png"), "wb") as f:
            f.write(b"x")
        entry.name = "Nouveau Nom"
        assets_dir_after = preset_assets_dir(entry)
        self.assertEqual(assets_dir_before, assets_dir_after)
        self.assertTrue(os.path.isfile(os.path.join(assets_dir_after, "texture.png")))

    def test_delete_preset_removes_json_and_assets_dir(self):
        entry = self._make_entry()
        path = save_preset(entry)
        assets_dir = preset_assets_dir(entry)
        with open(os.path.join(assets_dir, "a.png"), "wb") as f:
            f.write(b"x")

        delete_preset(path, entry)
        self.assertFalse(os.path.isfile(path))
        self.assertFalse(os.path.isdir(assets_dir))
        self.assertEqual(list_presets(), [])

    def test_delete_preset_missing_files_does_not_raise(self):
        entry = self._make_entry()
        delete_preset(os.path.join(self._temp_dir, "does-not-exist.zkfleasion"), entry)

    def test_list_presets_ignores_corrupted_file(self):
        corrupt_path = os.path.join(self._temp_dir, "corrupt.zkfleasion")
        with open(corrupt_path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        entry = self._make_entry()
        save_preset(entry)

        results = list_presets()
        self.assertEqual(len(results), 1)

    def test_export_import_round_trip_with_local_asset(self):
        entry = FleasionPresetEntry(
            id="localpreset", name="Local Preset",
            rules=[FleasionRule(asset_ids="1", mode=MODE_LOCAL, target="/tex.png", enabled=True)],
        )
        assets_dir = preset_assets_dir(entry)
        with open(os.path.join(assets_dir, "tex.png"), "wb") as f:
            f.write(b"fake texture bytes")
        save_preset(entry)

        export_dir = tempfile.mkdtemp(prefix="zenkai_fleasion_export_test_")
        try:
            zip_path = os.path.join(export_dir, "preset.zip")
            export_preset(entry, zip_path)
            self.assertTrue(os.path.isfile(zip_path))

            imported = import_preset(zip_path)
            self.assertEqual(imported.name, "Local Preset")
            self.assertNotEqual(imported.id, entry.id)  # jamais d'écrasement, toujours un nouvel id
            self.assertEqual(imported.rules[0].target, "/tex.png")

            imported_assets = preset_assets_dir(imported)
            self.assertTrue(os.path.isfile(os.path.join(imported_assets, "tex.png")))
            with open(os.path.join(imported_assets, "tex.png"), "rb") as f:
                self.assertEqual(f.read(), b"fake texture bytes")
        finally:
            shutil.rmtree(export_dir, ignore_errors=True)

    def test_export_without_local_assets_still_produces_valid_zip(self):
        entry = self._make_entry()  # mode ID, pas d'asset local
        save_preset(entry)
        export_dir = tempfile.mkdtemp(prefix="zenkai_fleasion_export_test2_")
        try:
            zip_path = os.path.join(export_dir, "preset.zip")
            export_preset(entry, zip_path)
            imported = import_preset(zip_path)
            self.assertEqual(imported.rules[0].asset_ids, "111")
        finally:
            shutil.rmtree(export_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
