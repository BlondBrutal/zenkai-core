"""
Écoute globale (système, hors fenêtre de l'app) d'une touche/bouton unique,
pour le "changement rapide de touche" repris de ChangementToucheHandler dans
"Global Macro v2.ahk" (page TP) : appuyer sur une touche dédiée échange à la
volée la touche de réaction active avec une seconde touche cible, sans
rouvrir la config. Contrairement à `pydirectinput` (qui sert uniquement à
ENVOYER des touches), il faut ici RECEVOIR un appui même quand Roblox a le
focus — `pynput` fournit ce hook global (déjà une dépendance du projet).

La touche de swap peut être une touche clavier OU un bouton de souris (clic
gauche/droit exclus dès la capture, voir ui/key_capture_widget.py) : deux
écouteurs pynput distincts tournent donc en parallèle, un seul matchant
réellement `_swap_key` selon son type.
"""
from PyQt6.QtCore import QObject, pyqtSignal

from pynput import keyboard as pynput_keyboard
from pynput import mouse as pynput_mouse

from features.macro_pixel.key_names import pynput_key_to_pydirectinput, pynput_mouse_button_to_name


class KeySwapListener(QObject):
    """`triggered` est émis quand la touche de changement est pressée. Les
    callbacks de pynput s'exécutent chacun sur leur propre thread interne :
    on ne touche donc jamais un widget directement dedans, seulement
    `emit()` (Qt met la connexion en file vers le thread GUI automatiquement)."""

    triggered = pyqtSignal()

    def __init__(self, swap_key: str, parent=None):
        super().__init__(parent)
        self._swap_key = swap_key
        self._kb_listener = pynput_keyboard.Listener(on_press=self._on_press)
        self._mouse_listener = pynput_mouse.Listener(on_click=self._on_click)

    def start(self) -> None:
        self._kb_listener.start()
        self._mouse_listener.start()

    def stop(self) -> None:
        self._kb_listener.stop()
        self._mouse_listener.stop()

    def _on_press(self, key) -> None:
        if pynput_key_to_pydirectinput(key) == self._swap_key:
            self.triggered.emit()

    def _on_click(self, x, y, button, pressed) -> None:
        if pressed and pynput_mouse_button_to_name(button) == self._swap_key:
            self.triggered.emit()
