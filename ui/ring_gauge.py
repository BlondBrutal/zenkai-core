"""
Anneau de progression 0-100% avec la valeur affichée au centre, partagé
entre les pages (monitoring en direct sur Performance, score de risque sur
Risque, ...). Transition animée en douceur entre deux valeurs plutôt que
de sauter instantanément.
"""
from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt, pyqtProperty
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from ui.status_colors import STATUS_OK


class RingGauge(QWidget):
    _TRACK_COLOR = QColor("#2A2A32")
    _PEN_WIDTH = 8

    def __init__(self, size: int = 76, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._value = 0.0
        self._color = QColor(STATUS_OK)
        self._show_placeholder = True  # "--" tant qu'aucune valeur n'a été reçue
        self._animation = QPropertyAnimation(self, b"value")
        self._animation.setDuration(500)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _get_value(self) -> float:
        return self._value

    def _set_value(self, value: float) -> None:
        self._value = value
        self.update()

    value = pyqtProperty(float, fget=_get_value, fset=_set_value)

    def set_target(self, value: float, color: str) -> None:
        self._show_placeholder = False
        self._color = QColor(color)
        value = max(0.0, min(100.0, value))
        self._animation.stop()
        self._animation.setStartValue(self._value)
        self._animation.setEndValue(value)
        self._animation.start()

    def set_placeholder(self) -> None:
        self._show_placeholder = True
        self._animation.stop()
        self._value = 0.0
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        margin = self._PEN_WIDTH // 2
        rect = self.rect().adjusted(margin, margin, -margin, -margin)

        painter.setPen(QPen(self._TRACK_COLOR, self._PEN_WIDTH, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(rect, 0, 360 * 16)

        if self._value > 0:
            painter.setPen(QPen(self._color, self._PEN_WIDTH, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            span = -round(self._value / 100 * 360 * 16)
            painter.drawArc(rect, 90 * 16, span)

        painter.setPen(QColor("#E7E9EE"))
        painter.setFont(QFont("Segoe UI", round(self.width() * 0.16), QFont.Weight.Bold))
        text = "--" if self._show_placeholder else f"{round(self._value)}%"
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, text)
