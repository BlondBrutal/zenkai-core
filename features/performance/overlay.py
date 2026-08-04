"""
Overlay de statistiques en direct (CPU/RAM/GPU/Disque) affiché par-dessus le
jeu, façon "overlay FPS" classique : fenêtre Qt réelle, sans cadre, toujours
au premier plan, opacité réglable, déplaçable à la souris n'importe où sur
l'écran (sa position est mémorisée et restaurée au prochain lancement).

Contrairement à RobloxCursorOverlay (features/cursor/roblox_overlay.py), PAS
"click-through" (WindowTransparentForInput) : l'utilisateur doit pouvoir
cliquer-glisser dessus pour le repositionner, donc elle accepte les clics —
seulement sur son propre rectangle (petit, dans un coin), le reste de l'écran/
du jeu reste cliquable normalement.

Opacité fond/texte INDÉPENDANTES : `setWindowOpacity` (opacité de fenêtre
Qt standard) s'applique à TOUT ce qui est peint, impossible de distinguer
fond et texte avec cette seule API. À la place, la fenêtre reste à opacité
1.0 et chaque opacité est peinte à la main via le canal alpha des couleurs
(fond dans paintEvent, texte dans les couleurs rgba() des <span> HTML).
"""
from typing import Optional

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from core.config import config
from core.i18n import t
from features.performance.live_monitor import LiveSample
from ui.status_colors import STATUS_NEUTRAL, STATUS_OK

_MARGIN_FROM_SCREEN_EDGE = 24
_PADDING = 10
_LINE_SPACING = 4
_CORNER_RADIUS = 10
# Alphas de référence à 100% d'opacité fond (voir _bg_color()/_border_color()) :
# mêmes valeurs que la version précédente à opacité fixe, juste rendues
# proportionnelles au curseur "Opacité du fond" au lieu d'être codées en dur.
_BG_BASE_ALPHA = 225
_BORDER_BASE_ALPHA = 220
_BG_BASE_RGB = (16, 18, 21)
_BORDER_BASE_RGB = (23, 184, 151)

_ELEMENT_LABEL_KEYS = {
    "cpu": "page.performance.overlay_element_cpu",
    "ram": "page.performance.overlay_element_ram",
    "gpu": "page.performance.overlay_element_gpu",
    "disk": "page.performance.overlay_element_disk",
    "net": "page.performance.overlay_element_net",
    "ping": "page.performance.overlay_element_ping",
    "fps": "page.performance.overlay_element_fps",
    "battery": "page.performance.overlay_element_battery",
}
ALL_ELEMENTS = ("cpu", "ram", "gpu", "disk", "net", "ping", "fps", "battery")

# Valeur la plus large plausible par ligne (voir _recompute_fixed_width) :
# sert à caler une largeur fixe qui ne bouge plus une fois déterminée, plutôt
# que de suivre la longueur réelle du texte affiché à chaque échantillon
# (ex: "3%" vs "100%" n'ont pas la même largeur, ce qui faisait "respirer"
# l'overlay en continu).
_WORST_CASE_VALUES = {
    "cpu": "100%",
    "ram": "100%",
    "gpu": "100%",
    "disk": "↓999 ↑999 Mo/s",
    "net": "↓999 ↑999 Ko/s",
    "ping": "999 ms",
    "fps": "999",
    "battery": "100%",
}
_EMPTY_OVERLAY_WIDTH = 90
_WIDTH_SAFETY_MARGIN = 6


def _with_alpha(rgb: tuple[int, int, int], base_alpha: int, opacity_percent: int) -> QColor:
    color = QColor(*rgb)
    color.setAlpha(round(base_alpha * max(0, min(100, opacity_percent)) / 100))
    return color


def _rgba_css(rgb: tuple[int, int, int], opacity_percent: int) -> str:
    color = _with_alpha(rgb, 255, opacity_percent)
    return f"rgba({color.red()},{color.green()},{color.blue()},{color.alpha()})"


_NEUTRAL_RGB = QColor(STATUS_NEUTRAL).getRgb()[:3]
_OK_RGB = QColor(STATUS_OK).getRgb()[:3]


class PerformanceOverlay(QWidget):
    """Un seul point d'entrée : construire, `apply_settings(...)`, puis
    `show()`. `update_sample(...)` pousse les nouvelles valeurs (voir
    LiveMonitorThread.sample_ready, branché en plus du slot de la page)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        # Opacité de fenêtre Qt standard jamais retouchée ensuite : fond et
        # texte gèrent leur propre opacité indépendamment via leur alpha
        # (voir docstring du module).
        self.setWindowOpacity(1.0)

        self._elements: list[str] = list(ALL_ELEMENTS)
        self._font_size = 13
        self._bg_opacity_percent = 85
        self._text_opacity_percent = 100
        self._drag_offset: QPoint | None = None
        self._last_sample: LiveSample | None = None
        self._last_ping_ms: Optional[float] = None
        self._last_fps: Optional[float] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(_PADDING + 2, _PADDING, _PADDING + 2, _PADDING)
        layout.setSpacing(_LINE_SPACING)

        self._labels: dict[str, QLabel] = {}
        for key in ALL_ELEMENTS:
            label = QLabel("")
            label.setStyleSheet("background: transparent;")
            # Sans ça, un clic sur le TEXTE (donc presque toute la surface de
            # l'overlay) est capté par ce label — qui ne fait rien de cet
            # évènement — au lieu de remonter jusqu'à mousePressEvent
            # ci-dessous : seule la petite marge autour du texte restait
            # alors glissable. "Transparent aux évènements souris" fait
            # ignorer ce label lors du hit-test, le clic atteint directement
            # ce widget parent quel que soit l'endroit cliqué.
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(label)
            self._labels[key] = label

        # Visible seulement quand AUCUN élément n'est activé : une ligne
        # vide (juste le cadre/fond) plutôt que de retomber sur "afficher
        # tout" (l'ancien comportement, qui ignorait silencieusement des
        # toggles pourtant tous désactivés) ou sur une fenêtre vide de 0px.
        self._empty_placeholder = QLabel(" ")
        self._empty_placeholder.setStyleSheet("background: transparent;")
        self._empty_placeholder.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._empty_placeholder.setVisible(False)
        layout.addWidget(self._empty_placeholder)

        self._reposition_or_restore()

    # ------------------------------------------------------------------
    def _set_line(self, key: str, value_text: str) -> None:
        """Nom de la métrique en gris discret, valeur en turquoise bien
        visible — plus lisible qu'une seule couleur de texte uniforme."""
        label_color = _rgba_css(_NEUTRAL_RGB, self._text_opacity_percent)
        value_color = _rgba_css(_OK_RGB, self._text_opacity_percent)
        label = self._labels[key]
        label.setText(
            f'<span style="color:{label_color};">{t(_ELEMENT_LABEL_KEYS[key])}</span> '
            f'<span style="color:{value_color};font-weight:700;">{value_text}</span>'
        )

    def apply_settings(
        self,
        elements: list[str],
        bg_opacity_percent: int,
        text_opacity_percent: int,
        font_size: int,
    ) -> None:
        """Appelé à l'activation ET à chaque changement dans le panneau de
        configuration (aperçu en direct, pas seulement à la fermeture)."""
        # Pas de repli sur ALL_ELEMENTS quand la liste est vide : une liste
        # vide veut dire "tout désactivé", à respecter tel quel (voir
        # _empty_placeholder ci-dessus) plutôt que de tout réafficher.
        self._elements = [e for e in ALL_ELEMENTS if e in elements]
        self._font_size = font_size
        self._bg_opacity_percent = bg_opacity_percent
        self._text_opacity_percent = text_opacity_percent

        for key, label in self._labels.items():
            visible = key in self._elements
            label.setVisible(visible)
            if visible:
                label.setStyleSheet(f"background: transparent; font-size: {self._font_size}px; font-weight: 700;")
                if not label.text():
                    self._set_line(key, "…")

        self._empty_placeholder.setVisible(not self._elements)
        if not self._elements:
            self._empty_placeholder.setStyleSheet(f"background: transparent; font-size: {self._font_size}px;")

        if self._last_sample is not None:
            self.update_sample(self._last_sample)
        if "ping" in self._elements:
            self.update_ping(self._last_ping_ms)
        if "fps" in self._elements:
            self.update_fps(self._last_fps)

        self._recompute_fixed_width()
        self.update()
        self.adjustSize()

    def update_sample(self, sample: LiveSample) -> None:
        self._last_sample = sample
        if "cpu" in self._elements:
            self._set_line("cpu", f"{sample.cpu_percent:.0f}%")
        if "ram" in self._elements:
            self._set_line("ram", f"{sample.ram_percent:.0f}%")
        if "gpu" in self._elements:
            gpu_text = f"{sample.gpu_percent:.0f}%" if sample.gpu_available and sample.gpu_percent is not None else "N/A"
            self._set_line("gpu", gpu_text)
        if "disk" in self._elements:
            self._set_line("disk", f"↓{sample.disk_read_mbps:.0f} ↑{sample.disk_write_mbps:.0f} Mo/s")
        if "net" in self._elements:
            self._set_line("net", f"↓{sample.net_download_kbps:.0f} ↑{sample.net_upload_kbps:.0f} Ko/s")
        if "battery" in self._elements:
            # Même "N/A" que GPU/Ping/FPS quand indisponible (PC de bureau,
            # sans batterie) : déjà compris dans l'app comme "cette mesure
            # n'est pas disponible ici", et tient dans la largeur fixe
            # calée sur "100%" (voir _WORST_CASE_VALUES) — un texte plus
            # long ("Aucune batterie détectée") la dépasserait.
            battery_text = (
                f"{sample.battery_percent:.0f}%"
                if sample.battery_available and sample.battery_percent is not None
                else "N/A"
            )
            self._set_line("battery", battery_text)
        self.adjustSize()

    def update_ping(self, ping_ms: Optional[float]) -> None:
        self._last_ping_ms = ping_ms
        if "ping" in self._elements:
            self._set_line("ping", f"{ping_ms:.0f} ms" if ping_ms is not None else "N/A")
            self.adjustSize()

    def update_fps(self, fps: Optional[float]) -> None:
        self._last_fps = fps
        if "fps" in self._elements:
            self._set_line("fps", f"{fps:.0f}" if fps is not None else "N/A")
        self.adjustSize()

    # ------------------------------------------------------------------
    # Largeur fixe (voir docstring du module + _WORST_CASE_VALUES) : calculée
    # une fois par changement de réglages (éléments/police), jamais suivie en
    # temps réel sur le contenu réel — adjustSize() ailleurs ne peut donc plus
    # faire "respirer" que la hauteur.
    def _recompute_fixed_width(self) -> None:
        if not self._elements:
            self.setFixedWidth(_EMPTY_OVERLAY_WIDTH)
            return

        probe = QLabel()
        probe.setStyleSheet(f"font-size: {self._font_size}px; font-weight: 700;")
        max_text_width = 0
        for key in self._elements:
            probe.setText(
                f'<span>{t(_ELEMENT_LABEL_KEYS[key])}</span> '
                f'<span style="font-weight:700;">{_WORST_CASE_VALUES[key]}</span>'
            )
            probe.adjustSize()
            max_text_width = max(max_text_width, probe.width())

        margins = self.layout().contentsMargins()
        total_width = max_text_width + margins.left() + margins.right() + _WIDTH_SAFETY_MARGIN
        self.setFixedWidth(total_width)

    # ------------------------------------------------------------------
    def _reposition_or_restore(self) -> None:
        x = config.get("performance_overlay_pos_x")
        y = config.get("performance_overlay_pos_y")
        if x is not None and y is not None:
            self.move(int(x), int(y))
        else:
            self._place_top_right()

    def _place_top_right(self) -> None:
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        avail = screen.availableGeometry()
        self.move(
            avail.right() - self.width() - _MARGIN_FROM_SCREEN_EDGE,
            avail.top() + _MARGIN_FROM_SCREEN_EDGE,
        )

    # ------------------------------------------------------------------
    # Déplacement à la souris : suivi manuel (pas de QDrag natif nécessaire
    # pour un simple glisser-déposer d'une fenêtre top-level), position
    # persistée au relâchement pour être restaurée au prochain lancement.
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_offset is not None:
            self._drag_offset = None
            config.set("performance_overlay_pos_x", self.x())
            config.set("performance_overlay_pos_y", self.y())
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Marge de 1px : le contour se dessine à cheval sur le bord du
        # widget sinon (moitié de son épaisseur invisible, hors du rect).
        rect = self.rect().adjusted(1, 1, -1, -1)
        bg_color = _with_alpha(_BG_BASE_RGB, _BG_BASE_ALPHA, self._bg_opacity_percent)
        border_color = _with_alpha(_BORDER_BASE_RGB, _BORDER_BASE_ALPHA, self._bg_opacity_percent)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg_color)
        painter.drawRoundedRect(rect, _CORNER_RADIUS, _CORNER_RADIUS)

        painter.setPen(QPen(border_color, 1.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, _CORNER_RADIUS, _CORNER_RADIUS)
