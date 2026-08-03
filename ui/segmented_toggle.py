"""
Petit sélecteur à segments (2 options ou plus), peint nous-mêmes : pour un
choix exclusif à peu d'options, un toggle façon segmented control tient
mieux dans le thème sombre qu'un QComboBox ou des QRadioButton (rendu natif
clair que le QSS ne couvre pas complètement — vu à plusieurs reprises dans
ce projet). Généralisé à partir du sélecteur de langue FR/EN de la page
Paramètres, réutilisé ici pour le mode de déclenchement des macros Pixel.
"""
from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from ui.status_colors import STATUS_NEUTRAL, STATUS_OK

_HEIGHT = 30
_PADDING = 3
_SEGMENT_H_PADDING = 14


class SegmentedToggle(QWidget):
    valueChanged = pyqtSignal(str)

    def __init__(self, options: list[tuple[str, str]], current: str, parent=None):
        """`options` : liste de (valeur, libellé affiché)."""
        super().__init__(parent)
        self._options = options
        self._current = current
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        font = self.font()
        fm = QFontMetrics(font)
        self._segment_widths = [fm.horizontalAdvance(label) + _SEGMENT_H_PADDING * 2 for _, label in options]
        total_width = sum(self._segment_widths) + _PADDING * 2
        self.setFixedSize(total_width, _HEIGHT)

    def value(self) -> str:
        return self._current

    def set_value(self, value: str) -> None:
        if value != self._current:
            self._current = value
            self.update()

    def _segment_at(self, x: float) -> int:
        cursor = _PADDING
        for i, width in enumerate(self._segment_widths):
            if cursor <= x < cursor + width:
                return i
            cursor += width
        return len(self._segment_widths) - 1

    def mousePressEvent(self, event) -> None:
        index = self._segment_at(event.position().x())
        value = self._options[index][0]
        if value != self._current:
            self._current = value
            self.update()
            self.valueChanged.emit(value)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        outer = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor("#33333C"), 1))
        painter.setBrush(QColor("#202027"))
        painter.drawRoundedRect(outer, outer.height() / 2, outer.height() / 2)

        cursor = _PADDING
        for (value, label), width in zip(self._options, self._segment_widths):
            seg_rect = QRectF(cursor, _PADDING, width, _HEIGHT - 2 * _PADDING)
            active = value == self._current
            painter.setPen(Qt.PenStyle.NoPen)
            if active:
                painter.setBrush(QColor(STATUS_OK))
                painter.drawRoundedRect(seg_rect, seg_rect.height() / 2, seg_rect.height() / 2)

            painter.setPen(QColor("#0E1C19") if active else QColor(STATUS_NEUTRAL))
            font = painter.font()
            font.setPixelSize(12)
            font.setWeight(font.Weight.DemiBold if active else font.Weight.Medium)
            painter.setFont(font)
            painter.drawText(seg_rect, Qt.AlignmentFlag.AlignCenter, label)

            cursor += width
