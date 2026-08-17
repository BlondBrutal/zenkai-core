"""
Page Performance (ex-Diagnostic) : monitoring en direct (CPU/RAM/GPU/disque),
scan à la demande (specs, réglages Windows, cartes de statut), composant
limitant, et bouton de recommandation vers les Fast Flags.

Le monitoring en direct démarre à l'affichage de la page et s'arrête dès
qu'on la quitte (showEvent/hideEvent) : rafraîchissement 1x/seconde dans un
QThread séparé, jamais de scan lourd automatique (celui-ci reste déclenché
manuellement, cf. Partie 2.1 du brief).
"""
import logging

from PyQt6.QtCore import QPointF, QRectF, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QScrollArea, QSlider, QStackedWidget,
    QVBoxLayout, QWidget,
)

from core.config import config
from core.i18n import t
from features.performance.fixes import disable_game_dvr, disable_sysmain, enable_game_mode, set_power_plan_high_performance
from features.performance.fps_monitor import FpsMonitorThread
from features.performance.game_detection import ROBLOX_EXE_NAME, detect_foreground_game
from features.performance.live_monitor import LiveMonitorThread, LiveSample
from features.performance.overlay import ALL_ELEMENTS, PerformanceOverlay
from features.performance.ping_monitor import PingMonitorThread
from features.performance.scan import PerformanceScanWorker, ScanResult
from features.performance.status_cards import StatusCard
from ui.animated_button import AnimatedButton
from ui.pages.base_page import BasePage
from ui.pages.page_risk import RiskControlsPanel
from ui.ring_gauge import RingGauge
from ui.scrollbar_style import apply_viewport_scrollbar_gap, style_scrollbar_directly
from ui.status_colors import STATUS_CRITICAL, STATUS_NEUTRAL, STATUS_OK, STATUS_WARNING
from ui.styled_message_box import show_confirm
from ui.toggle_switch import ToggleSwitch

# Icône power et loader partagent exactement la même taille : le loader doit
# remplacer le bouton en place pendant le scan, pas apparaître ailleurs/à une
# autre taille. +20% par rapport à la version d'origine (96px).
_HERO_SIZE = 115
# Hauteur fixe partagée par les 4 tuiles de monitoring en direct : sans ça,
# la tuile CPU (pas de légende) et RAM/GPU (avec légende) n'ont pas la même
# hauteur naturelle, ce qui décale visuellement les anneaux entre eux.
_LIVE_TILE_HEIGHT = 150

# Barème fixe pour la couleur des anneaux CPU/RAM/GPU (identique pour les
# trois, indépendant des seuils de détection du composant limitant).
_RING_WARNING_PERCENT = 50.0
_RING_CRITICAL_PERCENT = 80.0

# Barre de scroll en forme de pilule, scopée aux 3 onglets
# Diagnostic/Overlay/Risque (voir _build_scrollable_tab_container) — un peu
# plus épaisse que le style app-wide habituel (10px, voir
# ui/scrollbar_style.py). Posée directement sur l'instance via
# style_scrollbar_directly (même technique déjà éprouvée pour la
# bibliothèque de macros) : ces onglets vivent dans un QStackedWidget
# (section_stack), contexte où le QProxyStyle app-wide seul n'est pas fiable.
_TAB_SCROLLBAR_THICKNESS = 11  # -10% (12 -> 11)
# Petit espace en haut/bas de la barre (au lieu de toucher les bords) : le
# "margin" QSS sur la QScrollBar elle-même n'a aucun effet vertical ici
# (vérifié : bar.y()==0 et bar.height()==viewport.height() peu importe la
# valeur déclarée) — on rogne donc la QScrollArea elle-même via un padding
# haut/bas (même technique que _TAB_SCROLLBAR_GAP pour le bord droit), qui
# réduit la hauteur disponible pour la barre en même temps que celle du
# contenu.
_TAB_SCROLLBAR_VERTICAL_INSET = 4


def _severity_color(value: float) -> str:
    if value >= _RING_CRITICAL_PERCENT:
        return STATUS_CRITICAL
    if value >= _RING_WARNING_PERCENT:
        return STATUS_WARNING
    return STATUS_OK


class PulsingLoader(QWidget):
    """Loader classique : un anneau discret avec un arc qui tourne en continu
    (style spinner par défaut, sans rien d'organique ni de réactif). Le
    timer ne tourne que pendant le scan (start/stop explicites), jamais en
    arrière-plan sans raison."""

    _COLOR = QColor(23, 184, 151)
    _TRACK_COLOR = QColor(255, 255, 255, 30)
    _SPAN_DEGREES = 100
    _DEGREES_PER_TICK = 6

    def __init__(self, size: int = _HERO_SIZE, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(16)  # ~60 fps : rotation fluide
        self._timer.timeout.connect(self._advance)

    def _advance(self) -> None:
        self._angle = (self._angle + self._DEGREES_PER_TICK) % 360
        self.update()

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        base = min(self.width(), self.height())
        thickness = max(2.0, base * 0.09)
        rect = QRectF(thickness / 2, thickness / 2, base - thickness, base - thickness)

        painter.setPen(QPen(self._TRACK_COLOR, thickness, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(rect, 0, 360 * 16)

        painter.setPen(QPen(self._COLOR, thickness, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(rect, -self._angle * 16, self._SPAN_DEGREES * 16)


# --- Colonne de sélection de section (Diagnostic / Overlay / réservé) ------
_TAB_ICON_SIZE = 20
_TAB_DISABLED_COLOR = "#4A4E56"
# Couleur de fond des tuiles (voir QFrame.navTabButton dans theme.qss) : sert
# à peindre l'icône "calques" en dur pour masquer le coin qui se chevauche
# (même technique que l'ancienne _OverlayIcon de la tuile "Activer l'overlay").
_TAB_TILE_BG = QColor("#1F1F25")


class _DiagnosticTabIcon(QWidget):
    """Loupe vectorielle (cercle + manche) pour l'onglet "Diagnostic"."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(_TAB_ICON_SIZE, _TAB_ICON_SIZE)
        self._color = QColor(STATUS_NEUTRAL)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        painter.setPen(QPen(self._color, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        lens_rect = QRectF(w * 0.10, h * 0.10, w * 0.58, h * 0.58)
        painter.drawEllipse(lens_rect)
        painter.drawLine(
            QPointF(lens_rect.right() - w * 0.06, lens_rect.bottom() - h * 0.06),
            QPointF(w * 0.92, h * 0.92),
        )


class _OverlayTabIcon(QWidget):
    """Icône "calques" (deux carrés arrondis superposés) pour l'onglet
    "Overlay" — même dessin que l'ancienne tuile "Activer l'overlay"."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(_TAB_ICON_SIZE, _TAB_ICON_SIZE)
        self._color = QColor(STATUS_NEUTRAL)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        back = QRectF(w * 0.06, h * 0.04, w * 0.62, h * 0.62)
        front = QRectF(w * 0.32, h * 0.34, w * 0.62, h * 0.62)

        painter.setPen(QPen(self._color, 1.6))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(back, 3, 3)

        painter.setBrush(_TAB_TILE_BG)
        painter.drawRoundedRect(front, 3, 3)


class _RiskTabIcon(QWidget):
    """Icône bouclier vectorielle (silhouette + point d'exclamation) pour
    l'onglet "Risque"."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(_TAB_ICON_SIZE, _TAB_ICON_SIZE)
        self._color = QColor(STATUS_NEUTRAL)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        shield = QPainterPath()
        shield.moveTo(w * 0.5, h * 0.06)
        shield.cubicTo(w * 0.78, h * 0.14, w * 0.86, h * 0.16, w * 0.86, h * 0.16)
        shield.lineTo(w * 0.86, h * 0.46)
        shield.cubicTo(w * 0.86, h * 0.74, w * 0.68, h * 0.90, w * 0.5, h * 0.96)
        shield.cubicTo(w * 0.32, h * 0.90, w * 0.14, h * 0.74, w * 0.14, h * 0.46)
        shield.lineTo(w * 0.14, h * 0.16)
        shield.cubicTo(w * 0.14, h * 0.16, w * 0.22, h * 0.14, w * 0.5, h * 0.06)
        shield.closeSubpath()

        painter.setPen(QPen(self._color, 1.8))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(shield)

        painter.setPen(QPen(self._color, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(w * 0.5, h * 0.32), QPointF(w * 0.5, h * 0.56))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(QPointF(w * 0.5, h * 0.68), w * 0.035, w * 0.035)


class _ReservedTabIcon(QWidget):
    """Icône cadenas vectorielle (corps + anse) pour le 3e onglet, réservé
    à une future fonctionnalité — signale visuellement "pas encore
    disponible" plutôt qu'un simple onglet inactif."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(_TAB_ICON_SIZE, _TAB_ICON_SIZE)
        self._color = QColor(_TAB_DISABLED_COLOR)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color)
        body = QRectF(w * 0.20, h * 0.45, w * 0.60, h * 0.42)
        painter.drawRoundedRect(body, 2, 2)

        painter.setPen(QPen(self._color, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        shackle_rect = QRectF(w * 0.30, h * 0.10, w * 0.40, h * 0.48)
        painter.drawArc(shackle_rect, 0, 180 * 16)


class _NavTabButton(QFrame):
    """Bouton d'onglet vertical de la colonne de droite : icône + texte côte
    à côte, état actif en turquoise avec contour — même logique de mise en
    évidence que _SegmentButton (page_macro.py, onglets "Macro type"), en
    empilement vertical plutôt qu'horizontal."""

    clicked = pyqtSignal()

    def __init__(self, icon: QWidget, text: str, parent=None):
        super().__init__(parent)
        self.setProperty("class", "navTabButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._icon = icon

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)

        self._label = QLabel(text)
        self._label.setWordWrap(True)
        layout.addWidget(self._label, 1)

        self.set_active(False)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.clicked.emit()
        super().mousePressEvent(event)

    def set_active(self, active: bool) -> None:
        self.setProperty("active", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        color = STATUS_OK if active else STATUS_NEUTRAL
        self._icon.set_color(color)
        self._label.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {color};")

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)
        if not enabled:
            # Grisé plus fort que l'état "inactif" normal : signale un
            # bouton réservé pour plus tard, pas juste un onglet non
            # sélectionné qu'on pourrait cliquer.
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self._icon.set_color(_TAB_DISABLED_COLOR)
            self._label.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {_TAB_DISABLED_COLOR};")


class _NoWheelSlider(QSlider):
    """QSlider dont la molette de la souris ne change jamais la valeur —
    seul le glisser-déposer de la poignée le peut. L'événement est ignoré
    (pas juste "non traité") pour qu'il remonte au parent : la molette au-
    dessus d'un curseur fait défiler la page, comme si le curseur n'était
    pas là."""

    def wheelEvent(self, event) -> None:
        event.ignore()


_OVERLAY_ELEMENT_LABEL_KEYS = {
    "cpu": "page.performance.overlay_element_cpu",
    "ram": "page.performance.overlay_element_ram",
    "gpu": "page.performance.overlay_element_gpu",
    "disk": "page.performance.overlay_element_disk",
    "net": "page.performance.overlay_element_net",
    "ping": "page.performance.overlay_element_ping",
    "fps": "page.performance.overlay_element_fps",
    "battery": "page.performance.overlay_element_battery",
}


class _OverlayControlsPanel(QFrame):
    """Contenu de l'onglet "Overlay" de la zone principale : activation +
    tous les réglages (éléments affichés, opacité fond/texte, taille de
    police). Vit directement dans la zone principale comme les résultats du
    diagnostic — pas de dialogue modal par-dessus, un onglet dédié n'en a
    pas besoin (voir _build_section_tabs_column). Chaque changement
    s'applique EN DIRECT sur l'overlay déjà affiché (aperçu immédiat), pas
    seulement en quittant l'onglet.

    Ping et FPS détectent automatiquement le jeu au premier plan (Valorant,
    Roblox, ou tout autre jeu connu, voir features/performance/game_detection.py)
    : pas de sélecteur d'application ici, inutile de choisir manuellement.

    Pas de classe QSS "card" ici (contrairement à l'ancienne version) : ce
    panneau vit maintenant DANS une QScrollArea (voir
    PerformancePage._build_overlay_tab_container) qui porte elle-même le
    fond/contour "card" — sinon la bordure arrondie défilerait avec le
    contenu au lieu de rester fixe autour de la zone de défilement."""

    enabled_toggled = pyqtSignal(bool)
    settings_changed = pyqtSignal(list, int, int, int)  # (elements, bg_opacity_percent, text_opacity_percent, font_size)

    def __init__(
        self,
        enabled: bool,
        elements: list[str],
        bg_opacity_percent: int,
        text_opacity_percent: int,
        font_size: int,
        parent=None,
    ):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        enable_row = QHBoxLayout()
        enable_row.setSpacing(8)
        enable_label = QLabel(t("page.performance.overlay_enable_tile"))
        enable_label.setStyleSheet("font-size: 14px; font-weight: 700; color: #E7E9EE; padding-bottom: 3px;")
        enable_row.addWidget(enable_label)
        enable_row.addStretch(1)
        self.enable_toggle = ToggleSwitch(checked=enabled)
        self.enable_toggle.toggled.connect(self.enabled_toggled.emit)
        enable_row.addWidget(self.enable_toggle)
        layout.addLayout(enable_row)

        hint = QLabel(t("page.performance.overlay_drag_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size: 12px; color: {STATUS_NEUTRAL};")
        layout.addWidget(hint)

        # Section "Éléments affichés" : 2 colonnes de toggles (inchangé),
        # empilée verticalement au-dessus de la section "Apparence" — pas
        # côte à côte (ça faisait déborder le panneau horizontalement,
        # d'où la barre de scroll qui apparaissait à l'horizontale en bas
        # au lieu de rester verticale sur le bord droit).
        elements_title = QLabel(t("page.performance.overlay_elements_title"))
        elements_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #E7E9EE;")
        layout.addWidget(elements_title)

        # 2 colonnes plutôt qu'une seule liste verticale : sur la largeur de
        # ce panneau, une seule colonne laissait un grand vide horizontal
        # entre le label et le toggle (aussi étroite que la ligne "CPU :").
        elements_columns = QHBoxLayout()
        elements_columns.setSpacing(20)
        left_column = QVBoxLayout()
        left_column.setSpacing(10)
        right_column = QVBoxLayout()
        right_column.setSpacing(10)
        elements_columns.addLayout(left_column, 1)
        elements_columns.addLayout(right_column, 1)
        layout.addLayout(elements_columns)

        # CPU/RAM/GPU/Disque à gauche, Réseau/Ping/FPS/Batterie à droite (les
        # 2 premiers groupes historiques vs les groupes ajoutés ensuite).
        column_split = (ALL_ELEMENTS[:4], ALL_ELEMENTS[4:])

        self._toggles: dict[str, ToggleSwitch] = {}
        for column_layout, keys in zip((left_column, right_column), column_split):
            for key in keys:
                row = QHBoxLayout()
                row.setSpacing(8)
                label = QLabel(t(_OVERLAY_ELEMENT_LABEL_KEYS[key]))
                label.setStyleSheet(f"font-size: 12px; color: {STATUS_NEUTRAL};")
                row.addWidget(label)
                row.addStretch(1)
                toggle = ToggleSwitch(checked=key in elements)
                toggle.toggled.connect(self._emit_changed)
                row.addWidget(toggle)
                column_layout.addLayout(row)
                self._toggles[key] = toggle
            column_layout.addStretch(1)

        # Fine ligne de séparation horizontale entre les 2 sections — même
        # style que le séparateur déjà utilisé entre les emplacements de la
        # page Macro Pixel (voir _build_green_separator dans
        # macro_pixel_tab.py), juste sans largeur fixe (celle-ci s'étire sur
        # toute la largeur du panneau au lieu d'une colonne figée).
        separator = QFrame()
        separator.setFixedHeight(2)
        separator.setStyleSheet(f"background-color: {STATUS_OK}; border: none; border-radius: 1px;")
        layout.addWidget(separator)

        # Section "Apparence" : les 3 curseurs empilés verticalement, chacun
        # sur toute la largeur disponible avec son label complet AU-DESSUS
        # (jamais à côté) — un label à côté aurait dû se couper sur 2 lignes
        # de façon inégale pour "Opacité du fond"/"Opacité du texte"/"Taille
        # du texte" à cette largeur.
        appearance_title = QLabel(t("page.performance.overlay_appearance_title"))
        appearance_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #E7E9EE;")
        layout.addWidget(appearance_title)

        self.bg_opacity_slider = self._build_full_width_slider(
            layout, t("page.performance.overlay_bg_opacity_label"), 20, 100, bg_opacity_percent
        )
        self.text_opacity_slider = self._build_full_width_slider(
            layout, t("page.performance.overlay_text_opacity_label"), 20, 100, text_opacity_percent
        )
        self.font_slider = self._build_full_width_slider(
            layout, t("page.performance.overlay_font_size_label"), 9, 24, font_size
        )

        layout.addStretch(1)

    def _build_full_width_slider(
        self, parent_layout: QVBoxLayout, title_text: str, minimum: int, maximum: int, value: int
    ) -> QSlider:
        title = QLabel(title_text)
        title.setStyleSheet(f"font-size: 12px; color: {STATUS_NEUTRAL};")
        parent_layout.addWidget(title)

        slider = _NoWheelSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        # La poignée stylée (theme.qss) déborde de 16px de haut alors que le
        # sizeHint par défaut du QSlider (15px) ignore ce déborderment défini
        # en QSS : sans hauteur fixe plus généreuse, la poignée ronde est
        # rognée en haut et en bas de sa piste.
        slider.setFixedHeight(22)
        slider.valueChanged.connect(self._emit_changed)
        parent_layout.addWidget(slider)
        return slider

    def _emit_changed(self, *_args) -> None:
        elements = [key for key, toggle in self._toggles.items() if toggle.isChecked()]
        self.settings_changed.emit(
            elements, self.bg_opacity_slider.value(), self.text_opacity_slider.value(), self.font_slider.value()
        )


logger = logging.getLogger("zenkaiontop.performance")

# Le badge "warning" s'affiche en rouge (comme "critical"), pas en orange :
# la couleur orange reste réservée à la zone 50-80% des anneaux CPU/RAM/GPU.
_LEVEL_COLORS = {"ok": STATUS_OK, "warning": STATUS_CRITICAL, "critical": STATUS_CRITICAL}
_LEVEL_BADGE_KEYS = {
    "ok": "page.performance.badge_ok",
    "warning": "page.performance.badge_warning",
    "critical": "page.performance.badge_critical",
}
_COMPONENT_LABEL_KEYS = {
    "cpu": "performance.component.cpu",
    "gpu": "performance.component.gpu",
    "ram": "performance.component.ram",
    "disk": "performance.component.disk",
}
# Mêmes clés de traduction que la page Fast Flags (page_fastflags.py) : un
# seul texte source pour le nom de chaque preset, pas de duplication.
_PRESET_NAME_KEYS = {
    "hard": "page.fastflags.preset_hard",
    "balanced": "page.fastflags.preset_balanced",
}

# Corrections automatiques disponibles, par identifiant de carte.
_AUTO_FIXES = {
    "power_plan": set_power_plan_high_performance,
    "game_mode": enable_game_mode,
    "game_dvr": disable_game_dvr,
    "sysmain": disable_sysmain,
}

# Texte d'avertissement affiché AVANT chaque correction (voir
# _StatusCardWidget._run_auto_fix et PerformancePage._on_optimize_clicked) :
# ces 4 corrections écrivent toutes dans une catégorie sensible du journal
# de sécurité (REGISTRY_WRITE, EXTERNAL_EXECUTION ou SERVICE_CONTROL, voir
# core/security_log.py) — un clic sur "Corriger"/"Optimiser" est un
# changement de configuration ponctuel et explicite, donc averti, à la
# différence du chemin de lancement du jeu (volontairement sans friction).
_FIX_CONFIRM_TEXT_KEYS = {
    "power_plan": "page.performance.fix_confirm_power_plan",
    "game_mode": "page.performance.fix_confirm_game_mode",
    "game_dvr": "page.performance.fix_confirm_game_dvr",
    "sysmain": "page.performance.fix_confirm_sysmain",
}


class _FixWorker(QThread):
    """Applique une correction dans un thread séparé : certaines (SysMain)
    demandent une élévation UAC et peuvent donc rester bloquées plusieurs
    secondes en attendant la réponse de l'utilisateur — jamais dans le
    thread UI."""

    finished_fix = pyqtSignal(bool)

    def __init__(self, fix_fn, parent=None):
        super().__init__(parent)
        self._fix_fn = fix_fn

    def run(self) -> None:
        try:
            success = bool(self._fix_fn()) if self._fix_fn else False
        except Exception:
            logger.exception("Échec inattendu pendant une correction automatique")
            success = False
        self.finished_fix.emit(success)


class _OptimizeWorker(QThread):
    """Applique d'affilée toutes les corrections automatiques disponibles
    pour ce scan (bouton "Optimiser pour Roblox"). Thread séparé pour la
    même raison que _FixWorker : SysMain peut demander une élévation UAC."""

    finished_all = pyqtSignal(list)  # list[tuple[str, bool]] (card_id, succès)

    def __init__(self, card_ids: list[str], parent=None):
        super().__init__(parent)
        self._card_ids = card_ids

    def run(self) -> None:
        results = []
        for card_id in self._card_ids:
            fix_fn = _AUTO_FIXES.get(card_id)
            try:
                success = bool(fix_fn()) if fix_fn else False
            except Exception:
                logger.exception("Échec inattendu pendant l'optimisation groupée (%s)", card_id)
                success = False
            results.append((card_id, success))
        self.finished_all.emit(results)


class SparklineWidget(QWidget):
    """Historique court (fenêtre glissante ~30s) d'une métrique sans plafond
    naturel (débit disque en Mo/s) : aire + ligne plutôt qu'une jauge 0-100%."""

    _MAX_POINTS = 30
    _LINE_COLOR = QColor(STATUS_OK)
    _FILL_COLOR = QColor(23, 184, 151, 40)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(44)
        self._values: list[float] = []

    def push_value(self, value: float) -> None:
        self._values.append(max(0.0, value))
        if len(self._values) > self._MAX_POINTS:
            self._values.pop(0)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if len(self._values) < 2:
            return

        w, h = self.width(), self.height()
        max_val = max(self._values) or 1.0
        step_x = w / (len(self._values) - 1)

        points = [
            QPointF(i * step_x, h - (val / max_val) * (h - 6) - 3)
            for i, val in enumerate(self._values)
        ]

        area_path = QPainterPath()
        area_path.moveTo(0, h)
        for pt in points:
            area_path.lineTo(pt)
        area_path.lineTo(w, h)
        area_path.closeSubpath()
        painter.fillPath(area_path, self._FILL_COLOR)

        line_path = QPainterPath()
        line_path.moveTo(points[0])
        for pt in points[1:]:
            line_path.lineTo(pt)
        painter.setPen(QPen(self._LINE_COLOR, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(line_path)

    def clear(self) -> None:
        self._values.clear()
        self.update()


class _StatusCardWidget(QFrame):
    """Une carte de statut avec badge coloré. Quand une correction peut être
    appliquée automatiquement, un unique bouton "Corriger" la déclenche
    directement (pas de panneau d'explication intermédiaire) ; sinon, les
    étapes manuelles restent dépliables via "Comment corriger ?" (il n'y a
    alors aucune action à déclencher, juste des étapes à lire)."""

    fixed = pyqtSignal()  # émis après une correction automatique réussie, pour relancer le scan

    def __init__(self, card: StatusCard, parent=None):
        super().__init__(parent)
        self.card = card
        self.setProperty("class", "card")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel(t(card.title_key))
        title.setStyleSheet("font-size: 14px; font-weight: 700; color: #E7E9EE; padding-bottom: 3px;")
        # wordWrap + stretch : sans ça, un titre long ("Xbox Game Bar /
        # enregistrement en arrière-plan") imposait une largeur minimale à
        # toute la carte (donc à toute la zone de résultats) plutôt que de
        # passer sur 2 lignes — c'est ce qui provoquait un débordement
        # horizontal (scroll horizontal) dès qu'un tel diagnostic apparaissait.
        title.setWordWrap(True)
        header.addWidget(title)
        header.addStretch(1)

        # Le statut se lit à la couleur du texte, pas à une puce/boîte en plus
        # (cohérent avec la page Licence — hiérarchie par typographie, pas par boîtes imbriquées).
        color = _LEVEL_COLORS.get(card.level, STATUS_NEUTRAL)
        badge = QLabel(t(_LEVEL_BADGE_KEYS.get(card.level, "page.performance.badge_ok")))
        badge.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 700;")
        header.addWidget(badge)
        layout.addLayout(header)

        desc = QLabel(t(card.desc_key).format(**card.desc_kwargs))
        desc.setWordWrap(True)
        desc.setStyleSheet(f"font-size: 12px; color: {STATUS_NEUTRAL};")
        layout.addWidget(desc)

        if card.can_auto_fix and card.card_id in _AUTO_FIXES:
            # Espace supplémentaire avant le bouton (au-delà du spacing
            # uniforme du layout) : sans ça, il reste collé au texte au-dessus.
            layout.addSpacing(6)

            self.fix_btn = AnimatedButton(t("page.performance.auto_fix_btn"), variant="secondary")
            self.fix_btn.clicked.connect(self._run_auto_fix)
            layout.addWidget(self.fix_btn, 0, Qt.AlignmentFlag.AlignLeft)

            progress_row = QHBoxLayout()
            progress_row.setSpacing(8)
            self._fix_spinner = PulsingLoader(size=18)
            self._fix_spinner.setVisible(False)
            progress_row.addWidget(self._fix_spinner)

            # Masqué tant qu'il n'y a rien à dire : un QLabel vide réserve
            # quand même la hauteur d'une ligne, ce qui laissait un vide en
            # bas de carte avant même la première correction.
            self.auto_fix_result = QLabel("")
            self.auto_fix_result.setVisible(False)
            self.auto_fix_result.setWordWrap(True)
            self.auto_fix_result.setStyleSheet("font-size: 11px;")
            progress_row.addWidget(self.auto_fix_result, 1)
            layout.addLayout(progress_row)
        elif card.fix_steps_key:
            self.toggle_btn = QPushButton(t("page.performance.fix_btn_show"))
            self.toggle_btn.setProperty("class", "secondaryButton")
            self.toggle_btn.clicked.connect(self._toggle_fix_panel)
            layout.addWidget(self.toggle_btn)

            self.fix_panel = QWidget()
            fix_layout = QVBoxLayout(self.fix_panel)
            fix_layout.setContentsMargins(0, 6, 0, 0)
            fix_layout.setSpacing(8)

            steps_label = QLabel(t(card.fix_steps_key))
            steps_label.setWordWrap(True)
            steps_label.setStyleSheet("font-size: 12px; color: #C7CBD3;")
            fix_layout.addWidget(steps_label)

            self.fix_panel.setVisible(False)
            layout.addWidget(self.fix_panel)

    def _toggle_fix_panel(self) -> None:
        showing = not self.fix_panel.isVisible()
        self.fix_panel.setVisible(showing)
        self.toggle_btn.setText(t("page.performance.fix_btn_hide") if showing else t("page.performance.fix_btn_show"))

    def _run_auto_fix(self) -> None:
        confirm_text_key = _FIX_CONFIRM_TEXT_KEYS.get(self.card.card_id)
        if confirm_text_key and not show_confirm(
            self, t("dialog.security_warning_title"), t(confirm_text_key),
            confirm_label=t("page.performance.fix_confirm_btn"),
        ):
            return

        # Exécuté dans un thread séparé : certaines corrections (SysMain)
        # demandent une élévation UAC et peuvent donc attendre plusieurs
        # secondes la réponse de l'utilisateur — jamais bloquer l'UI pendant
        # ce temps. L'animation reflète le vrai travail en cours, pas un
        # délai artificiel.
        self.fix_btn.setEnabled(False)
        self.auto_fix_result.setVisible(False)
        self.auto_fix_result.setText("")
        self._fix_spinner.setVisible(True)
        self._fix_spinner.start()

        fix_fn = _AUTO_FIXES.get(self.card.card_id)
        self._fix_worker = _FixWorker(fix_fn, self)
        self._fix_worker.finished_fix.connect(self._on_fix_finished)
        self._fix_worker.start()

    def _on_fix_finished(self, success: bool) -> None:
        self._fix_spinner.stop()
        self._fix_spinner.setVisible(False)
        self.auto_fix_result.setVisible(True)

        if success:
            self.auto_fix_result.setStyleSheet(f"font-size: 11px; color: {STATUS_OK};")
            self.auto_fix_result.setText(t("page.performance.auto_fix_success"))
            self.fixed.emit()
        else:
            self.fix_btn.setEnabled(True)
            self.auto_fix_result.setStyleSheet(f"font-size: 11px; color: {STATUS_CRITICAL};")
            self.auto_fix_result.setText(t("page.performance.auto_fix_failure"))


class PerformancePage(BasePage):
    boost_requested = pyqtSignal(str, str)  # (preset_key, reason)

    def __init__(self, parent=None):
        super().__init__(t("page.performance.title"), "", parent)
        self.add_info_badge(t("page.performance.subtitle"))
        self.add_beta_badge(t("app.beta_warning"))

        # Marge droite réduite (32 -> 16), comme la page Macro (référence) :
        # cohérence de largeur de contenu entre toutes les pages (voir aussi
        # page_cursor.py/page_license.py/page_fastflags.py).
        margins = self.content_layout().contentsMargins()
        self.content_layout().setContentsMargins(margins.left(), margins.top(), 16, margins.bottom())

        self._live_thread: LiveMonitorThread | None = None
        self._scan_worker: PerformanceScanWorker | None = None
        self._last_result: ScanResult | None = None
        # Masque le rectangle d'optimisation dès qu'on clique sur son bouton
        # (voir _on_optimize_clicked) jusqu'au prochain "Relancer le
        # diagnostic" cliqué explicitement (voir _on_rescan_clicked) — le
        # rescan AUTOMATIQUE déclenché juste après une optimisation
        # (_on_optimize_finished) ne doit pas le faire réapparaître tout
        # seul.
        self._hide_optimize_card = False
        self._overlay: PerformanceOverlay | None = None
        self._ping_thread: PingMonitorThread | None = None
        self._fps_thread: FpsMonitorThread | None = None

        QApplication.instance().aboutToQuit.connect(self._stop_live_thread)
        QApplication.instance().aboutToQuit.connect(self._stop_ping_thread)
        QApplication.instance().aboutToQuit.connect(self._stop_fps_thread)

        # Interrupteur au même niveau visuel que le titre, aligné à droite
        # (header_layout() pousse tout ce qui est ajouté après son stretch interne).
        self.header_layout().addWidget(self._build_monitoring_toggle_control())

        self.content_layout().addWidget(self._build_live_row())
        # Même écart que celui, de référence, entre les tuiles CPU/RAM/GPU/
        # Disque ci-dessus (QHBoxLayout.setSpacing(12) dans _build_live_row) :
        # 6 (spacing implicite de content_layout()) + 6 = 12, au lieu des 22px
        # (6 + 16) que ce addSpacing(16) donnait avant.
        self.content_layout().addSpacing(6)

        # Plus d'écran "Analysez votre PC..." intermédiaire avant le premier
        # lancement : la mise en page des résultats est visible dès
        # l'affichage de l'onglet, juste vide (seul le bouton d'action) tant
        # qu'aucun diagnostic n'a encore tourné (voir _build_results_container).
        self._build_results_container()

        self._overlay_panel = _OverlayControlsPanel(
            self._overlay_enabled(),
            config.get("performance_overlay_elements", list(ALL_ELEMENTS)),
            int(config.get("performance_overlay_bg_opacity", 85)),
            int(config.get("performance_overlay_text_opacity", 100)),
            int(config.get("performance_overlay_font_size", 13)),
        )
        self._overlay_panel.enabled_toggled.connect(self._on_overlay_enabled_toggled)
        self._overlay_panel.settings_changed.connect(self._on_overlay_settings_changed)

        self._risk_panel = RiskControlsPanel()

        # Zone principale : bascule entre le contenu Diagnostic (inchangé),
        # le panneau Overlay et le panneau Risque selon l'onglet actif de la
        # colonne de droite — même taille/position quel que soit l'onglet
        # (un seul QStackedWidget partagé, pas une reconstruction de layout
        # à chaque bascule).
        self.section_stack = QStackedWidget()
        # Les 3 onglets partagent EXACTEMENT le même conteneur extérieur
        # (bordure + fond "card" + scrollbar, voir _build_scrollable_tab_container) :
        # leur contenu respectif (résultats du diagnostic/panneau overlay/
        # panneau risque) est donc lui-même transparent, sans sa propre
        # bordure "card" imbriquée (voir _build_results_container/
        # RiskControlsPanel), sous peine de double contour empilé au même
        # endroit.
        self._diagnostic_scroll = self._build_scrollable_tab_container(self.results_widget)
        self._section_diagnostic_index = self.section_stack.addWidget(self._diagnostic_scroll)
        self._section_overlay_index = self.section_stack.addWidget(
            self._build_scrollable_tab_container(self._overlay_panel)
        )
        self._section_risk_index = self.section_stack.addWidget(
            self._build_scrollable_tab_container(self._risk_panel)
        )

        # Superposé au-dessus de la zone de résultats (pas un widget de plus
        # dans le flux défilant) : reste ainsi toujours visible pendant tout
        # le scan, peu importe la position de défilement ou la hauteur des
        # résultats du scan précédent — un ancien QStackedWidget interne
        # pouvait se retrouver hors du cadre visible si le défilement
        # n'était pas remis à zéro (constaté : le curseur restait scrollé en
        # bas de longs résultats précédents, cachant l'animation du scan
        # suivant).
        self._build_scan_overlay()

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(12)
        bottom_row.addWidget(self.section_stack, 1)
        bottom_row.addWidget(self._build_section_tabs_column())
        self.content_layout().addLayout(bottom_row, 1)

        # Si l'overlay était actif à la fermeture précédente, il réapparaît
        # tout seul au lancement (même logique que le kill switch des macros,
        # voir page_macro.py) — sans attendre que l'utilisateur revienne sur
        # cette page (elle est déjà construite au démarrage, voir
        # MainWindow._build_pages).
        if bool(config.get("performance_overlay_enabled", False)):
            self._ensure_overlay()
            self._apply_overlay_settings()
            self._overlay.show()
            self._start_live_thread()
            self._sync_process_threads()

    # ------------------------------------------------------------------
    # Cycle de vie : le monitoring en direct tourne tant que la page est
    # affichée ET l'interrupteur activé, OU tant que l'overlay est actif
    # (lui doit continuer à se mettre à jour même quand on quitte cette page
    # pour aller jouer — voir _stop_live_thread_if_unneeded).
    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.monitoring_toggle.isChecked() or self._overlay_enabled():
            self._start_live_thread()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._stop_live_thread_if_unneeded()
        self.scan_loader.stop()

    def shutdown(self) -> None:
        """Arrêt INCONDITIONNEL et SYNCHRONE de tout ce qui pourrait encore
        tourner — appelé juste avant que cette page soit réellement détruite
        (voir MainWindow.reload_language), PAS à une simple navigation.
        hideEvent ne suffit pas ici : _stop_live_thread_if_unneeded laisse
        volontairement le monitoring/overlay actif pendant qu'on quitte
        cette page pour aller jouer — un comportement voulu en navigation
        normale, mais qui laisserait un QThread tourner pendant que son
        widget parent est détruit (Qt plante avec un qFatal
        "QThread: Destroyed while thread is still running", jamais une
        exception Python catchable — cause réelle diagnostiquée d'un
        plantage silencieux au changement de langue)."""
        self._stop_live_thread()
        self._stop_ping_thread()
        self._stop_fps_thread()
        for worker in (getattr(self, "_fix_worker", None), getattr(self, "_optimize_worker", None)):
            if worker is not None and worker.isRunning():
                worker.wait(2000)
        self._scan_overlay.hide()

    def _overlay_enabled(self) -> bool:
        return bool(config.get("performance_overlay_enabled", False))

    def _start_live_thread(self) -> None:
        if self._live_thread is None or not self._live_thread.isRunning():
            self._live_thread = LiveMonitorThread(self)
            self._live_thread.sample_ready.connect(self._on_live_sample)
            self._live_thread.sample_ready.connect(self._on_overlay_sample)
            self._live_thread.start()

    def _stop_live_thread(self) -> None:
        if self._live_thread is not None and self._live_thread.isRunning():
            self._live_thread.stop()
            self._live_thread.wait(2000)

    def _stop_live_thread_if_unneeded(self) -> None:
        if not self.monitoring_toggle.isChecked() and not self._overlay_enabled():
            self._stop_live_thread()

    def _on_monitoring_toggled(self, checked: bool) -> None:
        config.set("performance_live_monitoring_enabled", checked)
        if checked:
            self._start_live_thread()
        else:
            self._stop_live_thread_if_unneeded()
            self._reset_live_tiles()

    def _reset_live_tiles(self) -> None:
        for ring in (self.cpu_ring, self.ram_ring, self.gpu_ring):
            ring.set_placeholder()
        self.ram_caption.setText("")
        self.gpu_caption.setText("")
        self.disk_spark.clear()
        self.disk_read_label.setText("")
        self.disk_write_label.setText("")

    # ------------------------------------------------------------------
    # Monitoring en direct
    # ------------------------------------------------------------------
    def _build_monitoring_toggle_control(self) -> QWidget:
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        label = QLabel(t("page.performance.live_monitoring_label"))
        label.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {STATUS_NEUTRAL};")
        row.addWidget(label)

        initial_enabled = bool(config.get("performance_live_monitoring_enabled", True))
        self.monitoring_toggle = ToggleSwitch(checked=initial_enabled)
        self.monitoring_toggle.toggled.connect(self._on_monitoring_toggled)
        row.addWidget(self.monitoring_toggle)

        return wrapper

    # ------------------------------------------------------------------
    # Colonne de sélection de section (Diagnostic / Overlay / réservé)
    # ------------------------------------------------------------------
    def _build_section_tabs_column(self) -> QFrame:
        column = QFrame()
        column.setProperty("class", "card")

        layout = QVBoxLayout(column)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        self._section_tab_buttons: list[_NavTabButton] = []

        diagnostic_btn = _NavTabButton(_DiagnosticTabIcon(), t("page.performance.tab_diagnostic"))
        diagnostic_btn.clicked.connect(lambda: self._on_section_tab_clicked(self._section_diagnostic_index))
        layout.addWidget(diagnostic_btn)
        self._section_tab_buttons.append(diagnostic_btn)

        overlay_btn = _NavTabButton(_OverlayTabIcon(), t("page.performance.tab_overlay"))
        overlay_btn.clicked.connect(lambda: self._on_section_tab_clicked(self._section_overlay_index))
        layout.addWidget(overlay_btn)
        self._section_tab_buttons.append(overlay_btn)

        risk_btn = _NavTabButton(_RiskTabIcon(), t("page.performance.tab_risk"))
        risk_btn.clicked.connect(lambda: self._on_section_tab_clicked(self._section_risk_index))
        layout.addWidget(risk_btn)
        self._section_tab_buttons.append(risk_btn)

        reserved_btn = _NavTabButton(_ReservedTabIcon(), t("page.performance.tab_reserved"))
        reserved_btn.setEnabled(False)
        layout.addWidget(reserved_btn)
        self._section_tab_buttons.append(reserved_btn)

        layout.addStretch(1)

        # Largeur calée sur le plus long des 4 libellés (icône comprise)
        # plutôt qu'une valeur fixe devinée à la main : "Diagnostic"/"Coming
        # soon" sont des mots (ou expressions) qu'un QLabel en wordWrap ne
        # peut pas couper faute d'espace au bon endroit — une colonne trop
        # étroite les ferait déborder au lieu de les afficher proprement.
        # +10% supplémentaires demandés par-dessus ce contenu réel.
        content_width = max(btn.sizeHint().width() for btn in self._section_tab_buttons)
        column.setFixedWidth(round((content_width + 20) * 1.1))

        self._active_section_index = self._section_diagnostic_index
        self._section_tab_buttons[self._active_section_index].set_active(True)
        return column

    def _on_section_tab_clicked(self, index: int) -> None:
        if index == self._active_section_index:
            return
        self._active_section_index = index
        for i, btn in enumerate(self._section_tab_buttons):
            btn.set_active(i == index)
        self.section_stack.setCurrentIndex(index)

    # ------------------------------------------------------------------
    # Les 3 onglets (Diagnostic/Overlay/Risque) : même conteneur extérieur
    # (voir _build_scrollable_tab_container)
    # ------------------------------------------------------------------
    def _build_scrollable_tab_container(self, content: QWidget) -> QScrollArea:
        """Conteneur commun aux 3 onglets de la zone principale : bordure +
        fond "card" + barre de scroll verticale, identiques quel que soit
        l'onglet actif. `content` (résultats du diagnostic / panneau overlay
        / panneau risque) n'a lui-même aucune carte interne (juste des widgets qui
        flottent, background transparent) — le fond/contour "card" est donc
        porté par la QScrollArea elle-même (reste fixe pendant le
        défilement), jamais dupliqué à l'intérieur.

        Marge ajoutée autour de la barre de scroll (au lieu du "margin: 0px"
        global de theme.qss) : sans ça, elle reste collée directement contre
        le bord de la zone — un léger espace la détache du contour."""
        scroll = QScrollArea()
        scroll.setProperty("class", "card")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # QSS "margin" sur une QScrollBar n'a aucun effet ici (ni horizontal
        # ni vertical, vérifié) — la place réservée pour la barre ("width")
        # comme sa position (haut/bas) ne bougent pas d'un pixel quelle que
        # soit la valeur déclarée. padding-top/bottom (haut/bas de la carte,
        # nuance propre à cette page, _TAB_SCROLLBAR_VERTICAL_INSET) reste en
        # QSS : viewport ET scrollbar PARTAGENT le même espace vertical, donc
        # un padding qui rogne le contentsRect insète bien les deux ensemble
        # de façon symétrique, sans effet de bord.
        #
        # padding-right (règle globale CONTENT_SCROLLBAR_GAP, voir
        # CLAUDE.md/ui/scrollbar_style.py) N'EST PLUS ici en QSS : vérifié
        # par mesure directe de géométrie que sur une QScrollArea "nue", un
        # padding horizontal rogne le contentsRect ENTIER (viewport+scrollbar
        # empilés côte à côte) depuis le bord droit AVANT qu'ils ne se
        # partagent cet espace — le vide obtenu apparaît donc APRÈS la
        # scrollbar (entre elle et le bord de la carte), jamais ENTRE le
        # contenu et elle, qui restent accolés malgré ce padding. Seul
        # apply_viewport_scrollbar_gap (setViewportMargins, appelé après
        # setWidget ci-dessous) rétrécit réellement le viewport lui-même,
        # indépendamment de la position de la scrollbar.
        scroll.setStyleSheet(
            "QScrollArea {"
            f" padding-top: {_TAB_SCROLLBAR_VERTICAL_INSET}px;"
            f" padding-bottom: {_TAB_SCROLLBAR_VERTICAL_INSET}px;"
            " }"
        )
        scroll.viewport().setStyleSheet("background: transparent;")
        scroll.setWidget(content)
        apply_viewport_scrollbar_gap(scroll)
        # Voir _TAB_SCROLLBAR_THICKNESS : épaissit cette barre précise.
        style_scrollbar_directly(
            scroll.verticalScrollBar(),
            thickness=_TAB_SCROLLBAR_THICKNESS,
            min_handle_length=28,
        )
        return scroll

    def _ensure_overlay(self) -> None:
        if self._overlay is None:
            self._overlay = PerformanceOverlay()

    def _apply_overlay_settings(self) -> None:
        self._overlay.apply_settings(
            config.get("performance_overlay_elements", list(ALL_ELEMENTS)),
            int(config.get("performance_overlay_bg_opacity", 85)),
            int(config.get("performance_overlay_text_opacity", 100)),
            int(config.get("performance_overlay_font_size", 13)),
        )

    def _on_overlay_enabled_toggled(self, enabled: bool) -> None:
        config.set("performance_overlay_enabled", enabled)

        if enabled:
            self._ensure_overlay()
            self._apply_overlay_settings()
            self._overlay.show()
            self._start_live_thread()
        else:
            if self._overlay is not None:
                self._overlay.hide()
            self._stop_live_thread_if_unneeded()
        self._sync_process_threads()

    def _on_overlay_settings_changed(
        self, elements: list[str], bg_opacity_percent: int, text_opacity_percent: int, font_size: int
    ) -> None:
        config.set("performance_overlay_elements", elements)
        config.set("performance_overlay_bg_opacity", bg_opacity_percent)
        config.set("performance_overlay_text_opacity", text_opacity_percent)
        config.set("performance_overlay_font_size", font_size)
        if self._overlay is not None:
            self._overlay.apply_settings(elements, bg_opacity_percent, text_opacity_percent, font_size)
        self._sync_process_threads()

    def _on_overlay_sample(self, sample: LiveSample) -> None:
        if self._overlay is not None and self._overlay.isVisible():
            self._overlay.update_sample(sample)

    # ------------------------------------------------------------------
    # Ping / FPS : détectent eux-mêmes le jeu au premier plan à chaque cycle
    # (voir docstrings de ping_monitor.py/fps_monitor.py — pas de nom de
    # process à leur passer ici), tournent tant que l'overlay ET l'élément
    # correspondant sont activés — indépendamment de la visibilité de cette
    # page, comme LiveMonitorThread (voir _sync_process_threads).
    # ------------------------------------------------------------------
    def _sync_process_threads(self) -> None:
        self._sync_ping_thread()
        self._sync_fps_thread()

    def _sync_ping_thread(self) -> None:
        elements = config.get("performance_overlay_elements", list(ALL_ELEMENTS))
        want = self._overlay_enabled() and "ping" in elements

        if want and self._ping_thread is not None and self._ping_thread.isRunning():
            return
        self._stop_ping_thread()
        if want:
            self._ping_thread = PingMonitorThread(self)
            self._ping_thread.ping_ready.connect(self._on_ping_sample)
            self._ping_thread.start()

    def _stop_ping_thread(self) -> None:
        if self._ping_thread is not None:
            self._ping_thread.stop()
            self._ping_thread.wait(2000)
            self._ping_thread = None

    def _sync_fps_thread(self) -> None:
        elements = config.get("performance_overlay_elements", list(ALL_ELEMENTS))
        want = self._overlay_enabled() and "fps" in elements

        if want and self._fps_thread is not None and self._fps_thread.isRunning():
            return
        self._stop_fps_thread()
        if want:
            self._fps_thread = FpsMonitorThread(self)
            self._fps_thread.fps_ready.connect(self._on_fps_sample)
            self._fps_thread.start()

    def _stop_fps_thread(self) -> None:
        if self._fps_thread is not None:
            self._fps_thread.stop()
            self._fps_thread.wait(2000)
            self._fps_thread = None

    def _on_ping_sample(self, ping_ms) -> None:
        if self._overlay is not None and self._overlay.isVisible():
            self._overlay.update_ping(ping_ms)

    def _on_fps_sample(self, fps) -> None:
        if self._overlay is not None and self._overlay.isVisible():
            self._overlay.update_fps(fps)

    def _build_ring_tile(self, title: str) -> tuple[QFrame, RingGauge, QLabel]:
        # Structure et hauteur strictement identiques pour CPU/RAM/GPU (même
        # si la légende reste vide pour CPU) : c'est ce qui garantit que les
        # 3 anneaux soient rigoureusement à la même taille et la même position.
        frame = QFrame()
        frame.setProperty("class", "card")
        frame.setFixedHeight(_LIVE_TILE_HEIGHT)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setFixedHeight(16)
        title_label.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {STATUS_NEUTRAL};")
        layout.addWidget(title_label)

        # Stretch de part et d'autre de l'anneau : il reste centré dans
        # l'espace disponible plutôt que collé sous le titre.
        layout.addStretch(1)
        ring = RingGauge()
        layout.addWidget(ring, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)

        # Légende réservée (hauteur fixe) même quand elle reste vide (RAM) :
        # ne sert plus qu'au cas GPU indisponible, mais garde la structure
        # identique entre les 3 tuiles pour l'alignement croisé.
        caption = QLabel("")
        caption.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        caption.setWordWrap(True)
        caption.setFixedHeight(14)
        caption.setStyleSheet(f"font-size: 10.5px; color: {STATUS_NEUTRAL};")
        layout.addWidget(caption)

        return frame, ring, caption

    def _build_sparkline_tile(self, title: str) -> tuple[QFrame, SparklineWidget, QLabel, QLabel]:
        frame = QFrame()
        frame.setProperty("class", "card")
        frame.setFixedHeight(_LIVE_TILE_HEIGHT)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {STATUS_NEUTRAL};")
        layout.addWidget(title_label)

        spark = SparklineWidget()
        layout.addWidget(spark)

        legend_row = QHBoxLayout()
        read_label = QLabel("")
        read_label.setStyleSheet(f"font-size: 10px; color: {STATUS_OK};")
        write_label = QLabel("")
        write_label.setStyleSheet("font-size: 10px; color: #7DE4CF;")
        legend_row.addWidget(read_label)
        legend_row.addStretch(1)
        legend_row.addWidget(write_label)
        layout.addLayout(legend_row)

        return frame, spark, read_label, write_label

    def _build_live_row(self) -> QFrame:
        row = QFrame()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        cpu_frame, self.cpu_ring, self.cpu_caption = self._build_ring_tile(t("page.performance.live_cpu"))
        ram_frame, self.ram_ring, self.ram_caption = self._build_ring_tile(t("page.performance.live_ram"))
        gpu_frame, self.gpu_ring, self.gpu_caption = self._build_ring_tile(t("page.performance.live_gpu"))
        disk_frame, self.disk_spark, self.disk_read_label, self.disk_write_label = self._build_sparkline_tile(
            t("page.performance.live_disk")
        )

        for frame in (cpu_frame, ram_frame, gpu_frame, disk_frame):
            layout.addWidget(frame)
        return row

    def _on_live_sample(self, sample: LiveSample) -> None:
        # Le thread peut tourner uniquement pour l'overlay (page masquée ou
        # interrupteur "Monitoring en direct" éteint, voir
        # _stop_live_thread_if_unneeded) : les tuiles de CETTE page ne
        # doivent alors pas se remettre à jour toutes seules.
        if not self.monitoring_toggle.isChecked():
            return
        self.cpu_ring.set_target(sample.cpu_percent, _severity_color(sample.cpu_percent))

        # Pas de quantité en Go ici : déjà présente dans la fiche de
        # configuration du Diagnostic, inutile de la dupliquer.
        self.ram_ring.set_target(sample.ram_percent, _severity_color(sample.ram_percent))

        if sample.gpu_available and sample.gpu_percent is not None:
            self.gpu_ring.set_target(sample.gpu_percent, _severity_color(sample.gpu_percent))
            self.gpu_caption.setText("")
        else:
            self.gpu_ring.set_placeholder()
            self.gpu_caption.setText(t("page.performance.gpu_unavailable"))

        self.disk_spark.push_value(sample.disk_read_mbps + sample.disk_write_mbps)
        self.disk_read_label.setText(f"{t('page.performance.disk_read')} {sample.disk_read_mbps:.1f} Mo/s")
        self.disk_write_label.setText(f"{t('page.performance.disk_write')} {sample.disk_write_mbps:.1f} Mo/s")

    # ------------------------------------------------------------------
    # Superposition "scan en cours" : couvre la zone de résultats (pas un
    # widget de plus dans le flux défilant, voir le commentaire dans
    # __init__) pour rester toujours visible pendant tout le scan.
    # ------------------------------------------------------------------
    def _build_scan_overlay(self) -> None:
        # Parenté directe à la QScrollArea (pas au viewport) : sa géométrie
        # ne dépend donc jamais du défilement du contenu, contrairement à un
        # widget placé dans results_layout. Fond opaque de la même couleur
        # que "class=card" (#1F1F25) : cache complètement les résultats de
        # l'ancien scan pendant que le nouveau tourne.
        self._scan_overlay = QFrame(self._diagnostic_scroll)
        self._scan_overlay.setStyleSheet("background-color: #1F1F25;")
        layout = QVBoxLayout(self._scan_overlay)
        layout.addStretch(1)
        self.scan_loader = PulsingLoader()
        layout.addWidget(self.scan_loader, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
        self._scan_overlay.hide()

        # Garde la superposition alignée sur la zone visible si la fenêtre
        # est redimensionnée pendant qu'un scan tourne.
        self._diagnostic_scroll.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if watched is self._diagnostic_scroll and event.type() == event.Type.Resize:
            self._scan_overlay.setGeometry(self._diagnostic_scroll.rect())
        return super().eventFilter(watched, event)

    def _show_scan_overlay(self, visible: bool) -> None:
        if visible:
            self._scan_overlay.setGeometry(self._diagnostic_scroll.rect())
            self._scan_overlay.raise_()
            self._scan_overlay.show()
            self.scan_loader.start()
        else:
            self.scan_loader.stop()
            self._scan_overlay.hide()

    def _on_rescan_clicked(self) -> None:
        # Seul point d'entrée qui réaffiche le rectangle d'optimisation
        # (voir _hide_optimize_card ci-dessus) : le clic explicite sur
        # "Lancer l'analyse"/"Relancer le diagnostic", jamais un rescan
        # automatique déclenché ailleurs (ex: après optimisation, après la
        # correction d'une carte individuelle).
        self._hide_optimize_card = False
        self._start_scan()

    def _start_scan(self) -> None:
        live_snapshot = self._live_thread.average_sample() if self._live_thread else None
        self._show_scan_overlay(True)

        self._scan_worker = PerformanceScanWorker(live_snapshot, self)
        self._scan_worker.finished_scan.connect(self._on_scan_finished)
        self._scan_worker.start()

    # ------------------------------------------------------------------
    # Résultats — sert aussi d'état initial (avant tout premier scan) : pas
    # d'écran "Analysez votre PC..." séparé, juste ce même conteneur, vide à
    # part le bouton d'action tant qu'aucun résultat n'existe encore.
    # ------------------------------------------------------------------
    def _scan_action_button_text(self) -> str:
        # "Relancer le diagnostic" dès qu'un résultat existe déjà (généré
        # dans cette session, ou déjà en mémoire pour une raison quelconque),
        # "Lancer l'analyse" tant qu'aucun diagnostic n'a encore tourné.
        return t("page.performance.rescan_btn") if self._last_result is not None else t("page.performance.scan_btn")

    def _build_results_container(self) -> QWidget:
        # Simple QWidget (pas une QScrollArea) : le défilement est maintenant
        # géré une seule fois par le conteneur extérieur commun aux 3 onglets
        # (voir _build_scrollable_tab_container) — imbriquer une deuxième
        # QScrollArea ici donnerait deux barres de scroll indépendantes.
        self.results_widget = QWidget()
        self.results_widget.setStyleSheet("background: transparent;")
        self.results_layout = QVBoxLayout(self.results_widget)
        # Marge sur les 4 côtés (même valeur que les panneaux Overlay/Risque,
        # 12px) : sans ça, les cartes de résultats touchaient directement les
        # bords de la zone de défilement.
        self.results_layout.setContentsMargins(12, 12, 12, 12)
        self.results_layout.setSpacing(14)

        # Bouton persistant (jamais recréé/détruit, voir _render_results) :
        # seul son texte change entre "Lancer l'analyse" et "Relancer le
        # diagnostic", pas le widget lui-même.
        self.scan_action_btn = AnimatedButton(self._scan_action_button_text(), variant="secondary")
        self.scan_action_btn.clicked.connect(self._on_rescan_clicked)
        self.results_layout.addWidget(self.scan_action_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.results_layout.addStretch(1)

        return self.results_widget

    def _on_scan_finished(self, result: ScanResult) -> None:
        self._last_result = result
        self._render_results(result)
        self._show_scan_overlay(False)

    def _render_results(self, result: ScanResult) -> None:
        # Vide tout SAUF le bouton d'action (jamais détruit, juste retiré du
        # layout puis réinséré ci-dessous) : un seul et même widget avant et
        # après le premier scan, pas une recréation à chaque fois.
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self.scan_action_btn:
                widget.deleteLater()

        self.scan_action_btn.setText(self._scan_action_button_text())
        self.results_layout.addWidget(self.scan_action_btn, 0, Qt.AlignmentFlag.AlignLeft)

        # Ordre d'affichage : bloc d'optimisation groupée (juste après le
        # scan, bien visible), puis fiche de configuration, puis composant
        # limitant, puis la liste des améliorations possibles. Le bloc
        # d'optimisation est omis si _hide_optimize_card (voir son bouton
        # cliqué juste avant ce rescan, _on_optimize_clicked).
        if not self._hide_optimize_card:
            self.results_layout.addWidget(self._build_optimize_card(result))
        self.results_layout.addWidget(self._build_config_card(result))
        self.results_layout.addWidget(self._build_bottleneck_card(result))

        improvements_title = QLabel(t("page.performance.improvements_title"))
        improvements_title.setStyleSheet("font-size: 15px; font-weight: 700; color: #E7E9EE; padding-bottom: 3px;")
        self.results_layout.addWidget(improvements_title)

        if result.cards:
            for card in result.cards:
                card_widget = _StatusCardWidget(card)
                card_widget.fixed.connect(self._start_scan)
                self.results_layout.addWidget(card_widget)
        else:
            no_improvements = QLabel(t("page.performance.no_improvements"))
            no_improvements.setWordWrap(True)
            no_improvements.setStyleSheet(f"font-size: 13px; color: {STATUS_OK};")
            self.results_layout.addWidget(no_improvements)

        self.results_layout.addStretch(1)

    def _build_bottleneck_card(self, result: ScanResult) -> QFrame:
        # Une seule bordure (celle, neutre, de la classe "card" comme toutes
        # les autres cartes) : la prominence vient de la taille du texte et de
        # l'accent de couleur, pas d'un contour supplémentaire imbriqué.
        bottleneck = result.bottleneck
        frame = QFrame()
        frame.setProperty("class", "card")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        title = QLabel(t("page.performance.bottleneck_title"))
        title.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {STATUS_OK};")
        layout.addWidget(title)

        if bottleneck.component is None:
            headline = QLabel(t("performance.bottleneck.none"))
        else:
            component_label = t(_COMPONENT_LABEL_KEYS[bottleneck.component])
            headline = QLabel(component_label)
        headline.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {STATUS_OK};")
        layout.addWidget(headline)

        reason = t(bottleneck.reason_key).format(**bottleneck.reason_kwargs)
        reason_label = QLabel(reason)
        reason_label.setWordWrap(True)
        reason_label.setStyleSheet(f"font-size: 12px; color: {STATUS_NEUTRAL};")
        layout.addWidget(reason_label)

        return frame

    # ------------------------------------------------------------------
    # "Optimiser pour Roblox" : applique d'un coup toutes les corrections
    # automatiques pertinentes pour ce PC (pas juste celles du composant
    # limitant), donc dans son propre bloc plutôt que dans la carte
    # "Composant limitant" — puis affiche un résumé honnête de ce qui a
    # réellement été fait.
    # ------------------------------------------------------------------
    def _build_optimize_card(self, result: ScanResult) -> QFrame:
        frame = QFrame()
        frame.setProperty("class", "card")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        title = QLabel(t("page.performance.optimize_title"))
        title.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {STATUS_OK};")
        layout.addWidget(title)

        # Détecté à chaque (re)construction de cette carte (donc à chaque
        # scan) : le libellé du bouton ET le texte descriptif reflètent le
        # jeu réellement au premier plan à ce moment-là, pas une valeur
        # figée au démarrage de l'app. Mémorisé sur l'instance pour que
        # _show_optimize_summary sache, plus tard, si la recommandation Fast
        # Flags (pertinente seulement pour Roblox) doit s'afficher.
        detected_game = detect_foreground_game()
        self._optimize_detected_exe = detected_game[0] if detected_game is not None else None
        is_roblox = self._optimize_detected_exe == ROBLOX_EXE_NAME

        desc_key = "page.performance.optimize_desc_roblox" if is_roblox else "page.performance.optimize_desc_generic"
        desc = QLabel(t(desc_key))
        desc.setWordWrap(True)
        desc.setStyleSheet(f"font-size: 12px; color: {STATUS_NEUTRAL};")
        layout.addWidget(desc)

        optimize_row = QHBoxLayout()
        optimize_row.setSpacing(10)

        if detected_game is not None:
            btn_label = t("page.performance.optimize_btn_game").format(game=detected_game[1])
        else:
            btn_label = t("page.performance.optimize_btn_windows")

        self.optimize_btn = AnimatedButton(btn_label, variant="secondary")
        self.optimize_btn.clicked.connect(lambda: self._on_optimize_clicked(result))
        optimize_row.addWidget(self.optimize_btn)

        self._optimize_spinner = PulsingLoader(size=20)
        self._optimize_spinner.setVisible(False)
        optimize_row.addWidget(self._optimize_spinner)
        optimize_row.addStretch(1)
        layout.addLayout(optimize_row)

        # Mémorisé pour pouvoir le masquer instantanément au clic (voir
        # _on_optimize_clicked), avant même que le rescan qui suit ait eu le
        # temps de reconstruire les résultats.
        self._optimize_card_frame = frame

        return frame

    def _on_optimize_clicked(self, result: ScanResult) -> None:
        self._optimize_result = result
        fixable_ids = [c.card_id for c in result.cards if c.can_auto_fix and c.card_id in _AUTO_FIXES]

        # Masqué dès le clic (pas seulement après le rescan qui suit) : reste
        # caché jusqu'au prochain "Relancer le diagnostic" explicite (voir
        # _on_rescan_clicked et _hide_optimize_card) — y compris pendant le
        # rescan automatique lancé par _on_optimize_finished ci-dessous, qui
        # ne doit pas le faire réapparaître tout seul.
        self._hide_optimize_card = True
        self._optimize_card_frame.setVisible(False)

        if not fixable_ids:
            self._show_optimize_summary([])
            return

        if not show_confirm(
            self, t("dialog.security_warning_title"), t("page.performance.optimize_confirm_text"),
            confirm_label=t("page.performance.optimize_confirm_btn"),
        ):
            return

        self.optimize_btn.setEnabled(False)
        self._optimize_spinner.setVisible(True)
        self._optimize_spinner.start()

        self._optimize_worker = _OptimizeWorker(fixable_ids, self)
        self._optimize_worker.finished_all.connect(self._on_optimize_finished)
        self._optimize_worker.start()

    def _on_optimize_finished(self, results: list) -> None:
        self._optimize_spinner.stop()
        self._optimize_spinner.setVisible(False)
        self.optimize_btn.setEnabled(True)

        self._show_optimize_summary(results)
        # Reflète les changements qu'on vient d'appliquer (cartes corrigées
        # qui disparaissent, composant limitant recalculé, etc.).
        self._start_scan()

    def _show_optimize_summary(self, results: list) -> None:
        result = self._optimize_result
        card_titles = {c.card_id: c.title_key for c in result.cards}

        lines = []
        for card_id, success in results:
            label = t(card_titles.get(card_id, card_id))
            if success:
                text = t("page.performance.optimize_action_ok").format(label=label)
                lines.append(f'<span style="color:{STATUS_OK};">{text}</span>')
            else:
                text = t("page.performance.optimize_action_failed").format(label=label)
                lines.append(f'<span style="color:{STATUS_CRITICAL};">{text}</span>')

        if lines:
            body = "<p>" + "<br>".join(lines) + "</p>"
        else:
            body = f"<p>{t('page.performance.optimize_none_needed')}</p>"

        # La recommandation de preset Fast Flags n'a de sens que pour Roblox
        # (les Fast Flags sont un mécanisme propre au client Roblox) : pour
        # tout autre jeu détecté, ou si aucun jeu connu n'est au premier
        # plan (libellé neutre "Optimiser pour Windows"), on s'arrête aux 4
        # corrections Windows génériques ci-dessus, sans cette section.
        is_roblox = self._optimize_detected_exe == ROBLOX_EXE_NAME
        if is_roblox:
            # Le preset Fast Flags le plus adapté est recommandé, pas
            # appliqué : la lecture/écriture réelle de ClientAppSettings.json
            # n'existe pas encore (Partie 2.2 du brief, pas encore
            # construite) — on ne fait jamais semblant d'avoir fait quelque
            # chose de réel.
            preset_name = t(_PRESET_NAME_KEYS.get(result.recommended_preset, "page.fastflags.preset_balanced"))
            body += (
                f'<p style="color:{STATUS_NEUTRAL};">'
                f'{t("page.performance.optimize_preset_line").format(preset=preset_name)}</p>'
            )

        msg = QMessageBox(self)
        msg.setWindowTitle(t("page.performance.optimize_summary_title"))
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(body)
        msg.exec()

        if is_roblox:
            reason = t(result.bottleneck.reason_key).format(**result.bottleneck.reason_kwargs)
            self.boost_requested.emit(result.recommended_preset, reason)

    def _build_config_card(self, result: ScanResult) -> QFrame:
        specs = result.specs
        frame = QFrame()
        frame.setProperty("class", "card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel(t("page.performance.config_title"))
        title.setStyleSheet("font-size: 15px; font-weight: 700; color: #E7E9EE; padding-bottom: 3px;")
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)

        # Le 4e élément (mono) marque les identifiants techniques (hash de
        # version, chaîne de pilote) où une police à connotation terminal
        # aide la lecture — un accent ponctuel, pas la police de toute la carte.
        rows = [
            (t("page.performance.config_cpu"), specs.cpu_name or "?", False),
            (t("page.performance.config_gpu"), specs.gpu_name or "?", False),
            (t("page.performance.config_ram"), f"{specs.ram_total_gb:.1f} Go" if specs.ram_total_gb else "?", False),
            (t("page.performance.config_os"), specs.os_caption or "?", False),
            (t("page.performance.config_resolution"), specs.screen_resolution or "?", False),
            (
                t("page.performance.config_roblox_version"),
                specs.roblox_version_folder or t("performance.card.roblox.desc_missing"),
                bool(specs.roblox_version_folder),
            ),
            (
                t("page.performance.config_gpu_driver"),
                f"{specs.gpu_driver_version or '?'} ({specs.gpu_driver_date or '?'})",
                bool(specs.gpu_driver_version),
            ),
        ]
        for row_index, (label_text, value_text, mono) in enumerate(rows):
            label = QLabel(label_text)
            label.setStyleSheet(f"font-size: 12px; color: {STATUS_NEUTRAL};")
            value = QLabel(str(value_text))
            value.setWordWrap(True)
            font_family = ' font-family: "Consolas", "Courier New", monospace;' if mono else ""
            value.setStyleSheet(f"font-size: 12px; color: #E7E9EE; font-weight: 600;{font_family}")
            grid.addWidget(label, row_index, 0)
            grid.addWidget(value, row_index, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        note = QLabel(t("page.performance.config_gpu_driver_note"))
        note.setWordWrap(True)
        note.setStyleSheet(f"font-size: 11px; color: {STATUS_NEUTRAL};")
        layout.addWidget(note)

        return frame
