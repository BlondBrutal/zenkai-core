"""
Tests (pytest) de la détection de jeu en cours d'exécution (features/
performance/game_detection.py) — psutil.process_iter mocké, jamais de vrai
scan de processus.
"""
from unittest.mock import patch

import psutil

from features.performance.game_detection import KNOWN_GAMES, ROBLOX_EXE_NAME, detect_foreground_game


class _FakeProcess:
    def __init__(self, name=None, raise_exc=None):
        self._name = name
        self._raise_exc = raise_exc

    @property
    def info(self):
        if self._raise_exc is not None:
            raise self._raise_exc
        return {"name": self._name}


def test_returns_none_when_no_known_game_running():
    with patch("psutil.process_iter", return_value=[_FakeProcess("explorer.exe"), _FakeProcess("chrome.exe")]):
        assert detect_foreground_game() is None


def test_detects_roblox_case_insensitive():
    with patch("psutil.process_iter", return_value=[_FakeProcess("RobloxPlayerBeta.EXE")]):
        result = detect_foreground_game()
        assert result == (ROBLOX_EXE_NAME, "Roblox")


def test_detects_non_roblox_known_game():
    with patch("psutil.process_iter", return_value=[_FakeProcess("cs2.exe")]):
        assert detect_foreground_game() == ("cs2.exe", "Counter-Strike 2")


def test_returns_first_match_when_multiple_known_games_running():
    processes = [_FakeProcess("dota2.exe"), _FakeProcess("cs2.exe")]
    with patch("psutil.process_iter", return_value=processes):
        assert detect_foreground_game() == ("dota2.exe", "Dota 2")


def test_skips_processes_that_raise_no_such_process():
    processes = [_FakeProcess("ghost.exe", raise_exc=psutil.NoSuchProcess(1)), _FakeProcess("cs2.exe")]
    with patch("psutil.process_iter", return_value=processes):
        assert detect_foreground_game() == ("cs2.exe", "Counter-Strike 2")


def test_skips_processes_that_raise_access_denied():
    processes = [_FakeProcess("protected.exe", raise_exc=psutil.AccessDenied(1)), _FakeProcess("dota2.exe")]
    with patch("psutil.process_iter", return_value=processes):
        assert detect_foreground_game() == ("dota2.exe", "Dota 2")


def test_never_raises_even_if_process_iter_itself_fails():
    with patch("psutil.process_iter", side_effect=RuntimeError("boom")):
        assert detect_foreground_game() is None


def test_minecraft_java_intentionally_not_recognized():
    # Voir le commentaire dans game_detection.py : "javaw.exe" n'est
    # délibérément PAS dans KNOWN_GAMES (faux positif pour toute appli Java).
    assert "javaw.exe" not in KNOWN_GAMES
    with patch("psutil.process_iter", return_value=[_FakeProcess("javaw.exe")]):
        assert detect_foreground_game() is None


def test_minecraft_bedrock_is_recognized():
    with patch("psutil.process_iter", return_value=[_FakeProcess("Minecraft.Windows.exe")]):
        assert detect_foreground_game() == ("minecraft.windows.exe", "Minecraft")
