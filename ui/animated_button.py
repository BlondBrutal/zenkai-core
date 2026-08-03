"""
Bouton avec un fondu de couleur animé au survol/clic — les Qt Style Sheets
ne supportent pas de vraies transitions, donc on peint nous-mêmes et on
anime la couleur via QPropertyAnimation.

Peint entièrement nous-mêmes (pas de classe QSS type "primaryButton") : un
QPushButton stylé par sélecteur de classe QSS ne rend pas toujours son
background-color une fois ajouté dynamiquement à une page déjà affichée
(bug constaté et contourné plusieurs fois dans ce projet) — peindre nous-
mêmes élimine complètement le risque.
"""
from PyQt6.QtCore import QRectF, QSize, Qt, QPropertyAnimation, pyqtProperty
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QPushButton

from ui.status_colors import STATUS_CRITICAL, STATUS_NEUTRAL, STATUS_OK


class AnimatedButton(QPushButton):
    def __init__(self, text: str, variant: str = "primary", parent=None, text_color: str | None = None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(42)
        self._variant = variant

        if variant == "primary":
            self._base = QColor(STATUS_OK)
            self._hover = QColor("#1BDAB3")
            self._pressed = QColor("#129076")
            self._text_color = QColor("#0E1C19")
        elif variant == "danger":
            # Même contour gris neutre que "neutral" (pas de rouge sur le
            # contour) : seul le texte reste rouge pour signaler une action
            # destructive (supprimer un emplacement), sans faire ressortir
            # le bouton du reste de l'interface au repos.
            self._base = QColor(155, 161, 171, 0)
            self._hover = QColor(155, 161, 171, 24)
            self._pressed = QColor(155, 161, 171, 45)
            self._text_color = QColor(STATUS_CRITICAL)
        elif variant == "neutral":
            # Contour gris discret (jamais vert), identique à celui de
            # KeyCaptureWidget/.neutralButton (#33333C dans theme.qss) — même
            # bordure partout, seul le texte turquoise distingue le bouton.
            self._base = QColor(155, 161, 171, 0)
            self._hover = QColor(155, 161, 171, 24)
            self._pressed = QColor(155, 161, 171, 45)
            self._text_color = QColor(STATUS_OK)
        else:
            self._base = QColor(23, 184, 151, 0)
            self._hover = QColor(23, 184, 151, 32)
            self._pressed = QColor(23, 184, 151, 60)
            self._text_color = QColor(STATUS_OK)

        if text_color is not None:
            self._text_color = QColor(text_color)

        self._bg_color = QColor(self._base)
        self._animation = QPropertyAnimation(self, b"bgColor")

    def _get_bg(self) -> QColor:
        return self._bg_color

    def _set_bg(self, color: QColor) -> None:
        self._bg_color = color
        self.update()

    bgColor = pyqtProperty(QColor, fget=_get_bg, fset=_set_bg)

    def sizeHint(self) -> QSize:
        text_width = self.fontMetrics().horizontalAdvance(self.text())
        return QSize(text_width + 56, 42)

    def enterEvent(self, event) -> None:
        self._animate_to(self._hover, 150)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate_to(self._base, 150)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        self._animate_to(self._pressed, 80)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        target = self._hover if self.rect().contains(event.pos()) else self._base
        self._animate_to(target, 120)
        super().mouseReleaseEvent(event)

    def _animate_to(self, color: QColor, duration: int) -> None:
        self._animation.stop()
        self._animation.setDuration(duration)
        self._animation.setStartValue(self._bg_color)
        self._animation.setEndValue(color)
        self._animation.start()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        # État désactivé peint nous-mêmes : QPushButton grise le texte via
        # QPalette par défaut, mais comme tout ici est peint à la main
        # (voir docstring du module), rien ne grise automatiquement sans ça.
        if not self.isEnabled():
            painter.setBrush(QColor(23, 24, 28))
            painter.drawRoundedRect(rect, 10, 10)
            painter.setPen(QPen(QColor(STATUS_NEUTRAL), 1.3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, 10, 10)
            painter.setPen(QColor(STATUS_NEUTRAL))
            painter.setFont(QFont("Segoe UI Variable Text", 10, QFont.Weight.DemiBold))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())
            return

        painter.setBrush(self._bg_color)
        painter.drawRoundedRect(rect, 10, 10)

        if self._variant in ("secondary", "danger", "neutral"):
            if self._variant in ("neutral", "danger"):
                outline_color = QColor("#33333C")
            else:
                outline_color = QColor(STATUS_OK)
            painter.setPen(QPen(outline_color, 1.3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, 10, 10)

        painter.setPen(self._text_color)
        painter.setFont(QFont("Segoe UI Variable Text", 10, QFont.Weight.DemiBold))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())
