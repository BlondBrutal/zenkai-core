"""
Overlay plein écran (tous les moniteurs) pour sélectionner un pixel : clic
n'importe où pour capturer sa position et sa couleur, Échap pour annuler.

Reste strictement visuel/passif tant qu'aucun clic n'a eu lieu — se ferme de
lui-même après (jamais un second overlay qui traînerait en arrière-plan).
"""
from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFont, QPainter
from PyQt6.QtWidgets import QApplication, QWidget

from core.i18n import t
from features.macro_pixel.color_capture import grab_pixel_color

_TINT_ALPHA = 40


def logical_to_physical(global_pos: QPoint) -> tuple[int, int]:
    """Convertit un point en coordonnées logiques Qt (celles des événements
    souris) vers des coordonnées physiques (celles qu'utilise mss pour
    capturer l'écran) — nécessaire dès qu'un moniteur a une mise à l'échelle
    différente des autres (ex. écran secondaire à 125% ici), sans quoi la
    couleur capturée correspondrait au mauvais pixel sur cet écran-là."""
    screen = QApplication.screenAt(global_pos) or QApplication.primaryScreen()
    origin = screen.geometry().topLeft()
    dpr = screen.devicePixelRatio()
    px = origin.x() + round((global_pos.x() - origin.x()) * dpr)
    py = origin.y() + round((global_pos.y() - origin.y()) * dpr)
    return px, py


class PixelPickerOverlay(QWidget):
    """Un seul point d'entrée : construire, connecter `picked`/`cancelled`,
    puis `show()`. Se ferme (et se détruit) tout seul après un clic ou Échap."""

    picked = pyqtSignal(int, int, tuple)  # (x, y, (r, g, b)) en pixels physiques
    cancelled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

        virtual_desktop = self._virtual_desktop_rect()
        self.setGeometry(virtual_desktop)
        self._mouse_pos = self.mapFromGlobal(QCursor.pos())

    @staticmethod
    def _virtual_desktop_rect() -> QRect:
        rect = QRect()
        for screen in QApplication.screens():
            rect = rect.united(screen.geometry())
        return rect

    def mouseMoveEvent(self, event) -> None:
        self._mouse_pos = event.position().toPoint()
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            # Un clic droit (ou molette/latéral) n'importe où ANNULE, au lieu
            # d'être silencieusement avalé sans rien faire : sans ça, ce clic
            # est bien reçu par cet overlay plein écran/toujours au premier
            # plan mais ne le ferme pas, qui reste donc bloqué à intercepter
            # TOUS les clics suivants n'importe où sur le bureau (y compris
            # dans les champs Pixel X/Y) tant qu'aucun clic gauche ou Échap ne
            # survient — c'est exactement ce qui pouvait faire croire à un
            # widget invisible qui "recouvre" le reste de l'appli.
            self.cancelled.emit()
            self.close()
            return
        global_pos = event.globalPosition().toPoint()

        # On se cache avant de capturer la couleur : notre propre teinte
        # semi-transparente altère sinon le pixel réellement affiché.
        self.hide()
        QApplication.processEvents()
        try:
            px, py = logical_to_physical(global_pos)
            color = grab_pixel_color(px, py)
        except Exception:
            # Si la capture échoue (ex: coordonnées hors d'un moniteur réel),
            # fermer quand même : sans ce filet, l'overlay resterait caché
            # mais jamais détruit/annoncé, un état incohérent à éviter même
            # s'il n'intercepte plus de clics une fois caché.
            self.cancelled.emit()
            self.close()
            return

        self.picked.emit(px, py, color)
        self.close()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.fillRect(self.rect(), QColor(10, 10, 12, _TINT_ALPHA))

        # Pas de curseur custom dessiné ici : on garde uniquement le curseur
        # système (Qt.CursorShape.CrossCursor, natif) pour éviter d'en
        # afficher deux superposés.
        pos = self._mouse_pos

        label = t("page.macro.pixel.picker_hint")
        font = QFont("Segoe UI Variable Text", 11, QFont.Weight.DemiBold)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(label)

        label_x = pos.x() + 24
        label_y = pos.y() - 24
        if label_x + text_width + 16 > self.width():
            label_x = pos.x() - text_width - 40
        if label_y < 10:
            label_y = pos.y() + 34

        bubble_rect = QRect(label_x - 8, label_y - 18, text_width + 16, 26)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(20, 20, 24, 235))
        painter.drawRoundedRect(bubble_rect, 6, 6)
        painter.setPen(QColor("#E7E9EE"))
        painter.drawText(bubble_rect, Qt.AlignmentFlag.AlignCenter, label)
