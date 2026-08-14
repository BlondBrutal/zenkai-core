"""
Overlay "crosshair" : même principe technique que RobloxCursorOverlay
(fenêtre Qt à canal alpha réel par pixel, toujours au premier plan,
"click-through" — voir roblox_overlay.py pour le détail de chaque réglage),
mais FIXE au centre de l'écran au lieu de suivre la souris.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QWidget


class CrosshairOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Fenêtre sans bordure, toujours au-dessus, qui ne vole jamais le
        # focus et laisse passer tous les clics vers ce qu'il y a en dessous
        # (le jeu) — voir roblox_overlay.py pour le détail de chaque flag.
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

    def set_image(self, image) -> None:
        # Change l'image affichée (ex: après un import ou un changement de
        # taille) et recentre aussitôt, puisque la taille de la fenêtre change.
        self._pixmap = QPixmap.fromImage(image)
        self.resize(self._pixmap.size())
        self._center_on_screen()
        self.update()

    def show_overlay(self) -> None:
        self._center_on_screen()
        self.show()

    def hide_overlay(self) -> None:
        self.hide()

    def _center_on_screen(self) -> None:
        # Écran principal : cohérent avec le fait que Roblox (seul contexte
        # où ce overlay s'affiche, voir cursor_manager.py) tourne quasi
        # toujours sur l'écran principal en usage normal.
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.geometry()
        x = geo.x() + (geo.width() - self._pixmap.width()) // 2
        y = geo.y() + (geo.height() - self._pixmap.height()) // 2
        self.move(x, y)

    def paintEvent(self, event) -> None:
        if self._pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(0, 0, self._pixmap)
