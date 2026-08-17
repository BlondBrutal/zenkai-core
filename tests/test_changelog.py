"""
Tests de la lecture du changelog (core/changelog.py) — chemin de fichier
redirigé vers un fichier temporaire, jamais le vrai CHANGELOG.json du dépôt.
"""
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import core.changelog as changelog_mod


class TestChangelog(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.mkdtemp(prefix="zenkai_changelog_test_")
        self._path = os.path.join(self._temp_dir, "CHANGELOG.json")
        self._patcher = patch.object(changelog_mod, "_CHANGELOG_PATH", self._path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def _write(self, data) -> None:
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_load_changelog_round_trip(self):
        self._write([
            {"version": "1.1", "date": "2026-09-01", "added": ["A"], "fixed": ["B"]},
            {"version": "1.0", "date": "2026-08-16", "added": ["C"], "fixed": []},
        ])
        entries = changelog_mod.load_changelog()
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].version, "1.1")
        self.assertEqual(entries[0].added, ["A"])
        self.assertEqual(entries[0].fixed, ["B"])
        self.assertEqual(entries[1].fixed, [])

    def test_current_version_is_first_entry(self):
        self._write([
            {"version": "2.0", "date": "2026-10-01", "added": [], "fixed": []},
            {"version": "1.0", "date": "2026-08-16", "added": [], "fixed": []},
        ])
        self.assertEqual(changelog_mod.current_version(), "2.0")

    def test_current_version_unknown_when_missing(self):
        # Fichier jamais écrit dans ce test.
        self.assertEqual(changelog_mod.current_version(), "?")

    def test_load_changelog_returns_empty_list_when_missing(self):
        self.assertEqual(changelog_mod.load_changelog(), [])

    def test_load_changelog_ignores_corrupted_file(self):
        with open(self._path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        self.assertEqual(changelog_mod.load_changelog(), [])

    def test_load_changelog_rejects_non_list_json(self):
        self._write({"version": "1.0"})
        self.assertEqual(changelog_mod.load_changelog(), [])

    def test_missing_fields_default_gracefully(self):
        self._write([{"version": "1.0"}])
        entries = changelog_mod.load_changelog()
        self.assertEqual(entries[0].date, "")
        self.assertEqual(entries[0].added, [])
        self.assertEqual(entries[0].fixed, [])


if __name__ == "__main__":
    unittest.main()
