"""
Tests du lancement/arrêt du process Fleasion partagé (features/fleasion/
process_manager.py) — subprocess/psutil/deelevate mockés, jamais un vrai
process lancé, journal de sécurité redirigé vers un fichier temporaire.
"""
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from features.custom_script.deelevate import DeelevationResult
from features.fleasion import process_manager as pm


class TestProcessManager(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.mkdtemp(prefix="zenkai_fleasion_security_log_test_")
        self._log_path = os.path.join(self._temp_dir, "security_events.jsonl")
        self._log_patcher = patch("core.security_log.get_security_log_path", return_value=self._log_path)
        self._log_patcher.start()

    def tearDown(self):
        self._log_patcher.stop()
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def test_start_returns_none_none_when_exe_missing(self):
        with patch.object(pm, "find_fleasion_interpreter", return_value=None):
            running, error = pm.start_fleasion()
        self.assertIsNone(running)
        self.assertIsNone(error)

    def test_start_not_admin_uses_direct_popen(self):
        fake_proc = MagicMock()
        fake_proc.pid = 4242
        with patch.object(pm, "find_fleasion_interpreter", return_value=r"C:\fake\Fleasion.exe"), \
             patch.object(pm, "is_admin", return_value=False), \
             patch("subprocess.Popen", return_value=fake_proc) as mock_popen:
            running, error = pm.start_fleasion()
        self.assertIsNone(error)
        self.assertEqual(running.pid, 4242)
        self.assertIs(running.popen, fake_proc)
        mock_popen.assert_called_once()
        self.assertEqual(mock_popen.call_args[0][0], [r"C:\fake\Fleasion.exe"])

    def test_start_admin_uses_deelevated_launch(self):
        with patch.object(pm, "find_fleasion_interpreter", return_value=r"C:\fake\Fleasion.exe"), \
             patch.object(pm, "is_admin", return_value=True), \
             patch.object(pm, "launch_deelevated", return_value=DeelevationResult(pid=5555, error_detail=None)):
            running, error = pm.start_fleasion()
        self.assertIsNone(error)
        self.assertEqual(running.pid, 5555)
        self.assertIsNone(running.popen)

    def test_start_admin_launch_failure_returns_error_detail(self):
        with patch.object(pm, "find_fleasion_interpreter", return_value=r"C:\fake\Fleasion.exe"), \
             patch.object(pm, "is_admin", return_value=True), \
             patch.object(pm, "launch_deelevated", return_value=DeelevationResult(pid=None, error_detail="boom")):
            running, error = pm.start_fleasion()
        self.assertIsNone(running)
        self.assertEqual(error, "boom")

    def test_stop_already_exited_popen_returns_true(self):
        fake_proc = MagicMock()
        fake_proc.poll.return_value = 0  # déjà sorti
        running = pm.RunningFleasion(pid=1, popen=fake_proc, exe_path="x", started_at=0.0)
        self.assertTrue(pm.stop_fleasion(running))

    def test_stop_kills_and_confirms(self):
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None  # encore en cours au premier check
        running = pm.RunningFleasion(pid=777, popen=fake_proc, exe_path="x", started_at=0.0)
        still_running_proc = MagicMock()
        still_running_proc.is_running.return_value = True
        with patch("psutil.Process", return_value=still_running_proc), \
             patch("psutil.pid_exists", return_value=False):
            self.assertTrue(pm.stop_fleasion(running))
        fake_proc.kill.assert_called_once()

    def test_stop_returns_false_if_still_alive_after_kill(self):
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        running = pm.RunningFleasion(pid=888, popen=fake_proc, exe_path="x", started_at=0.0)
        still_running_proc = MagicMock()
        still_running_proc.is_running.return_value = True
        with patch("psutil.Process", return_value=still_running_proc), \
             patch("psutil.pid_exists", return_value=True), \
             patch("time.sleep"):
            self.assertFalse(pm.stop_fleasion(running))


if __name__ == "__main__":
    unittest.main()
