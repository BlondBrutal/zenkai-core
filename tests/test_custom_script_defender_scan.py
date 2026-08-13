"""
Tests du scan Windows Defender à la demande (features/custom_script/
defender_scan.py) — arborescence MpCmdRun.exe factice sous un dossier
temporaire, et subprocess.run mocké : aucun vrai scan Defender n'est jamais
déclenché par ces tests.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from features.custom_script import defender_scan


class TestFindMpCmdRun(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.mkdtemp(prefix="zenkai_defender_test_")
        self._patcher = patch.object(defender_scan, "_DEFENDER_PLATFORM_DIR", self._temp_dir)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def _make_version_dir(self, name: str, with_exe: bool, mtime_offset: float = 0.0) -> str:
        version_dir = os.path.join(self._temp_dir, name)
        os.makedirs(version_dir, exist_ok=True)
        if with_exe:
            exe_path = os.path.join(version_dir, "MpCmdRun.exe")
            with open(exe_path, "w", encoding="utf-8") as f:
                f.write("fake")
        if mtime_offset:
            new_time = os.path.getmtime(version_dir) + mtime_offset
            os.utime(version_dir, (new_time, new_time))
        return version_dir

    def test_no_platform_dir_returns_none(self):
        shutil.rmtree(self._temp_dir)
        self.assertIsNone(defender_scan.find_mpcmdrun())

    def test_no_version_folders_returns_none(self):
        self.assertIsNone(defender_scan.find_mpcmdrun())

    def test_picks_most_recent_version_that_actually_has_the_exe(self):
        self._make_version_dir("4.18.100.0", with_exe=True, mtime_offset=-100)
        self._make_version_dir("4.18.200.0", with_exe=False, mtime_offset=0)  # plus récent, mais incomplet
        result = defender_scan.find_mpcmdrun()
        self.assertEqual(result, os.path.join(self._temp_dir, "4.18.100.0", "MpCmdRun.exe"))


class TestScanFile(unittest.TestCase):
    def test_mpcmdrun_not_found_returns_unavailable(self):
        with patch.object(defender_scan, "find_mpcmdrun", return_value=None):
            result = defender_scan.scan_file("C:\\fake\\script.ahk")
        self.assertFalse(result.available)
        self.assertIsNone(result.clean)

    def test_exit_code_zero_is_clean(self):
        fake_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
        with patch.object(defender_scan, "find_mpcmdrun", return_value="C:\\fake\\MpCmdRun.exe"), \
             patch("subprocess.run", return_value=fake_result):
            result = defender_scan.scan_file("C:\\fake\\script.ahk")
        self.assertTrue(result.available)
        self.assertTrue(result.clean)
        self.assertEqual(result.exit_code, 0)

    def test_nonzero_exit_code_is_not_clean(self):
        fake_result = subprocess.CompletedProcess(args=[], returncode=2, stdout="threat found", stderr="")
        with patch.object(defender_scan, "find_mpcmdrun", return_value="C:\\fake\\MpCmdRun.exe"), \
             patch("subprocess.run", return_value=fake_result):
            result = defender_scan.scan_file("C:\\fake\\script.ahk")
        self.assertFalse(result.clean)
        self.assertEqual(result.exit_code, 2)

    def test_timeout_is_inconclusive_never_raises(self):
        with patch.object(defender_scan, "find_mpcmdrun", return_value="C:\\fake\\MpCmdRun.exe"), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="MpCmdRun.exe", timeout=90)):
            result = defender_scan.scan_file("C:\\fake\\script.ahk")
        self.assertTrue(result.available)
        self.assertIsNone(result.clean)

    def test_unexpected_exception_is_inconclusive_never_raises(self):
        with patch.object(defender_scan, "find_mpcmdrun", return_value="C:\\fake\\MpCmdRun.exe"), \
             patch("subprocess.run", side_effect=OSError("boom")):
            result = defender_scan.scan_file("C:\\fake\\script.ahk")
        self.assertTrue(result.available)
        self.assertIsNone(result.clean)


if __name__ == "__main__":
    unittest.main()
