"""
Overlay "curseur en jeu" pour Roblox : une fenêtre Qt réelle à canal alpha
par pixel (WA_TranslucentBackground + compositing DWM), qui suit la souris
et affiche l'image choisie par-dessus le jeu pendant que le vrai curseur
Windows est masqué.

Repris du principe de RobloxCursorFollow / PaintLayeredBitmap dans
"Global Macro v2.ahk", mais SANS la technique color-key (WinSetTransColor)
qui provoquait un halo visible sur les bords semi-transparents de l'image :
Qt peint cette fenêtre via une vraie couche alpha par pixel (la même
mécanique qu'UpdateLayeredWindow + AC_SRC_ALPHA côté AHK une fois corrigé),
donc les bords anti-aliasés se fondent proprement sans liseré parasite.

Fenêtre "click-through" (WindowTransparentForInput) : elle ne doit jamais
intercepter les clics destinés au jeu, seulement s'afficher par-dessus.
"""
from PyQt6.QtCore import Qt, QPoint, QTimer
from PyQt6.QtGui import QCursor, QPainter, QPixmap
from PyQt6.QtWidgets import QWidget

_FOLLOW_INTERVAL_MS = 15  # ~66Hz, identique au SetTimer(RobloxCursorFollow, 15) de l'AHK


class RobloxCursorOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self._pixmap = QPixmap()
        self._follow_timer = QTimer(self)
        self._follow_timer.setInterval(_FOLLOW_INTERVAL_MS)
        self._follow_timer.timeout.connect(self._follow_mouse)

    def set_image(self, image) -> None:
        self._pixmap = QPixmap.fromImage(image)
        self.resize(self._pixmap.size())
        self.update()

    def start_following(self) -> None:
        self._follow_mouse()
        self.show()
        self._follow_timer.start()

    def stop_following(self) -> None:
        self._follow_timer.stop()
        self.hide()

    def _follow_mouse(self) -> None:
        pos = QCursor.pos()
        half = QPoint(self._pixmap.width() // 2, self._pixmap.height() // 2)
        self.move(pos - half)

    def paintEvent(self, event) -> None:
        if self._pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(0, 0, self._pixmap)
