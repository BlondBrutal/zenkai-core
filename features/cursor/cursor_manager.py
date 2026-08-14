"""
Coordonne le curseur Windows (système), le curseur en jeu (overlay Roblox
qui suit la souris) et le crosshair (overlay fixe au centre de l'écran) :
application/réinitialisation, persistance de la config (chemin + taille) et
surveillance du premier plan pour activer/désactiver les deux overlays
automatiquement — repris de RobloxCursorWatch/StopRobloxCursorOverlay dans
"Global Macro v2.ahk" : pendant que Roblox est au premier plan, le curseur
système réel est masqué (curseur 1x1 transparent, seulement si un curseur
Roblox est configuré) et remplacé visuellement par l'overlay à canal alpha
qui suit la souris ; en quittant Roblox, le curseur système est restauré
(curseur Windows personnalisé s'il y en a un, sinon le curseur par défaut).
Le crosshair suit ce même déclencheur (premier plan Roblox) mais reste fixe
au centre de l'écran et ne touche jamais au curseur système — un réglage
totalement indépendant du curseur Roblox, chacun pouvant être configuré
seul.
"""
import ctypes
from ctypes import wintypes
import logging
import os
import shutil

import psutil
from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

from core.config import config
from core.paths import get_cursors_dir
from features.cursor import win_cursor
from features.cursor.background_removal import remove_solid_background
from features.cursor.crosshair_overlay import CrosshairOverlay
from features.cursor.cursor_image import DEFAULT_SIZE, load_scaled_image
from features.cursor.roblox_overlay import RobloxCursorOverlay

logger = logging.getLogger("zenkaiontop.cursor")

user32 = ctypes.windll.user32
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD

_WATCH_INTERVAL_MS = 300  # identique à SetTimer(RobloxCursorWatch, 300) dans l'AHK
_ROBLOX_PROCESS_NAMES = {"robloxplayerbeta.exe", "windows10universal.exe"}

_CFG_GENERAL_PATH = "cursor_general_image_path"
_CFG_GENERAL_SIZE = "cursor_general_size"
_CFG_ROBLOX_PATH = "cursor_roblox_image_path"
_CFG_ROBLOX_SIZE = "cursor_roblox_size"
_CFG_CROSSHAIR_PATH = "cursor_crosshair_image_path"
_CFG_CROSSHAIR_SIZE = "cursor_crosshair_size"


def _foreground_process_name() -> str:
    """Nom (minuscules) de l'exécutable au premier plan, ou "" si indisponible."""
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        return psutil.Process(pid.value).name().lower()
    except Exception:
        return ""


def _copy_into_cursors_dir(path: str, stem: str) -> str:
    """Détoure un éventuel fond uni noir/blanc (voir background_removal.py),
    puis enregistre le résultat dans le dossier de données de l'app (même
    principe que la Bibliothèque de macros) : le curseur reste appliqué
    même si le fichier source est ensuite déplacé ou supprimé. Toujours
    réencodé en PNG, jamais une copie d'octets brute — seul format de la
    liste supportée qui préserve un canal alpha par pixel, nécessaire dès
    qu'un détourage a pu avoir lieu."""
    dest = os.path.join(get_cursors_dir(), f"{stem}.png")
    image = QImage(path)
    if image.isNull():
        shutil.copyfile(path, dest)  # filet de sécurité si QImage n'a pas pu décoder le fichier
        return dest
    remove_solid_background(image).save(dest, "PNG")
    return dest


class CursorManager(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.general_path = config.get(_CFG_GENERAL_PATH, "") or ""
        self.general_size = int(config.get(_CFG_GENERAL_SIZE, DEFAULT_SIZE) or DEFAULT_SIZE)
        self.roblox_path = config.get(_CFG_ROBLOX_PATH, "") or ""
        self.roblox_size = int(config.get(_CFG_ROBLOX_SIZE, DEFAULT_SIZE) or DEFAULT_SIZE)
        self.crosshair_path = config.get(_CFG_CROSSHAIR_PATH, "") or ""
        self.crosshair_size = int(config.get(_CFG_CROSSHAIR_SIZE, DEFAULT_SIZE) or DEFAULT_SIZE)

        self._overlay: RobloxCursorOverlay | None = None
        self._crosshair_overlay: CrosshairOverlay | None = None
        self._roblox_active = False
        self._system_cursor_hidden = False

        self._watch_timer = QTimer(self)
        self._watch_timer.setInterval(_WATCH_INTERVAL_MS)
        self._watch_timer.timeout.connect(self._watch_tick)

        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

        # Réapplique au démarrage ce qui était configuré lors de la session précédente.
        if self.general_path and os.path.exists(self.general_path):
            self._apply_general_cursor(self.general_path, self.general_size)
        if self.roblox_path and os.path.exists(self.roblox_path):
            self._prepare_roblox_overlay(self.roblox_path, self.roblox_size)
        if self.crosshair_path and os.path.exists(self.crosshair_path):
            self._prepare_crosshair_overlay(self.crosshair_path, self.crosshair_size)
        if self.roblox_path or self.crosshair_path:
            self._watch_timer.start()

    # ------------------------------------------------------------------
    # Curseur Windows (système)
    # ------------------------------------------------------------------
    def apply_general(self, path: str) -> bool:
        image = load_scaled_image(path, self.general_size)
        if image is None:
            return False
        dest = _copy_into_cursors_dir(path, "general")
        if not self._apply_general_cursor(dest, self.general_size):
            return False
        self.general_path = dest
        config.set(_CFG_GENERAL_PATH, dest)
        return True

    def set_general_size(self, size: int) -> None:
        self.general_size = size
        config.set(_CFG_GENERAL_SIZE, size)
        if self.general_path:
            self._apply_general_cursor(self.general_path, size)

    def reset_general(self) -> None:
        self.general_path = ""
        self.general_size = DEFAULT_SIZE
        config.set(_CFG_GENERAL_PATH, "")
        config.set(_CFG_GENERAL_SIZE, DEFAULT_SIZE)
        # Ne touche pas au curseur réel si l'overlay Roblox est actif et
        # masque déjà le curseur système : il serait aussitôt recouvert, et
        # _deactivate_foreground_overlays restaurera le bon état (défaut,
        # puisque general_path est maintenant vide) en sortant de Roblox.
        if not self._roblox_active:
            win_cursor.reset_system_cursors()

    def _apply_general_cursor(self, path: str, size: int) -> bool:
        image = load_scaled_image(path, size)
        if image is None:
            return False
        hicon = win_cursor.build_cursor_hicon(image)
        return win_cursor.apply_system_cursor(hicon)

    # ------------------------------------------------------------------
    # Curseur en jeu (overlay Roblox)
    # ------------------------------------------------------------------
    def apply_roblox(self, path: str) -> bool:
        image = load_scaled_image(path, self.roblox_size)
        if image is None:
            return False
        dest = _copy_into_cursors_dir(path, "roblox")
        self.roblox_path = dest
        config.set(_CFG_ROBLOX_PATH, dest)
        self._prepare_roblox_overlay(dest, self.roblox_size)
        self._watch_timer.start()
        self._watch_tick()
        return True

    def set_roblox_size(self, size: int) -> None:
        self.roblox_size = size
        config.set(_CFG_ROBLOX_SIZE, size)
        if self.roblox_path:
            self._prepare_roblox_overlay(self.roblox_path, size)

    def reset_roblox(self) -> None:
        self.roblox_path = ""
        self.roblox_size = DEFAULT_SIZE
        config.set(_CFG_ROBLOX_PATH, "")
        config.set(_CFG_ROBLOX_SIZE, DEFAULT_SIZE)
        if not self.crosshair_path:
            self._watch_timer.stop()
        if self._overlay is not None:
            self._overlay.stop_following()
            self._overlay.deleteLater()
            self._overlay = None
        # Plus de curseur Roblox configuré : le curseur système ne doit plus
        # jamais être masqué désormais, y compris tout de suite si l'overlay
        # était actif à l'instant de la réinitialisation (_deactivate_
        # foreground_overlays, appelé seulement au prochain changement de
        # premier plan, arriverait trop tard).
        if self._system_cursor_hidden:
            win_cursor.reset_system_cursors()
            self._system_cursor_hidden = False
            if self.general_path:
                self._apply_general_cursor(self.general_path, self.general_size)

    def _prepare_roblox_overlay(self, path: str, size: int) -> None:
        image = load_scaled_image(path, size)
        if image is None:
            return
        if self._overlay is None:
            self._overlay = RobloxCursorOverlay()
        self._overlay.set_image(image)

    # ------------------------------------------------------------------
    # Crosshair (overlay fixe au centre de l'écran, en jeu)
    # ------------------------------------------------------------------
    def apply_crosshair(self, path: str) -> bool:
        image = load_scaled_image(path, self.crosshair_size)
        if image is None:
            return False
        dest = _copy_into_cursors_dir(path, "crosshair")
        self.crosshair_path = dest
        config.set(_CFG_CROSSHAIR_PATH, dest)
        self._prepare_crosshair_overlay(dest, self.crosshair_size)
        self._watch_timer.start()
        self._watch_tick()
        return True

    def set_crosshair_size(self, size: int) -> None:
        self.crosshair_size = size
        config.set(_CFG_CROSSHAIR_SIZE, size)
        if self.crosshair_path:
            self._prepare_crosshair_overlay(self.crosshair_path, size)

    def reset_crosshair(self) -> None:
        self.crosshair_path = ""
        self.crosshair_size = DEFAULT_SIZE
        config.set(_CFG_CROSSHAIR_PATH, "")
        config.set(_CFG_CROSSHAIR_SIZE, DEFAULT_SIZE)
        if not self.roblox_path:
            self._watch_timer.stop()
        if self._crosshair_overlay is not None:
            self._crosshair_overlay.hide_overlay()
            self._crosshair_overlay.deleteLater()
            self._crosshair_overlay = None

    def _prepare_crosshair_overlay(self, path: str, size: int) -> None:
        image = load_scaled_image(path, size)
        if image is None:
            return
        if self._crosshair_overlay is None:
            self._crosshair_overlay = CrosshairOverlay()
        self._crosshair_overlay.set_image(image)

    # ------------------------------------------------------------------
    # Surveillance du premier plan (Roblox) — pilote l'overlay curseur ET
    # l'overlay crosshair, indépendamment l'un de l'autre (chacun peut être
    # configuré seul).
    # ------------------------------------------------------------------
    def _watch_tick(self) -> None:
        if not self.roblox_path and not self.crosshair_path:
            return
        active = _foreground_process_name() in _ROBLOX_PROCESS_NAMES
        if active and not self._roblox_active:
            self._activate_foreground_overlays()
        elif not active and self._roblox_active:
            self._deactivate_foreground_overlays()

    def _activate_foreground_overlays(self) -> None:
        # Le curseur système n'est masqué que si un curseur Roblox est
        # réellement configuré : le crosshair seul n'a aucune raison de
        # cacher le vrai curseur (ce sont deux réglages indépendants).
        if self.roblox_path and not self._system_cursor_hidden:
            hcursor = win_cursor.make_blank_cursor()
            self._system_cursor_hidden = win_cursor.apply_system_cursor(hcursor)
        if self._overlay is not None:
            self._overlay.start_following()
        if self._crosshair_overlay is not None:
            self._crosshair_overlay.show_overlay()
        self._roblox_active = True

    def _deactivate_foreground_overlays(self) -> None:
        if self._overlay is not None:
            self._overlay.stop_following()
        if self._crosshair_overlay is not None:
            self._crosshair_overlay.hide_overlay()
        self._roblox_active = False
        if self._system_cursor_hidden:
            win_cursor.reset_system_cursors()
            self._system_cursor_hidden = False
            if self.general_path:
                self._apply_general_cursor(self.general_path, self.general_size)

    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        self._watch_timer.stop()
        self._deactivate_foreground_overlays()
        if self.general_path or self._system_cursor_hidden:
            win_cursor.reset_system_cursors()


_cursor_manager: CursorManager | None = None


def get_cursor_manager() -> CursorManager:
    """Instance unique, créée à la demande (nécessite une QApplication déjà
    existante, comme les autres singletons Qt du projet)."""
    global _cursor_manager
    if _cursor_manager is None:
        _cursor_manager = CursorManager()
    return _cursor_manager
