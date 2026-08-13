"""
Tests de la persistance des scripts personnalisés (features/custom_script/
script_store.py) — isolés dans un dossier temporaire (jamais le vrai
%APPDATA%), même esprit que l'isolation utilisée par tests/test_license_manager.py.
"""
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from features.custom_script.script_store import (
    CustomScriptEntry, ScriptAnalysis, ahk_companion_path, delete_script,
    is_analysis_current, list_scripts, save_script,
)


class TestScriptStore(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.mkdtemp(prefix="zenkai_custom_script_test_")
        self._patcher = patch(
            "features.custom_script.script_store.get_custom_scripts_dir", return_value=self._temp_dir,
        )
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def _make_entry(self, name="Test Script", text="MsgBox, Hello") -> CustomScriptEntry:
        return CustomScriptEntry(id="abcdef12", name=name, script_text=text, created_at="", updated_at="")

    def test_save_and_list_round_trip(self):
        entry = self._make_entry()
        path = save_script(entry)
        self.assertTrue(os.path.isfile(path))

        results = list_scripts()
        self.assertEqual(len(results), 1)
        listed_path, listed_entry = results[0]
        self.assertEqual(listed_path, path)
        self.assertEqual(listed_entry.name, "Test Script")
        self.assertEqual(listed_entry.script_text, "MsgBox, Hello")

    def test_save_reuses_existing_path(self):
        entry = self._make_entry()
        path1 = save_script(entry)
        entry.name = "Renamed"
        path2 = save_script(entry, existing_path=path1)
        self.assertEqual(path1, path2)
        self.assertEqual(len(list_scripts()), 1)

    def test_is_analysis_current_true_right_after_analysis(self):
        entry = self._make_entry()
        entry.analysis = ScriptAnalysis(analyzed_hash=entry.content_hash())
        self.assertTrue(is_analysis_current(entry))

    def test_is_analysis_current_false_after_edit_without_reanalysis(self):
        entry = self._make_entry()
        entry.analysis = ScriptAnalysis(analyzed_hash=entry.content_hash())
        entry.script_text = "MsgBox, Hello, modified"
        self.assertFalse(is_analysis_current(entry))

    def test_is_analysis_current_false_when_no_analysis_yet(self):
        entry = self._make_entry()
        self.assertFalse(is_analysis_current(entry))

    def test_delete_script_removes_zkscript_and_ahk_companion(self):
        entry = self._make_entry()
        path = save_script(entry)
        companion = ahk_companion_path(path)
        with open(companion, "w", encoding="utf-8") as f:
            f.write(entry.script_text)

        delete_script(path)
        self.assertFalse(os.path.isfile(path))
        self.assertFalse(os.path.isfile(companion))
        self.assertEqual(list_scripts(), [])

    def test_delete_script_missing_files_does_not_raise(self):
        delete_script(os.path.join(self._temp_dir, "does-not-exist.zkscript"))

    def test_list_scripts_ignores_corrupted_file(self):
        corrupt_path = os.path.join(self._temp_dir, "corrupt.zkscript")
        with open(corrupt_path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        entry = self._make_entry()
        save_script(entry)

        results = list_scripts()
        self.assertEqual(len(results), 1)


if __name__ == "__main__":
    unittest.main()
