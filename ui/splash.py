"""
Splash screen affiché pendant l'initialisation de l'app : logo + nom, sans
aucun fond (fenêtre réellement transparente via WA_TranslucentBackground).
Le texte est tracé avec un léger contour sombre pour rester lisible sur
n'importe quel bureau (clair, sombre, fond d'écran chargé, etc.).
"""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QSplashScreen

from core.i18n import t

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")

_OUTLINE_COLOR = QColor(0, 0, 0, 160)
_OUTLINE_WIDTH = 3.0


def _draw_outlined_text(painter: QPainter, rect_x: int, rect_y: int, rect_w: int, rect_h: int,
                         text: str, font: QFont, fill_color: QColor) -> None:
    """Dessine un texte centré avec un léger contour sombre (lisible sur tout fond)."""
    metrics = QFontMetrics(font)
    text_width = metrics.horizontalAdvance(text)
    x = rect_x + (rect_w - text_width) / 2
    y = rect_y + (rect_h + metrics.ascent() - metrics.descent()) / 2

    path = QPainterPath()
    path.addText(x, y, font, text)

    pen = QPen(_OUTLINE_COLOR)
    pen.setWidthF(_OUTLINE_WIDTH)
    painter.strokePath(path, pen)
    painter.fillPath(path, QBrush(fill_color))


def build_splash() -> QSplashScreen:
    logo_path = os.path.join(ASSETS_DIR, "logo", "logo_256.png")

    canvas_w, canvas_h = 380, 240
    canvas = QPixmap(canvas_w, canvas_h)
    canvas.fill(Qt.GlobalColor.transparent)

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    if os.path.exists(logo_path):
        logo = QPixmap(logo_path).scaled(
            128, 128, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        painter.drawPixmap((canvas_w - logo.width()) // 2, 20, logo)

    _draw_outlined_text(
        painter, 0, 170, canvas_w, 36, t("app_name"),
        QFont("Consolas", 26, QFont.Weight.Bold), QColor("#17B897"),  # +20% par rapport à 22
    )

    painter.end()

    splash = QSplashScreen(canvas, Qt.WindowType.FramelessWindowHint)
    splash.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    return splash
