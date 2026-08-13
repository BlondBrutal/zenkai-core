"""
Tests de la détection de l'interpréteur AutoHotkey (features/custom_script/
ahk_detect.py) — registre et système de fichiers mockés, jamais touché pour
de vrai (ni le vrai registre Windows, ni une vraie recherche disque, ni la
vraie copie embarquée du dépôt).
"""
import unittest
from unittest.mock import patch

from features.custom_script import ahk_detect


class TestFindEmbeddedAhkInterpreter(unittest.TestCase):
    def test_prefers_64bit_over_32bit(self):
        def fake_isfile(path):
            return path in (
                ahk_detect._EMBEDDED_AHK_DIR + r"\AutoHotkey64.exe",
                ahk_detect._EMBEDDED_AHK_DIR + r"\AutoHotkey32.exe",
            )

        with patch("os.path.isfile", side_effect=fake_isfile):
            result = ahk_detect.find_embedded_ahk_interpreter()
            self.assertEqual(result, ahk_detect._EMBEDDED_AHK_DIR + r"\AutoHotkey64.exe")

    def test_falls_back_to_32bit_when_64bit_missing(self):
        def fake_isfile(path):
            return path == ahk_detect._EMBEDDED_AHK_DIR + r"\AutoHotkey32.exe"

        with patch("os.path.isfile", side_effect=fake_isfile):
            result = ahk_detect.find_embedded_ahk_interpreter()
            self.assertEqual(result, ahk_detect._EMBEDDED_AHK_DIR + r"\AutoHotkey32.exe")

    def test_none_when_neither_present(self):
        with patch("os.path.isfile", return_value=False):
            self.assertIsNone(ahk_detect.find_embedded_ahk_interpreter())


class TestFindAhkInterpreter(unittest.TestCase):
    def test_embedded_copy_takes_priority_over_system_install(self):
        # Même si une install système existe, la copie embarquée doit gagner.
        def fake_isfile(path):
            return path in (
                ahk_detect._EMBEDDED_AHK_DIR + r"\AutoHotkey64.exe",
                r"C:\Program Files\AutoHotkey\AutoHotkey64.exe",
            )

        with patch.object(ahk_detect, "_registry_install_dirs", return_value=[]), \
             patch.object(ahk_detect, "_fallback_dirs", return_value=[r"C:\Program Files\AutoHotkey"]), \
             patch("os.path.isfile", side_effect=fake_isfile):
            result = ahk_detect.find_ahk_interpreter()
            self.assertEqual(result, ahk_detect._EMBEDDED_AHK_DIR + r"\AutoHotkey64.exe")
            self.assertEqual(ahk_detect.health_check(), "ok")

    def test_falls_back_to_system_when_embedded_missing(self):
        registry_dir = r"C:\Custom\AutoHotkey"

        def fake_isfile(path):
            return path == registry_dir + r"\AutoHotkey64.exe"

        with patch.object(ahk_detect, "_registry_install_dirs", return_value=[registry_dir]), \
             patch.object(ahk_detect, "_fallback_dirs", return_value=[r"C:\Program Files\AutoHotkey"]), \
             patch("os.path.isfile", side_effect=fake_isfile):
            result = ahk_detect.find_ahk_interpreter()
            self.assertEqual(result, registry_dir + r"\AutoHotkey64.exe")
            self.assertEqual(ahk_detect.health_check(), "ok")

    def test_missing_everywhere_returns_none(self):
        with patch.object(ahk_detect, "_registry_install_dirs", return_value=[]), \
             patch.object(ahk_detect, "_fallback_dirs", return_value=[r"C:\Program Files\AutoHotkey"]), \
             patch("os.path.isfile", return_value=False):
            self.assertIsNone(ahk_detect.find_ahk_interpreter())
            self.assertEqual(ahk_detect.health_check(), "missing")

    def test_system_fallback_still_recognizes_v1_names(self):
        # Repli système : reconnaît aussi une installation v1.1 classique
        # (nom d'exe différent), pas seulement v2.
        registry_dir = r"C:\Custom\AutoHotkey"

        def fake_isfile(path):
            return path == registry_dir + r"\AutoHotkeyU64.exe"

        with patch.object(ahk_detect, "_registry_install_dirs", return_value=[registry_dir]), \
             patch.object(ahk_detect, "_fallback_dirs", return_value=[r"C:\Program Files\AutoHotkey"]), \
             patch("os.path.isfile", side_effect=fake_isfile):
            result = ahk_detect.find_ahk_interpreter()
            self.assertEqual(result, registry_dir + r"\AutoHotkeyU64.exe")

    def test_registry_takes_priority_over_fallback_dir(self):
        registry_dir = r"C:\Custom\AutoHotkey"
        fallback_dir = r"C:\Program Files\AutoHotkey"

        def fake_isfile(path):
            return path in (
                registry_dir + r"\AutoHotkey64.exe",
                fallback_dir + r"\AutoHotkey64.exe",
            )

        with patch.object(ahk_detect, "_registry_install_dirs", return_value=[registry_dir]), \
             patch.object(ahk_detect, "_fallback_dirs", return_value=[fallback_dir]), \
             patch("os.path.isfile", side_effect=fake_isfile):
            result = ahk_detect.find_ahk_interpreter()
            self.assertEqual(result, registry_dir + r"\AutoHotkey64.exe")


if __name__ == "__main__":
    unittest.main()
