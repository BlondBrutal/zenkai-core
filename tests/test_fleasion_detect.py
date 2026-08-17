"""
Tests de la détection de l'exécutable Fleasion (features/fleasion/
fleasion_detect.py) — système de fichiers mocké, jamais touché pour de vrai
(ni la vraie copie embarquée du dépôt, ni une vraie recherche disque).
"""
import unittest
from unittest.mock import patch

from features.fleasion import fleasion_detect


class TestFindEmbeddedFleasionInterpreter(unittest.TestCase):
    def test_finds_versioned_exe_name(self):
        candidate = fleasion_detect._EMBEDDED_FLEASION_DIR + r"\Fleasion-v2.3.0.exe"
        with patch("glob.glob", return_value=[candidate]):
            self.assertEqual(fleasion_detect.find_embedded_fleasion_interpreter(), candidate)

    def test_none_when_no_match(self):
        with patch("glob.glob", return_value=[]):
            self.assertIsNone(fleasion_detect.find_embedded_fleasion_interpreter())

    def test_picks_first_of_sorted_candidates_when_several_present(self):
        older = fleasion_detect._EMBEDDED_FLEASION_DIR + r"\Fleasion-v1.0.0.exe"
        newer = fleasion_detect._EMBEDDED_FLEASION_DIR + r"\Fleasion-v2.0.0.exe"
        with patch("glob.glob", return_value=[newer, older]):
            # sorted() alphabétique : "v1.0.0" < "v2.0.0" lexicographiquement.
            self.assertEqual(fleasion_detect.find_embedded_fleasion_interpreter(), older)


class TestFindFleasionInterpreter(unittest.TestCase):
    def test_embedded_copy_takes_priority_over_system_install(self):
        embedded = fleasion_detect._EMBEDDED_FLEASION_DIR + r"\Fleasion-v2.3.0.exe"
        with patch.object(fleasion_detect, "find_embedded_fleasion_interpreter", return_value=embedded), \
             patch.object(fleasion_detect, "find_system_fleasion_interpreter", return_value=r"C:\Fleasion\Fleasion.exe"):
            result = fleasion_detect.find_fleasion_interpreter()
            self.assertEqual(result, embedded)
            self.assertEqual(fleasion_detect.health_check(), "ok")

    def test_falls_back_to_system_when_embedded_missing(self):
        system_path = r"C:\Users\Test\AppData\Local\Programs\Fleasion\Fleasion.exe"
        with patch.object(fleasion_detect, "find_embedded_fleasion_interpreter", return_value=None), \
             patch.object(fleasion_detect, "find_system_fleasion_interpreter", return_value=system_path):
            result = fleasion_detect.find_fleasion_interpreter()
            self.assertEqual(result, system_path)
            self.assertEqual(fleasion_detect.health_check(), "ok")

    def test_missing_everywhere_returns_none(self):
        with patch.object(fleasion_detect, "find_embedded_fleasion_interpreter", return_value=None), \
             patch.object(fleasion_detect, "find_system_fleasion_interpreter", return_value=None):
            self.assertIsNone(fleasion_detect.find_fleasion_interpreter())
            self.assertEqual(fleasion_detect.health_check(), "missing")


class TestFindSystemFleasionInterpreter(unittest.TestCase):
    def test_finds_exact_exe_name_in_fallback_dir(self):
        fallback_dir = r"C:\Program Files\Fleasion"

        def fake_isfile(path):
            return path == fallback_dir + r"\Fleasion.exe"

        with patch.object(fleasion_detect, "_fallback_dirs", return_value=[fallback_dir]), \
             patch("os.path.isfile", side_effect=fake_isfile), \
             patch("glob.glob", return_value=[]):
            result = fleasion_detect.find_system_fleasion_interpreter()
            self.assertEqual(result, fallback_dir + r"\Fleasion.exe")

    def test_falls_back_to_path_lookup(self):
        with patch.object(fleasion_detect, "_fallback_dirs", return_value=[r"C:\Program Files\Fleasion"]), \
             patch("os.path.isfile", return_value=False), \
             patch("glob.glob", return_value=[]), \
             patch("shutil.which", return_value=r"C:\Somewhere\Fleasion.exe"):
            result = fleasion_detect.find_system_fleasion_interpreter()
            self.assertEqual(result, r"C:\Somewhere\Fleasion.exe")

    def test_none_when_nothing_found(self):
        with patch.object(fleasion_detect, "_fallback_dirs", return_value=[r"C:\Program Files\Fleasion"]), \
             patch("os.path.isfile", return_value=False), \
             patch("glob.glob", return_value=[]), \
             patch("shutil.which", return_value=None):
            self.assertIsNone(fleasion_detect.find_system_fleasion_interpreter())


if __name__ == "__main__":
    unittest.main()
