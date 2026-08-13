"""
Tests des nouvelles catégories Custom Script dans le journal de sécurité
(core/security_log.py) — chemin de log redirigé vers un fichier temporaire,
jamais le vrai journal de l'utilisateur.
"""
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from core.security_log import Category, SENSITIVE_CATEGORIES, log_event, read_events


class TestCustomScriptCategories(unittest.TestCase):
    def test_script_categories_are_sensitive(self):
        self.assertIn(Category.SCRIPT_EXECUTION, SENSITIVE_CATEGORIES)
        self.assertIn(Category.SCRIPT_SCAN, SENSITIVE_CATEGORIES)


class TestLogEventRoundTrip(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.mkdtemp(prefix="zenkai_security_log_test_")
        self._log_path = os.path.join(self._temp_dir, "security_events.jsonl")
        self._patcher = patch("core.security_log.get_security_log_path", return_value=self._log_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def test_custom_script_launch_round_trips_as_sensitive(self):
        log_event("custom_script_launch", Category.SCRIPT_EXECUTION, "MyScript", "ok")
        events = read_events()
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.action, "custom_script_launch")
        self.assertEqual(event.category, Category.SCRIPT_EXECUTION)
        self.assertEqual(event.target, "MyScript")
        self.assertEqual(event.result, "ok")
        self.assertTrue(event.sensitive)

    def test_custom_script_scan_round_trips_as_sensitive(self):
        log_event("custom_script_defender_scan", Category.SCRIPT_SCAN, "MyScript", "error")
        events = read_events()
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].sensitive)
        self.assertEqual(events[0].result, "error")


if __name__ == "__main__":
    unittest.main()
