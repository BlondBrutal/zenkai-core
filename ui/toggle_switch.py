"""
Interrupteur ON/OFF animé, partagé entre les pages (monitoring en direct sur
Performance, kill switch macros sur Macro, ...). Piste + bouton qui glisse,
pas une case à cocher standard.
"""
from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QWidget

from ui.status_colors import STATUS_OK


def _lerp_color(start: QColor, end: QColor, t: float) -> QColor:
    return QColor(
        round(start.red() + (end.red() - start.red()) * t),
        round(start.green() + (end.green() - start.green()) * t),
        round(start.blue() + (end.blue() - start.blue()) * t),
    )


class ToggleSwitch(QWidget):
    toggled = pyqtSignal(bool)

    _TRACK_OFF = QColor("#33333C")
    _TRACK_ON = QColor(STATUS_OK)
    _KNOB_COLOR = QColor("#E7E9EE")

    def __init__(self, checked: bool = True, parent=None):
        super().__init__(parent)
        self.setFixedSize(44, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._checked = checked
        self._position = 1.0 if checked else 0.0

        self._animation = QPropertyAnimation(self, b"position")
        self._animation.setDuration(180)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _get_position(self) -> float:
        return self._position

    def _set_position(self, value: float) -> None:
        self._position = value
        self.update()

    position = pyqtProperty(float, fget=_get_position, fset=_set_position)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool, animate: bool = True) -> None:
        self._checked = checked
        target = 1.0 if checked else 0.0
        # Toujours arrêter une animation en cours avant d'appliquer le nouvel
        # état : sinon un setChecked(..., animate=False) qui suit de près un
        # premier clic (ex. reverti par une validation) se fait écraser plus
        # tard par les frames de l'ancienne animation encore en vol, et le
        # bouton finit visuellement dans le mauvais état malgré isChecked()
        # correct.
        self._animation.stop()
        if animate:
            self._animation.setStartValue(self._position)
            self._animation.setEndValue(target)
            self._animation.start()
        else:
            self._position = target
            self.update()

    def mousePressEvent(self, event) -> None:
        self.setChecked(not self._checked)
        self.toggled.emit(self._checked)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        track_color = _lerp_color(self._TRACK_OFF, self._TRACK_ON, self._position)
        track_rect = QRectF(0, 0, self.width(), self.height())
        painter.setBrush(track_color)
        painter.drawRoundedRect(track_rect, track_rect.height() / 2, track_rect.height() / 2)

        knob_diameter = self.height() - 4
        knob_x = 2 + self._position * (self.width() - knob_diameter - 4)
        painter.setBrush(self._KNOB_COLOR)
        painter.drawEllipse(QRectF(knob_x, 2, knob_diameter, knob_diameter))
