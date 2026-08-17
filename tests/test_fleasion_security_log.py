"""
Tests de la journalisation des lancements/arrêts Fleasion dans le journal de
sécurité (core/security_log.py, catégorie EXTERNAL_EXECUTION déjà
existante — pas de nouvelle catégorie créée pour Fleasion) — chemin de log
redirigé vers un fichier temporaire, jamais le vrai journal de
l'utilisateur.
"""
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from core.security_log import Category, log_event, read_events


class TestFleasionSecurityLog(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.mkdtemp(prefix="zenkai_fleasion_security_log_test_")
        self._log_path = os.path.join(self._temp_dir, "security_events.jsonl")
        self._patcher = patch("core.security_log.get_security_log_path", return_value=self._log_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def test_fleasion_launch_round_trips_as_sensitive_external_execution(self):
        log_event("fleasion_launch", Category.EXTERNAL_EXECUTION, "Fleasion", "ok")
        events = read_events()
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.action, "fleasion_launch")
        self.assertEqual(event.category, Category.EXTERNAL_EXECUTION)
        self.assertEqual(event.target, "Fleasion")
        self.assertEqual(event.result, "ok")
        self.assertTrue(event.sensitive)

    def test_fleasion_stop_failure_round_trips(self):
        log_event("fleasion_stop", Category.EXTERNAL_EXECUTION, "Fleasion", "error")
        events = read_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].result, "error")
        self.assertTrue(events[0].sensitive)


if __name__ == "__main__":
    unittest.main()
