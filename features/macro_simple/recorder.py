"""
Enregistrement en temps réel d'une séquence d'actions clavier/souris, pour
Macro Simple : capture globale (pynput, même principe que
features/macro_pixel/key_swap_listener.py) des appuis clavier et clics
souris pendant que l'enregistrement est actif, avec pour chaque action sa
durée de maintien (keydown -> keyup) et le délai écoulé avant l'action
suivante (keyup -> prochain keydown) — ce délai est donc assigné à l'étape
PRÉCÉDENTE une fois la nouvelle action détectée, pas à la nouvelle elle-même.

Deux façons d'arrêter l'enregistrement sans jamais enregistrer l'action qui
sert à l'arrêter :
- la touche Échap, jamais capturée comme étape (réservée, même convention
  que KeyCaptureWidget qui l'utilise déjà pour annuler une capture) ;
- un clic sur le bouton "Arrêter l'enregistrement" de l'UI elle-même : tout
  clic dans le rectangle écran de la fenêtre de l'app (capturé au démarrage
  de l'enregistrement) est ignoré, pour ne pas polluer la séquence avec ce
  clic d'interface.

Les répétitions automatiques de l'OS quand une touche/bouton reste enfoncé
sont ignorées (une seule étape par appui réel), via un dictionnaire des
actions actuellement "en cours" (pressées mais pas encore relâchées).
"""
import time

from PyQt6.QtCore import QObject, QRect, pyqtSignal

from pynput import keyboard as pynput_keyboard
from pynput import mouse as pynput_mouse

from features.macro_pixel.key_names import pynput_key_to_pydirectinput
from features.macro_simple.macro_simple import ACTION_KEY, ACTION_MOUSE, MacroStep

_MOUSE_BUTTON_NAMES = {
    pynput_mouse.Button.left: "left",
    pynput_mouse.Button.right: "right",
    pynput_mouse.Button.middle: "middle",
    pynput_mouse.Button.x1: "x1",
    pynput_mouse.Button.x2: "x2",
}


class MacroRecorder(QObject):
    """`stopped_by_escape` est émis quand Échap est détectée pendant
    l'enregistrement : l'UI doit encore appeler stop() elle-même (ce signal
    ne fait qu'informer, il n'arrête rien tout seul), pour rester le seul
    point qui met à jour l'état visuel du bouton d'enregistrement.

    `step_recorded`/`step_delay_updated` permettent à l'UI d'afficher chaque
    ligne au fur et à mesure de l'enregistrement plutôt qu'attendre stop() :
    émis depuis les threads d'écoute pynput (jamais le thread GUI), comme
    stopped_by_escape déjà — Qt met en file d'attente la livraison vers le
    thread GUI automatiquement (connexion en file d'attente entre threads),
    aucune synchronisation manuelle nécessaire côté appelant."""

    stopped_by_escape = pyqtSignal()
    step_recorded = pyqtSignal(object)  # MacroStep tout juste finalisé (delay_after_ms encore à 0)
    step_delay_updated = pyqtSignal(int, int)  # (index dans la séquence, delay_after_ms corrigé)

    def __init__(self, exclude_rect: QRect | None = None, parent=None):
        super().__init__(parent)
        self._exclude_rect = exclude_rect
        self._kb_listener: pynput_keyboard.Listener | None = None
        self._mouse_listener: pynput_mouse.Listener | None = None
        self._pending: dict[tuple, float] = {}
        self._steps: list[MacroStep] = []
        self._last_release_time: float | None = None
        self._recording = False

    def start(self) -> None:
        self._steps = []
        self._pending = {}
        self._last_release_time = None
        self._recording = True
        self._kb_listener = pynput_keyboard.Listener(on_press=self._on_key_press, on_release=self._on_key_release)
        self._mouse_listener = pynput_mouse.Listener(on_click=self._on_click)
        self._kb_listener.start()
        self._mouse_listener.start()

    def stop(self) -> list[MacroStep]:
        """Arrête les écouteurs et retourne la séquence capturée. Attend la
        fin réelle des threads pynput (join) avant de retourner, pour ne
        jamais lire `_steps` alors qu'un callback est encore en vol."""
        self._recording = False
        if self._kb_listener is not None:
            self._kb_listener.stop()
            self._kb_listener.join()
            self._kb_listener = None
        if self._mouse_listener is not None:
            self._mouse_listener.stop()
            self._mouse_listener.join()
            self._mouse_listener = None
        return self._steps

    # ------------------------------------------------------------------
    def _mark_gap_before_new_action(self, press_time: float) -> None:
        if self._steps and self._last_release_time is not None:
            delay_ms = max(0, round((press_time - self._last_release_time) * 1000))
            index = len(self._steps) - 1
            self._steps[index].delay_after_ms = delay_ms
            self._last_release_time = None
            self.step_delay_updated.emit(index, delay_ms)

    def _finalize_step(self, action: str, value: str, x: int, y: int, press_time: float) -> None:
        release_time = time.perf_counter()
        hold_ms = max(0, round((release_time - press_time) * 1000))
        step = MacroStep(action=action, value=value, x=x, y=y, hold_ms=hold_ms, delay_after_ms=0)
        self._steps.append(step)
        self._last_release_time = release_time
        self.step_recorded.emit(step)

    # ------------------------------------------------------------------
    def _on_key_press(self, key) -> None:
        if not self._recording:
            return
        name = pynput_key_to_pydirectinput(key)
        if name is None:
            return
        if name == "esc":
            self.stopped_by_escape.emit()
            return

        token = (ACTION_KEY, name)
        if token in self._pending:
            return  # répétition auto OS d'une touche maintenue : ignorée
        press_time = time.perf_counter()
        self._mark_gap_before_new_action(press_time)
        self._pending[token] = press_time

    def _on_key_release(self, key) -> None:
        if not self._recording:
            return
        name = pynput_key_to_pydirectinput(key)
        if name is None or name == "esc":
            return
        token = (ACTION_KEY, name)
        press_time = self._pending.pop(token, None)
        if press_time is None:
            return
        self._finalize_step(ACTION_KEY, name, 0, 0, press_time)

    def _on_click(self, x, y, button, pressed) -> None:
        if not self._recording:
            return
        if self._exclude_rect is not None and self._exclude_rect.contains(x, y):
            return
        name = _MOUSE_BUTTON_NAMES.get(button)
        if name is None:
            return

        token = (ACTION_MOUSE, name)
        if pressed:
            if token in self._pending:
                return
            press_time = time.perf_counter()
            self._mark_gap_before_new_action(press_time)
            self._pending[token] = press_time
        else:
            press_time = self._pending.pop(token, None)
            if press_time is None:
                return
            self._finalize_step(ACTION_MOUSE, name, x, y, press_time)
