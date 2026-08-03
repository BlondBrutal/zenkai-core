"""
Écoute globale (système, hors fenêtre de l'app) d'une touche de
déclenchement pour Macro Simple, avec deux signaux séparés (appui et
relâchement) — nécessaire pour le mode Hold : la macro doit tourner tant que
la touche reste physiquement enfoncée, pas juste au moment de l'appui.

Tant que cet écouteur tourne (donc tant que la macro est armée, voir
MacroSimpleSlot._on_start_toggle), la touche de déclenchement est aussi
BLOQUÉE au niveau système (voir native_key_blocker.py) : elle ne doit plus
déclencher son action normale/système pendant que la macro est active,
comme le clic gauche/droit reste réservé à l'usage normal de l'interface
côté capture (voir ui/key_capture_widget.py) — ici c'est l'inverse, la
touche choisie doit devenir INUTILISABLE ailleurs tant qu'elle pilote la
macro. Elle redevient libre dès stop() (macro repassée à OFF)."""
from PyQt6.QtCore import QObject, pyqtSignal

from features.macro_simple.native_key_blocker import NativeKeyBlocker


class HotkeyTriggerListener(QObject):
    pressed = pyqtSignal()
    released = pyqtSignal()

    def __init__(self, hotkey: str, parent=None):
        super().__init__(parent)
        self._hotkey = hotkey
        self._is_down = False
        self._blocker = NativeKeyBlocker(hotkey, self._on_native_press, self._on_native_release)

    def start(self) -> None:
        self._blocker.start()

    def stop(self) -> None:
        self._blocker.stop()

    def _on_native_press(self) -> None:
        # Le callback natif ne dédoublonne pas la répétition auto de l'OS
        # (plusieurs "down" tant que la touche reste enfoncée, sans "up"
        # entre deux) : un seul signal "pressed" par appui réel, comme avant.
        if self._is_down:
            return
        self._is_down = True
        self.pressed.emit()

    def _on_native_release(self) -> None:
        self._is_down = False
        self.released.emit()
