"""
Icône poubelle vectorielle (peinte à la main, comme InfoBadge/AnimatedButton
— jamais d'emoji dans ce projet), pour "Supprimer l'emplacement" : remplace
l'ancien gros bouton texte séparé par une icône compacte directement à côté
du titre de l'emplacement, plutôt qu'une rangée entière dédiée à cette seule
action destructive.
"""
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from ui.status_colors import STATUS_CRITICAL

_SIZE = 20


class TrashIconButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(_SIZE, _SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hovered = False

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        color = QColor(STATUS_CRITICAL)
        if self._hovered:
            color = color.lighter(130)

        w, h = self.width(), self.height()
        pen = QPen(color, max(1.2, w * 0.09))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # Couvercle : ligne horizontale + petite poignée centrée dessus.
        lid_y = h * 0.30
        painter.drawLine(QPointF(w * 0.12, lid_y), QPointF(w * 0.88, lid_y))
        handle_rect = QRectF(w * 0.38, h * 0.10, w * 0.24, h * 0.16)
        painter.drawRoundedRect(handle_rect, w * 0.03, w * 0.03)

        # Corps : rectangle aux deux coins bas arrondis (chemin explicite,
        # pas de drawRoundedRect classique pour garder les coins HAUTS carrés
        # — seul le bas d'une poubelle est arrondi).
        left = w * 0.22
        right = w * 0.78
        top = lid_y
        bottom = h * 0.88
        corner = w * 0.08
        path = QPainterPath()
        path.moveTo(left, top)
        path.lineTo(left, bottom - corner)
        path.quadTo(left, bottom, left + corner, bottom)
        path.lineTo(right - corner, bottom)
        path.quadTo(right, bottom, right, bottom - corner)
        path.lineTo(right, top)
        painter.drawPath(path)

        # Trois côtes verticales à l'intérieur du corps.
        rib_top = top + h * 0.12
        rib_bottom = bottom - h * 0.10
        for fx in (0.36, 0.5, 0.64):
            painter.drawLine(QPointF(w * fx, rib_top), QPointF(w * fx, rib_bottom))
