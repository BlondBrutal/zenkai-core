"""
Petit panneau flottant (toujours au premier plan, hors-cadre) affichant en
continu la position physique actuelle du curseur — sert à repérer les
coordonnées X/Y à saisir à la main dans le tableau de Macro Simple (ex. viser
un point précis dans un jeu, lire ses coordonnées ici, les retaper dans le
tableau).

Volontairement PAS un overlay plein écran façon PixelPickerOverlay : celui-ci
ne doit jamais intercepter les clics ailleurs sur l'écran (le jeu/l'app visée
doit rester utilisable normalement pendant qu'on lit les coordonnées) — juste
un petit panneau dans un coin, purement passif.

F6 ferme le panneau à tout moment, MÊME si une autre fenêtre (le jeu) a le
focus : capturé globalement via pynput (comme ActionCaptureWidget/
KeyCaptureWidget), pas juste un raccourci clavier Qt local.
"""
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from pynput import keyboard as pynput_keyboard

from core.i18n import t
from ui.pixel_picker_overlay import logical_to_physical
from ui.status_colors import STATUS_OK

_REFRESH_MS = 30
_MARGIN_FROM_SCREEN_EDGE = 24


class _CloseButton(QLabel):
    """Petit "x" cliquable (pas un QPushButton : un simple label suffit,
    pas besoin du style/animation d'AnimatedButton pour ce bouton unique)."""

    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("✕", parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"color: {STATUS_OK}; font-size: 13px; font-weight: 700;")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class MouseCoordsOverlay(QWidget):
    """Un seul point d'entrée : construire puis `show()`. Se ferme (et se
    détruit) tout seul sur F6, clic sur le "x", ou `close()` externe."""

    closed = pyqtSignal()
    # Émis depuis le thread du callback pynput (voir docstring du module) :
    # jamais de manipulation directe de widget dedans, seulement `emit()`.
    _f6_pressed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFixedSize(190, 76)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(6)
        title = QLabel(t("page.macro.simple.coords_overlay_title"))
        title.setStyleSheet(f"color: {STATUS_OK}; font-size: 11px; font-weight: 700;")
        header.addWidget(title)
        header.addStretch(1)
        close_btn = _CloseButton()
        close_btn.clicked.connect(self.close)
        header.addWidget(close_btn)
        layout.addLayout(header)

        self._coords_label = QLabel("X: 0    Y: 0")
        self._coords_label.setStyleSheet("color: #E7E9EE; font-size: 15px; font-weight: 700;")
        layout.addWidget(self._coords_label)

        hint = QLabel(t("page.macro.simple.coords_overlay_hint"))
        hint.setStyleSheet("color: #9BA1AB; font-size: 10px;")
        layout.addWidget(hint)

        self._place_top_right()

        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(self._refresh_coords)
        self._timer.start()
        self._refresh_coords()

        self._f6_pressed.connect(self.close)
        self._kb_listener = pynput_keyboard.Listener(on_press=self._on_key_press)
        self._kb_listener.start()

    def _place_top_right(self) -> None:
        screen = QApplication.primaryScreen()
        avail = screen.availableGeometry()
        self.move(
            avail.right() - self.width() - _MARGIN_FROM_SCREEN_EDGE,
            avail.top() + _MARGIN_FROM_SCREEN_EDGE,
        )

    def _refresh_coords(self) -> None:
        px, py = logical_to_physical(QCursor.pos())
        self._coords_label.setText(f"X: {px}    Y: {py}")

    def _on_key_press(self, key) -> None:
        if key == pynput_keyboard.Key.f6:
            self._f6_pressed.emit()

    def closeEvent(self, event) -> None:
        self._timer.stop()
        if self._kb_listener is not None:
            self._kb_listener.stop()
            self._kb_listener = None
        self.closed.emit()
        super().closeEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(20, 20, 24, 235))
        painter.drawRoundedRect(rect, 10, 10)
        painter.setPen(QPen(QColor("#33333C"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 10, 10)
