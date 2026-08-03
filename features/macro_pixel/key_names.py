"""
Traduit une touche Qt (Qt.Key + le texte du QKeyEvent) vers l'identifiant de
touche attendu par `pydirectinput`, seule bibliothèque de simulation clavier
utilisée dans l'app. Retourne None si la touche n'a pas d'équivalent connu
(plutôt que de faire semblant de mapper quelque chose qui ne marchera pas).
"""
from PyQt6.QtCore import Qt

import pydirectinput
from pynput import mouse as pynput_mouse

_SPECIAL_KEYS = {
    Qt.Key.Key_Space: "space",
    Qt.Key.Key_Return: "enter",
    Qt.Key.Key_Enter: "enter",
    Qt.Key.Key_Tab: "tab",
    Qt.Key.Key_Backspace: "backspace",
    Qt.Key.Key_Delete: "delete",
    Qt.Key.Key_Escape: "esc",
    Qt.Key.Key_Up: "up",
    Qt.Key.Key_Down: "down",
    Qt.Key.Key_Left: "left",
    Qt.Key.Key_Right: "right",
    Qt.Key.Key_Home: "home",
    Qt.Key.Key_End: "end",
    Qt.Key.Key_PageUp: "pageup",
    Qt.Key.Key_PageDown: "pagedown",
    Qt.Key.Key_Insert: "insert",
    Qt.Key.Key_CapsLock: "capslock",
    Qt.Key.Key_NumLock: "numlock",
    Qt.Key.Key_ScrollLock: "scrolllock",
    Qt.Key.Key_Pause: "pause",
    Qt.Key.Key_Print: "printscreen",
    Qt.Key.Key_Shift: "shift",
    Qt.Key.Key_Control: "ctrl",
    Qt.Key.Key_Alt: "alt",
    Qt.Key.Key_Meta: "win",
    Qt.Key.Key_Menu: "apps",
    **{getattr(Qt.Key, f"Key_F{i}"): f"f{i}" for i in range(1, 13)},
}


def qt_key_to_pydirectinput(key: int, text: str) -> str | None:
    if key in _SPECIAL_KEYS:
        return _SPECIAL_KEYS[key]

    candidate = text.lower()
    if candidate and candidate in pydirectinput.KEYBOARD_MAPPING:
        return candidate

    return None


# Même principe que _SPECIAL_KEYS mais dans l'autre sens (pynput -> nom
# pydirectinput), pour le "changement rapide de touche" : la touche de
# changement est capturée dans l'UI (Qt) mais doit être reconnue dans les
# événements clavier globaux (pynput.keyboard.Listener), qui continuent
# d'arriver même quand la fenêtre de l'app n'a pas le focus (ex. en jeu).
_PYNPUT_SPECIAL_KEYS = {
    "space": "space",
    "enter": "enter",
    "tab": "tab",
    "backspace": "backspace",
    "delete": "delete",
    "esc": "esc",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "home": "home",
    "end": "end",
    "page_up": "pageup",
    "page_down": "pagedown",
    "insert": "insert",
    "caps_lock": "capslock",
    "num_lock": "numlock",
    "scroll_lock": "scrolllock",
    "pause": "pause",
    "print_screen": "printscreen",
    "shift": "shift", "shift_l": "shift", "shift_r": "shift",
    "ctrl": "ctrl", "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "alt": "alt", "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
    "cmd": "win", "cmd_l": "win", "cmd_r": "win",
    "menu": "apps",
    **{f"f{i}": f"f{i}" for i in range(1, 13)},
}


def pynput_key_to_pydirectinput(key) -> str | None:
    """Équivalent de qt_key_to_pydirectinput pour un événement pynput
    (keyboard.Key ou keyboard.KeyCode)."""
    name = getattr(key, "name", None)
    if name is not None:
        return _PYNPUT_SPECIAL_KEYS.get(name)

    char = getattr(key, "char", None)
    if char:
        candidate = char.lower()
        if candidate in pydirectinput.KEYBOARD_MAPPING:
            return candidate

    return None


# ---------------------------------------------------------------------------
# Boutons de souris capturables comme touche de déclenchement/réaction/swap
# (voir ui/key_capture_widget.py) : préfixe "mouse_" pour ne jamais entrer en
# collision avec les noms de touches fléchées clavier ci-dessus ("left"/
# "right" existent déjà dans _SPECIAL_KEYS pour les flèches).
MOUSE_BUTTON_LEFT = "mouse_left"
MOUSE_BUTTON_RIGHT = "mouse_right"
MOUSE_BUTTON_MIDDLE = "mouse_middle"
MOUSE_BUTTON_X1 = "mouse_x1"
MOUSE_BUTTON_X2 = "mouse_x2"

_QT_MOUSE_BUTTON_NAMES = {
    Qt.MouseButton.LeftButton: MOUSE_BUTTON_LEFT,
    Qt.MouseButton.RightButton: MOUSE_BUTTON_RIGHT,
    Qt.MouseButton.MiddleButton: MOUSE_BUTTON_MIDDLE,
    Qt.MouseButton.XButton1: MOUSE_BUTTON_X1,
    Qt.MouseButton.XButton2: MOUSE_BUTTON_X2,
}

_PYNPUT_MOUSE_BUTTON_NAMES = {
    pynput_mouse.Button.left: MOUSE_BUTTON_LEFT,
    pynput_mouse.Button.right: MOUSE_BUTTON_RIGHT,
    pynput_mouse.Button.middle: MOUSE_BUTTON_MIDDLE,
    pynput_mouse.Button.x1: MOUSE_BUTTON_X1,
    pynput_mouse.Button.x2: MOUSE_BUTTON_X2,
}
_NAME_TO_PYNPUT_MOUSE_BUTTON = {name: button for button, name in _PYNPUT_MOUSE_BUTTON_NAMES.items()}


def is_mouse_button_name(name: str) -> bool:
    return name in _NAME_TO_PYNPUT_MOUSE_BUTTON


def qt_mouse_button_to_name(button) -> str | None:
    """Bouton Qt (QMouseEvent.button()) -> identifiant "mouse_*"."""
    return _QT_MOUSE_BUTTON_NAMES.get(button)


def pynput_mouse_button_to_name(button) -> str | None:
    """Équivalent de qt_mouse_button_to_name pour un bouton pynput
    (mouse.Button), pour la reconnaissance dans les écouteurs globaux."""
    return _PYNPUT_MOUSE_BUTTON_NAMES.get(button)


def name_to_pynput_mouse_button(name: str):
    """Sens inverse : identifiant "mouse_*" -> mouse.Button pynput, pour
    simuler un clic (voir pixel_watcher.py). None si `name` n'est pas un
    identifiant de bouton de souris connu."""
    return _NAME_TO_PYNPUT_MOUSE_BUTTON.get(name)
