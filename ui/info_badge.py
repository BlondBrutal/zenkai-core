"""
Petit cercle "?" qui affiche un texte explicatif dans une bulle discrète au
survol. Remplace le pattern "texte descriptif dupliqué + emoji" utilisé dans
les premières pages du scaffold (voir page_fastflags.py, page_settings.py) :
une seule source du texte (la bulle), pas d'emoji Unicode.

La bulle n'utilise PAS QToolTip natif : son délai (~700ms), sa position
(pile sous le curseur) et son fond opaque grisâtre ne sont pas configurables
proprement widget par widget. On affiche donc nous-mêmes un petit popup
(fond réellement transparent, seule la puce de texte a un fond discret),
avec un délai court et décalé en diagonale du curseur.
"""
from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtGui import QColor, QCursor, QPainter, QPen
from PyQt6.QtWidgets import QLabel, QWidget

from ui.status_colors import STATUS_OK

_SIZE = 20
_SHOW_DELAY_MS = 150
_CURSOR_OFFSET_X = 8
_CURSOR_OFFSET_Y = 8
_MAX_BUBBLE_WIDTH = 640


class _TooltipBubble(QWidget):
    """Popup partagé (un seul à la fois) : fond de fenêtre réellement
    transparent, seule la puce de texte a un fond discret semi-transparent."""

    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self._label = QLabel(self)
        self._label.setWordWrap(True)
        self._label.setStyleSheet(
            "background-color: rgba(30, 30, 36, 200); color: #C7CBD3; "
            "border-radius: 5px; padding: 4px 8px; font-size: 12px;"
        )

    def show_at(self, cursor_pos: QPoint, text: str) -> None:
        self._label.setText(text)

        # Assez large pour tenir sur une seule ligne quand c'est possible :
        # une largeur fixe trop étroite (l'ancienne limite de 280px) forçait
        # un retour à la ligne systématique même pour des phrases courtes,
        # rendu en paragraphe compact plutôt qu'en bulle horizontale.
        padding = 20  # marge du style (4px 8px de chaque côté + un peu d'air)
        text_width = self._label.fontMetrics().horizontalAdvance(text) + padding
        self._label.setFixedWidth(min(_MAX_BUBBLE_WIDTH, text_width))
        self._label.adjustSize()
        self.resize(self._label.size())

        # En diagonale en haut à droite du curseur : à droite (+x), et assez
        # haut pour que le bas de la bulle reste au-dessus du curseur (-y de
        # sa propre hauteur + la marge), jamais en dessous.
        x = cursor_pos.x() + _CURSOR_OFFSET_X
        y = cursor_pos.y() - _CURSOR_OFFSET_Y - self.height()
        self.move(x, y)
        self.show()


_bubble: _TooltipBubble | None = None


def _shared_bubble() -> _TooltipBubble:
    global _bubble
    if _bubble is None:
        _bubble = _TooltipBubble()
    return _bubble


class InfoBadge(QWidget):
    def __init__(self, tooltip_text: str, size: int = _SIZE, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._tooltip_text = tooltip_text
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._color = QColor(STATUS_OK)

        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.setInterval(_SHOW_DELAY_MS)
        self._show_timer.timeout.connect(self._show_bubble)

    def enterEvent(self, event) -> None:
        self._show_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._show_timer.stop()
        _shared_bubble().hide()
        super().leaveEvent(event)

    def hideEvent(self, event) -> None:
        self._show_timer.stop()
        _shared_bubble().hide()
        super().hideEvent(event)

    def _show_bubble(self) -> None:
        _shared_bubble().show_at(QCursor.pos(), self._tooltip_text)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        margin = max(1.0, self.width() * 0.075)
        circle_rect = rect.toRectF().adjusted(margin, margin, -margin, -margin)

        painter.setPen(QPen(self._color, max(1.0, self.width() * 0.075)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(circle_rect)

        painter.setPen(self._color)
        font = painter.font()
        font.setPixelSize(max(8, round(self.width() * 0.6)))
        font.setWeight(font.Weight.Bold)
        painter.setFont(font)
        painter.drawText(circle_rect, Qt.AlignmentFlag.AlignCenter, "?")
