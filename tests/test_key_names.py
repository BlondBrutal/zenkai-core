"""
Tests (pytest) de la traduction de touches/boutons Qt <-> pydirectinput <->
pynput (features/macro_pixel/key_names.py) — pures tables de correspondance,
aucun mock nécessaire (PyQt6.QtCore.Qt/pydirectinput/pynput ne sont utilisés
ici que pour leurs constantes/enums statiques, jamais pour une vraie
simulation d'entrée).
"""
from PyQt6.QtCore import Qt
from pynput import mouse as pynput_mouse

from features.macro_pixel.key_names import (
    MOUSE_BUTTON_LEFT, MOUSE_BUTTON_MIDDLE, MOUSE_BUTTON_RIGHT, MOUSE_BUTTON_X1, MOUSE_BUTTON_X2,
    is_mouse_button_name, name_to_pynput_mouse_button, pynput_key_to_pydirectinput,
    pynput_mouse_button_to_name, qt_key_to_pydirectinput, qt_mouse_button_to_name,
)


class TestQtKeyToPydirectinput:
    def test_special_key_mapped_regardless_of_text(self):
        assert qt_key_to_pydirectinput(Qt.Key.Key_Space, "") == "space"
        assert qt_key_to_pydirectinput(Qt.Key.Key_Escape, "\x1b") == "esc"

    def test_function_keys_mapped(self):
        assert qt_key_to_pydirectinput(Qt.Key.Key_F1, "") == "f1"
        assert qt_key_to_pydirectinput(Qt.Key.Key_F12, "") == "f12"

    def test_regular_letter_uses_text_lowercased(self):
        assert qt_key_to_pydirectinput(Qt.Key.Key_A, "A") == "a"
        assert qt_key_to_pydirectinput(Qt.Key.Key_A, "a") == "a"

    def test_digit_uses_text(self):
        assert qt_key_to_pydirectinput(Qt.Key.Key_5, "5") == "5"

    def test_unknown_key_returns_none(self):
        # Une touche sans texte connu (ex: une touche morte/non gérée) et pas
        # dans _SPECIAL_KEYS ne doit jamais faire semblant de mapper.
        assert qt_key_to_pydirectinput(Qt.Key.Key_unknown, "") is None

    def test_empty_text_never_matches_empty_string_in_mapping(self):
        assert qt_key_to_pydirectinput(Qt.Key.Key_A, "") is None


class TestPynputKeyToPydirectinput:
    class _FakeSpecialKey:
        def __init__(self, name):
            self.name = name

    class _FakeCharKey:
        char = None

        def __init__(self, char):
            self.char = char

    def test_special_key_by_name(self):
        assert pynput_key_to_pydirectinput(self._FakeSpecialKey("space")) == "space"
        assert pynput_key_to_pydirectinput(self._FakeSpecialKey("ctrl_l")) == "ctrl"
        assert pynput_key_to_pydirectinput(self._FakeSpecialKey("page_up")) == "pageup"

    def test_function_key_by_name(self):
        assert pynput_key_to_pydirectinput(self._FakeSpecialKey("f5")) == "f5"

    def test_unknown_special_name_returns_none(self):
        assert pynput_key_to_pydirectinput(self._FakeSpecialKey("totally_unknown_key")) is None

    def test_char_key_lowercased(self):
        assert pynput_key_to_pydirectinput(self._FakeCharKey("A")) == "a"

    def test_char_key_not_in_mapping_returns_none(self):
        # Un caractère qui n'existe simplement pas dans pydirectinput.KEYBOARD_MAPPING.
        assert pynput_key_to_pydirectinput(self._FakeCharKey("\x01")) is None

    def test_object_without_name_or_char_returns_none(self):
        class _Empty:
            pass
        assert pynput_key_to_pydirectinput(_Empty()) is None


class TestMouseButtonNames:
    def test_qt_mouse_button_round_trip(self):
        assert qt_mouse_button_to_name(Qt.MouseButton.LeftButton) == MOUSE_BUTTON_LEFT
        assert qt_mouse_button_to_name(Qt.MouseButton.RightButton) == MOUSE_BUTTON_RIGHT
        assert qt_mouse_button_to_name(Qt.MouseButton.MiddleButton) == MOUSE_BUTTON_MIDDLE
        assert qt_mouse_button_to_name(Qt.MouseButton.XButton1) == MOUSE_BUTTON_X1
        assert qt_mouse_button_to_name(Qt.MouseButton.XButton2) == MOUSE_BUTTON_X2

    def test_qt_unknown_button_returns_none(self):
        assert qt_mouse_button_to_name(Qt.MouseButton.NoButton) is None

    def test_pynput_mouse_button_round_trip(self):
        assert pynput_mouse_button_to_name(pynput_mouse.Button.left) == MOUSE_BUTTON_LEFT
        assert pynput_mouse_button_to_name(pynput_mouse.Button.right) == MOUSE_BUTTON_RIGHT

    def test_is_mouse_button_name(self):
        assert is_mouse_button_name(MOUSE_BUTTON_LEFT) is True
        assert is_mouse_button_name("f1") is False
        assert is_mouse_button_name("left") is False  # nom clavier, pas "mouse_left"

    def test_name_to_pynput_mouse_button_round_trip(self):
        assert name_to_pynput_mouse_button(MOUSE_BUTTON_LEFT) is pynput_mouse.Button.left
        assert name_to_pynput_mouse_button(MOUSE_BUTTON_X2) is pynput_mouse.Button.x2

    def test_name_to_pynput_mouse_button_unknown_returns_none(self):
        assert name_to_pynput_mouse_button("mouse_unknown") is None

    def test_every_qt_button_name_resolves_back_via_pynput_table(self):
        # Les deux tables (Qt->nom, pynput->nom) doivent produire exactement
        # les mêmes identifiants "mouse_*", pour qu'une touche capturée côté
        # Qt (UI) soit bien reconnue côté pynput (écoute globale) et
        # inversement — sans ça, une touche de déclenchement capturée dans
        # l'UI ne se déclencherait jamais depuis l'écoute globale en jeu.
        for name in (MOUSE_BUTTON_LEFT, MOUSE_BUTTON_RIGHT, MOUSE_BUTTON_MIDDLE, MOUSE_BUTTON_X1, MOUSE_BUTTON_X2):
            button = name_to_pynput_mouse_button(name)
            assert button is not None
            assert pynput_mouse_button_to_name(button) == name
