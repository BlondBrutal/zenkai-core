"""
Tests (pytest) du lancement/arrêt des scripts AutoHotkey personnalisés
(features/custom_script/process_manager.py) — subprocess/psutil/deelevate
mockés, jamais un vrai interpréteur AutoHotkey lancé. Même approche que
tests/test_fleasion_process_manager.py (module quasi jumeau), adaptée au
paramètre CustomScriptEntry/zkscript_path supplémentaire de ce module-ci.
"""
import os
from unittest.mock import MagicMock, patch

import pytest

import features.custom_script.process_manager as pm
from features.custom_script.deelevate import DeelevationResult
from features.custom_script.script_store import CustomScriptEntry


@pytest.fixture(autouse=True)
def isolated_security_log(tmp_path, monkeypatch):
    monkeypatch.setattr("core.security_log.get_security_log_path", lambda: str(tmp_path / "security_events.jsonl"))


def _make_entry(script_text="MsgBox, Hello") -> CustomScriptEntry:
    return CustomScriptEntry(id="abcdef1234", name="Test Script", script_text=script_text, created_at="", updated_at="")


class TestWriteCompanionAhkFile:
    def test_writes_script_text_next_to_zkscript(self, tmp_path):
        zkscript_path = str(tmp_path / "test.zkscript")
        entry = _make_entry("MsgBox, Hi")
        ahk_path = pm.write_companion_ahk_file(entry, zkscript_path)
        assert ahk_path == str(tmp_path / "test.ahk")
        with open(ahk_path, encoding="utf-8") as f:
            assert f.read() == "MsgBox, Hi"

    def test_always_regenerated_never_stale(self, tmp_path):
        zkscript_path = str(tmp_path / "test.zkscript")
        entry = _make_entry("first version")
        ahk_path = pm.write_companion_ahk_file(entry, zkscript_path)
        entry.script_text = "second version"
        pm.write_companion_ahk_file(entry, zkscript_path)
        with open(ahk_path, encoding="utf-8") as f:
            assert f.read() == "second version"


class TestStartScript:
    def test_returns_none_none_when_interpreter_missing(self, tmp_path):
        with patch.object(pm, "find_ahk_interpreter", return_value=None):
            running, error = pm.start_script(_make_entry(), str(tmp_path / "s.zkscript"))
        assert running is None
        assert error is None

    def test_not_admin_uses_direct_popen(self, tmp_path):
        fake_proc = MagicMock()
        fake_proc.pid = 4321
        with patch.object(pm, "find_ahk_interpreter", return_value=r"C:\fake\AutoHotkey64.exe"), \
             patch.object(pm, "is_admin", return_value=False), \
             patch("subprocess.Popen", return_value=fake_proc) as mock_popen:
            running, error = pm.start_script(_make_entry(), str(tmp_path / "s.zkscript"))
        assert error is None
        assert running.pid == 4321
        assert running.popen is fake_proc
        args = mock_popen.call_args[0][0]
        assert args[0] == r"C:\fake\AutoHotkey64.exe"
        assert args[1].endswith("s.ahk")

    def test_admin_uses_deelevated_launch(self, tmp_path):
        with patch.object(pm, "find_ahk_interpreter", return_value=r"C:\fake\AutoHotkey64.exe"), \
             patch.object(pm, "is_admin", return_value=True), \
             patch.object(pm, "launch_deelevated", return_value=DeelevationResult(pid=555, error_detail=None)):
            running, error = pm.start_script(_make_entry(), str(tmp_path / "s.zkscript"))
        assert error is None
        assert running.pid == 555
        assert running.popen is None

    def test_admin_launch_failure_returns_error_detail(self, tmp_path):
        with patch.object(pm, "find_ahk_interpreter", return_value=r"C:\fake\AutoHotkey64.exe"), \
             patch.object(pm, "is_admin", return_value=True), \
             patch.object(pm, "launch_deelevated", return_value=DeelevationResult(pid=None, error_detail="boom")):
            running, error = pm.start_script(_make_entry(), str(tmp_path / "s.zkscript"))
        assert running is None
        assert error == "boom"

    def test_not_admin_popen_oserror_returns_error_detail(self, tmp_path):
        with patch.object(pm, "find_ahk_interpreter", return_value=r"C:\fake\AutoHotkey64.exe"), \
             patch.object(pm, "is_admin", return_value=False), \
             patch("subprocess.Popen", side_effect=OSError("access denied")):
            running, error = pm.start_script(_make_entry(), str(tmp_path / "s.zkscript"))
        assert running is None
        assert "access denied" in error


class TestStopScript:
    def _running(self, popen=None, pid=999):
        return pm.RunningScript(
            entry_id="abcdef1234", pid=pid, popen=popen, exe_path="x", script_path="y", started_at=0.0,
        )

    def test_already_exited_popen_returns_true(self):
        fake_proc = MagicMock()
        fake_proc.poll.return_value = 0
        assert pm.stop_script(self._running(popen=fake_proc)) is True

    def test_kills_and_confirms(self):
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        still_running = MagicMock()
        still_running.is_running.return_value = True
        with patch("psutil.Process", return_value=still_running), patch("psutil.pid_exists", return_value=False):
            assert pm.stop_script(self._running(popen=fake_proc)) is True
        fake_proc.kill.assert_called_once()

    def test_returns_false_if_still_alive_after_kill(self):
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        still_running = MagicMock()
        still_running.is_running.return_value = True
        with patch("psutil.Process", return_value=still_running), \
             patch("psutil.pid_exists", return_value=True), patch("time.sleep"):
            assert pm.stop_script(self._running(popen=fake_proc)) is False

    def test_no_popen_handle_uses_psutil_only(self):
        # Chemin dé-élevé (voir launch_deelevated) : jamais de handle Popen,
        # uniquement le PID renvoyé par la tâche planifiée.
        import psutil as psutil_mod
        with patch("psutil.Process", side_effect=psutil_mod.NoSuchProcess(1234)):
            assert pm.stop_script(self._running(popen=None, pid=1234)) is True
