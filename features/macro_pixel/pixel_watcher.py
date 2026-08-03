"""
Boucle de détection d'une macro Pixel : surveille un pixel dans un thread
séparé (jamais dans le thread UI), au polling le plus rapide possible sans
saturer un cœur CPU. Reprend le comportement de PixelWatchLoop dans
"Global Macro v2.ahk" (page TP) :
- lecture du pixel via une capture `mss` réutilisée sur toute la durée du
  watcher (PersistentPixelReader) plutôt qu'une nouvelle capture à chaque
  itération — un `GetPixel` Win32 direct (DC caché, comme PixelGetColor
  dans l'AHK d'origine) a été essayé mais rejeté : vérifié contre une
  couleur fixe connue, il renvoyait des valeurs incohérentes d'un appel à
  l'autre sur cette machine (voir features/macro_pixel/color_capture.py) ;
- correspondance de couleur exacte (pas de tolérance : fonctionnalité
  retirée sur demande) ;
- déclenchement sur front montant (la touche part une fois quand la couleur
  se met à correspondre, puis plus rien tant qu'elle continue de
  correspondre) — c'est ce front montant qui sert d'anti-spam par défaut ;
- "temps de recharge" toujours actif (cooldown_seconds, 0 = pas de délai),
  qui reprend TP_COOLDOWN_MS de l'AHK d'origine : si un front montant est
  bloqué par le cooldown, il reste retenté à CHAQUE itération tant que la
  couleur continue de correspondre (pas besoin d'un nouveau front montant
  après expiration du cooldown), exactement comme `cooldownOk`/
  `g_PixelActive` dans PixelWatchLoop.

Fréquence : l'AHK d'origine tourne en boucle quasi ininterrompue (Sleep(-1)
ne fait que céder la main, sans vraie pause). On vise ici un intervalle
cible bien plus court que les ~100Hz d'une première version (voir
_POLL_INTERVAL_S) pour égaler/battre cette réactivité, tout en gardant un
plancher de sommeil non nul (_MIN_SLEEP_S) pour ne jamais transformer la
boucle en busy-spin qui monopoliserait un cœur pour rien.
"""
import logging
import time

from PyQt6.QtCore import QThread, pyqtSignal

import pydirectinput
from pynput.mouse import Controller as MouseController

from features.macro_pixel.color_capture import PersistentPixelReader
from features.macro_pixel.key_names import is_mouse_button_name, name_to_pynput_mouse_button
from features.macro_pixel.pixel_macro import PixelMacroConfig

logger = logging.getLogger("zenkaiontop.macro_pixel")

_POLL_INTERVAL_S = 0.0005  # ~2000Hz cible
_MIN_SLEEP_S = 0.0002  # jamais un vrai busy-spin, même si la lecture est instantanée


class PixelWatcherThread(QThread):
    triggered = pyqtSignal()  # émis à chaque appui de touche déclenché
    error = pyqtSignal(str)  # émis si la capture échoue de façon inattendue

    def __init__(self, macro: PixelMacroConfig, parent=None):
        super().__init__(parent)
        self._macro = macro
        self._running = False
        pydirectinput.PAUSE = 0  # jamais de délai imposé par pydirectinput lui-même
        # Touche de réaction clavier -> pydirectinput (déjà utilisé partout
        # ailleurs) ; bouton de souris -> pynput (pydirectinput ne sait pas
        # cliquer autre chose que gauche/droit/milieu, pas les boutons
        # latéraux x1/x2 qu'on veut aussi pouvoir capturer, voir key_names.py).
        self._mouse = MouseController()

    def stop(self) -> None:
        self._running = False

    def set_key(self, key: str) -> None:
        """Met à jour la touche de réaction à chaud (changement rapide de
        touche) sans avoir à arrêter/relancer le watcher. Simple assignation
        d'attribut, lue par run() à l'itération suivante — sûr sous CPython
        (le GIL protège l'assignation d'une référence)."""
        self._macro.key = key

    def _fire_reaction(self, key: str) -> None:
        if is_mouse_button_name(key):
            button = name_to_pynput_mouse_button(key)
            if button is not None:
                self._mouse.click(button)
            return
        pydirectinput.press(key)

    def run(self) -> None:
        self._running = True
        was_active = False  # équivalent de g_PixelActive dans l'AHK d'origine
        # Négatif : autorise un déclenchement dès le premier front montant,
        # sans attendre un plein cooldown après le lancement du watcher.
        last_trigger_time = -self._macro.cooldown_seconds
        reader = PersistentPixelReader()

        try:
            while self._running:
                loop_start = time.perf_counter()

                try:
                    current_color = reader.read(self._macro.x, self._macro.y)
                    is_matching = current_color == self._macro.target_color
                except Exception as exc:
                    logger.error("Capture de pixel impossible : %s", exc)
                    self.error.emit(str(exc))
                    is_matching = False

                if not is_matching:
                    was_active = False
                elif not was_active:
                    cooldown_ok = (time.perf_counter() - last_trigger_time) >= self._macro.cooldown_seconds
                    if cooldown_ok:
                        was_active = True
                        self._fire_reaction(self._macro.key)
                        last_trigger_time = time.perf_counter()
                        self.triggered.emit()
                    # Sinon : was_active reste False, on retentera à la
                    # prochaine itération tant que ça matche toujours (pas
                    # besoin d'un nouveau front montant), comme dans l'AHK.

                # On soustrait le temps déjà passé dans cette itération pour
                # rester à la bonne fréquence sans dériver.
                elapsed = time.perf_counter() - loop_start
                time.sleep(max(_MIN_SLEEP_S, _POLL_INTERVAL_S - elapsed))
        finally:
            reader.close()
