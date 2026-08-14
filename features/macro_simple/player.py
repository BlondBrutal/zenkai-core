"""
Rejeu d'une séquence de MacroStep enregistrée, dans un thread séparé (jamais
dans le thread UI) — même structure que
features/macro_pixel/pixel_watcher.py : boucle interruptible via `_running`,
pauses découpées en petits sleeps pour réagir vite à stop() plutôt qu'un
time.sleep() unique bloquant sur toute la durée d'une étape.

Envoie les touches/clics via `pydirectinput`, seule bibliothèque du projet
utilisée pour ENVOYER des entrées (pynput ne sert qu'à en RECEVOIR, voir
hotkey_listener.py/ui/action_capture_widget.py).
"""
import logging
import time

from PyQt6.QtCore import QThread, pyqtSignal

import pydirectinput
from pynput import mouse as pynput_mouse
from pynput.mouse import Controller as MouseController

from features.macro_simple.macro_simple import ACTION_KEY, MacroStep

logger = logging.getLogger("zenkaiontop.macro_simple")

_SLEEP_CHUNK_S = 0.02  # découpe les pauses pour rester réactif à stop()

# pydirectinput.mouseDown/mouseUp (utilisé avant ce correctif) ne connaît que
# 'left'/'right'/'middle' : incapable de rejouer un clic sur un bouton latéral
# (x1/x2), désormais capturable (voir ui/action_capture_widget.py). pynput
# couvre les 5 boutons réels de façon uniforme, d'où le passage à
# mouse.Controller pour TOUTE action souris ci-dessous (le clavier reste sur
# pydirectinput, inchangé).
_MOUSE_BUTTONS = {
    "left": pynput_mouse.Button.left,
    "right": pynput_mouse.Button.right,
    "middle": pynput_mouse.Button.middle,
    "x1": pynput_mouse.Button.x1,
    "x2": pynput_mouse.Button.x2,
}


class MacroPlayerThread(QThread):
    step_started = pyqtSignal(int)  # index de l'étape en cours (surligne la ligne dans le tableau)
    finished_playback = pyqtSignal()  # toujours émis en sortie de run(), arrêt anticipé ou fin naturelle
    error = pyqtSignal(str)

    def __init__(
        self, steps: list[MacroStep], repeat_count: int, infinite: bool,
        loop_delay_ms: int = 0, parent=None,
    ):
        super().__init__(parent)
        self._steps = list(steps)
        self._repeat_count = max(1, repeat_count)
        self._infinite = infinite
        # Délai entre deux passages COMPLETS de la séquence (pas entre deux
        # étapes — voir MacroStep.delay_after_ms pour ça), utile seulement en
        # Hold/Toggle (mode Répétition n'expose pas ce champ, voir
        # macro_simple_tab.py) pour espacer les répétitions tant que la
        # macro tourne.
        self._loop_delay_ms = max(0, loop_delay_ms)
        self._running = False
        pydirectinput.PAUSE = 0  # jamais de délai imposé par pydirectinput lui-même
        self._mouse = MouseController()

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        self._running = True
        try:
            count = 0
            while self._running and (self._infinite or count < self._repeat_count):
                for index, step in enumerate(self._steps):
                    if not self._running:
                        break
                    self.step_started.emit(index)
                    self._play_step(step)
                count += 1
                will_loop_again = self._running and (self._infinite or count < self._repeat_count)
                if will_loop_again and self._loop_delay_ms > 0:
                    self._sleep_ms(self._loop_delay_ms)
        finally:
            self.finished_playback.emit()

    def _play_step(self, step: MacroStep) -> None:
        try:
            if step.action == ACTION_KEY:
                pydirectinput.keyDown(step.value)
                self._sleep_ms(step.hold_ms)
                pydirectinput.keyUp(step.value)
            else:
                button = _MOUSE_BUTTONS[step.value]
                if not step.use_current_position:
                    self._mouse.position = (step.x, step.y)
                self._mouse.press(button)
                self._sleep_ms(step.hold_ms)
                self._mouse.release(button)
        except Exception as exc:
            logger.error("Étape de macro Simple impossible à rejouer (%s) : %s", step, exc)
            self.error.emit(str(exc))
            return
        self._sleep_ms(step.delay_after_ms)

    def _sleep_ms(self, ms: int) -> None:
        end = time.perf_counter() + max(0, ms) / 1000
        while self._running and time.perf_counter() < end:
            time.sleep(min(_SLEEP_CHUNK_S, max(0.0, end - time.perf_counter())))
