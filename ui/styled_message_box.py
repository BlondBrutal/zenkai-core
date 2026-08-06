"""
Boîte de dialogue d'information/avertissement stylée, cohérente avec le
thème sombre de l'app — remplace la QMessageBox.information/warning par
défaut de Windows (fond blanc, icône bleue ronde "i") qui détonnait
complètement avec le reste de l'interface. Icône peinte à la main (cercle +
lettre), même principe que InfoBadge/TrashIconButton : jamais d'emoji dans
ce projet.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from core.i18n import t
from ui.status_colors import STATUS_CRITICAL, STATUS_OK

_BACKGROUND = "#1A1A1F"
_ICON_SIZE = 22


class _StatusIcon(QWidget):
    """Cercle + lettre ("i" ou "!"), coloré selon la variante — remplace
    l'icône bleue ronde par défaut de Windows par quelque chose de cohérent
    avec le reste de l'app (voir InfoBadge, même technique de dessin)."""

    def __init__(self, color: QColor, glyph: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(_ICON_SIZE, _ICON_SIZE)
        self._color = color
        self._glyph = glyph

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        margin = max(1.0, self.width() * 0.06)
        circle_rect = self.rect().toRectF().adjusted(margin, margin, -margin, -margin)

        painter.setPen(QPen(self._color, max(1.0, self.width() * 0.08)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(circle_rect)

        painter.setPen(self._color)
        font = painter.font()
        font.setPixelSize(max(9, round(self.width() * 0.55)))
        font.setWeight(font.Weight.Bold)
        painter.setFont(font)
        painter.drawText(circle_rect, Qt.AlignmentFlag.AlignCenter, self._glyph)


class StyledMessageBox(QDialog):
    def __init__(self, title: str, text: str, variant: str = "info", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(360)
        # Fond aligné sur le reste de l'app : un QDialog nu utilise la
        # palette Qt par défaut (fond blanc), pas le style
        # QMainWindow/#centralWidget de theme.qss.
        self.setStyleSheet(f"background-color: {_BACKGROUND};")

        accent = STATUS_CRITICAL if variant == "warning" else STATUS_OK
        glyph = "!" if variant == "warning" else "i"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        header_row.addWidget(_StatusIcon(QColor(accent), glyph))
        title_label = QLabel(title)
        title_label.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {accent};")
        header_row.addWidget(title_label)
        header_row.addStretch(1)
        layout.addLayout(header_row)

        message_label = QLabel(text)
        message_label.setWordWrap(True)
        message_label.setStyleSheet("font-size: 12.5px; color: #E7E9EE;")
        layout.addWidget(message_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        ok_btn = QPushButton(t("dialog.ok_btn"))
        ok_btn.setProperty("class", "secondaryButton")
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn.clicked.connect(self.accept)
        button_row.addWidget(ok_btn)
        layout.addLayout(button_row)


def show_info(parent, title: str, text: str) -> None:
    StyledMessageBox(title, text, variant="info", parent=parent).exec()


def show_warning(parent, title: str, text: str) -> None:
    StyledMessageBox(title, text, variant="warning", parent=parent).exec()
