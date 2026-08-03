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
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from core.config import config
from core.i18n import t
from features.performance.fixes import disable_game_dvr, disable_sysmain, enable_game_mode, set_power_plan_high_performance
from features.performance.live_monitor import LiveMonitorThread, LiveSample
from features.performance.scan import PerformanceScanWorker, ScanResult
from features.performance.status_cards import StatusCard
from ui.animated_button import AnimatedButton
from ui.pages.base_page import BasePage
from ui.ring_gauge import RingGauge
from ui.status_colors import STATUS_CRITICAL, STATUS_NEUTRAL, STATUS_OK, STATUS_WARNING
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


def _severity_color(value: float) -> str:
    if value >= _RING_CRITICAL_PERCENT:
        return STATUS_CRITICAL
    if value >= _RING_WARNING_PERCENT:
        return STATUS_WARNING
    return STATUS_OK


class PowerIcon(QWidget):
    """Symbole "power" (⏻) dessiné en vectoriel (arc + trait), jamais en
    caractère Unicode/emoji — cercle englobant qui délimite toute la zone
    cliquable, avec le glyphe marche/arrêt (arc ouvert + trait) à l'intérieur."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(_HERO_SIZE, _HERO_SIZE)
        self._color = QColor(STATUS_OK)

    def set_hovered(self, hovered: bool) -> None:
        self._color = QColor("#1BDAB3") if hovered else QColor(STATUS_OK)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Cercle englobant : délimite toute la zone cliquable du bouton.
        # Contour plus épais que la première version.
        painter.setPen(QPen(QColor(self._color.red(), self._color.green(), self._color.blue(), 110), 3.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        boundary_rect = QRectF(3.5, 3.5, self.width() - 7, self.height() - 7)
        painter.drawEllipse(boundary_rect)

        # Glyphe power (arc ouvert + trait), avec plus d'air par rapport au
        # contour englobant qu'avant (marge augmentée).
        painter.setPen(QPen(self._color, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        margin = self.width() * 0.27
        glyph_rect = QRectF(margin, margin, self.width() - 2 * margin, self.height() - 2 * margin)
        # Ouverture de ~70deg centrée en haut (90deg) : trace les 290deg restants.
        painter.drawArc(glyph_rect, int(125 * 16), int(290 * 16))

        center_x = self.width() / 2
        top_y = glyph_rect.top() - 1
        stem_y = glyph_rect.top() + glyph_rect.height() * 0.45
        painter.drawLine(QPointF(center_x, top_y), QPointF(center_x, stem_y))


class _PowerButton(QWidget):
    """Icône power + texte, cliquable, en turquoise — remplace le bouton
    rectangulaire pour lancer le premier scan."""

    clicked = pyqtSignal()

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.icon = PowerIcon()
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignHCenter)

        self.label = QLabel(text)
        self.label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.label.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {STATUS_OK};")
        layout.addWidget(self.label)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:
        self.icon.set_hovered(True)
        self.label.setStyleSheet("font-size: 22px; font-weight: 700; color: #1BDAB3;")
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.icon.set_hovered(False)
        self.label.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {STATUS_OK};")
        super().leaveEvent(event)


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
        title.setStyleSheet("font-size: 14px; font-weight: 700; color: #E7E9EE;")
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

            self.fix_btn = AnimatedButton(t("page.performance.auto_fix_btn"), variant="primary")
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

        self._live_thread: LiveMonitorThread | None = None
        self._scan_worker: PerformanceScanWorker | None = None
        self._last_result: ScanResult | None = None

        QApplication.instance().aboutToQuit.connect(self._stop_live_thread)

        # Interrupteur au même niveau visuel que le titre, aligné à droite
        # (header_layout() pousse tout ce qui est ajouté après son stretch interne).
        self.header_layout().addWidget(self._build_monitoring_toggle_control())

        self.content_layout().addWidget(self._build_monitoring_status_label())
        self.content_layout().addWidget(self._build_live_row())
        self.content_layout().addSpacing(16)

        self.scan_stack = QStackedWidget()
        self._empty_index = self.scan_stack.addWidget(self._build_empty_state())
        self._scanning_index = self.scan_stack.addWidget(self._build_scanning_state())
        self._results_index = self.scan_stack.addWidget(self._build_results_container())
        self.content_layout().addWidget(self.scan_stack, 1)

    # ------------------------------------------------------------------
    # Cycle de vie : le monitoring en direct ne tourne que page affichée
    # ET interrupteur activé — jamais de polling sans les deux à la fois.
    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.monitoring_toggle.isChecked():
            self._start_live_thread()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._stop_live_thread()
        self.scan_loader.stop()

    def _start_live_thread(self) -> None:
        if self._live_thread is None or not self._live_thread.isRunning():
            self._live_thread = LiveMonitorThread(self)
            self._live_thread.sample_ready.connect(self._on_live_sample)
            self._live_thread.start()

    def _stop_live_thread(self) -> None:
        if self._live_thread is not None and self._live_thread.isRunning():
            self._live_thread.stop()
            self._live_thread.wait(2000)

    def _on_monitoring_toggled(self, checked: bool) -> None:
        config.set("performance_live_monitoring_enabled", checked)
        if checked:
            self._start_live_thread()
        else:
            self._stop_live_thread()
            self._reset_live_tiles()
        self.monitoring_status_label.setVisible(not checked)

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

    def _build_monitoring_status_label(self) -> QLabel:
        initial_enabled = bool(config.get("performance_live_monitoring_enabled", True))
        self.monitoring_status_label = QLabel(t("page.performance.live_monitoring_off"))
        self.monitoring_status_label.setStyleSheet(f"font-size: 11px; color: {STATUS_NEUTRAL};")
        self.monitoring_status_label.setVisible(not initial_enabled)
        return self.monitoring_status_label

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
    # État vide (avant le premier scan)
    # ------------------------------------------------------------------
    def _build_empty_state(self) -> QFrame:
        # Squelette identique à _build_scanning_state (mêmes marges/espacement,
        # même texte en haut, même stretch de part et d'autre du "hero" :
        # c'est ce qui garantit que le loader du scan apparaisse exactement à
        # la même position/taille que ce bouton, plutôt qu'ailleurs à l'écran.
        frame = QFrame()
        frame.setProperty("class", "card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        desc = QLabel(t("page.performance.empty_desc"))
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        desc.setStyleSheet(f"font-size: 13px; color: {STATUS_NEUTRAL};")
        layout.addWidget(desc)

        layout.addStretch(1)

        scan_btn = _PowerButton(t("page.performance.scan_btn"))
        scan_btn.clicked.connect(self._start_scan)
        layout.addWidget(scan_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addStretch(1)
        return frame

    # ------------------------------------------------------------------
    # État "scan en cours"
    # ------------------------------------------------------------------
    def _build_scanning_state(self) -> QFrame:
        frame = QFrame()
        frame.setProperty("class", "card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        desc = QLabel(t("page.performance.empty_desc"))
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        desc.setStyleSheet(f"font-size: 13px; color: {STATUS_NEUTRAL};")
        layout.addWidget(desc)

        layout.addStretch(1)

        # Juste l'animation (cercle + vagues), aucun texte pendant le scan.
        self.scan_loader = PulsingLoader()
        layout.addWidget(self.scan_loader, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addStretch(1)
        return frame

    def _start_scan(self) -> None:
        live_snapshot = self._live_thread.average_sample() if self._live_thread else None
        self.scan_stack.setCurrentIndex(self._scanning_index)
        self.scan_loader.start()

        self._scan_worker = PerformanceScanWorker(live_snapshot, self)
        self._scan_worker.finished_scan.connect(self._on_scan_finished)
        self._scan_worker.start()

    # ------------------------------------------------------------------
    # Résultats
    # ------------------------------------------------------------------
    def _build_results_container(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # QScrollArea peint sa propre viewport avec la couleur de palette Qt
        # par défaut (pas #1A1A1F) tant qu'on ne la force pas transparente —
        # c'est ce qui donnait l'impression que les cartes du bas avaient un
        # fond différent de celles du haut.
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self.results_widget = QWidget()
        self.results_widget.setStyleSheet("background: transparent;")
        self.results_layout = QVBoxLayout(self.results_widget)
        self.results_layout.setContentsMargins(0, 0, 12, 0)
        self.results_layout.setSpacing(14)

        scroll.setWidget(self.results_widget)
        scroll.viewport().setStyleSheet("background: transparent;")
        return scroll

    def _on_scan_finished(self, result: ScanResult) -> None:
        self.scan_loader.stop()
        self._last_result = result
        self._render_results(result)
        self.scan_stack.setCurrentIndex(self._results_index)

    def _render_results(self, result: ScanResult) -> None:
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        rescan_btn = AnimatedButton(t("page.performance.rescan_btn"), variant="secondary")
        rescan_btn.clicked.connect(self._start_scan)
        self.results_layout.addWidget(rescan_btn, 0, Qt.AlignmentFlag.AlignLeft)

        # Ordre d'affichage : bloc d'optimisation groupée (juste après le
        # scan, bien visible), puis fiche de configuration, puis composant
        # limitant, puis la liste des améliorations possibles.
        self.results_layout.addWidget(self._build_optimize_card(result))
        self.results_layout.addWidget(self._build_config_card(result))
        self.results_layout.addWidget(self._build_bottleneck_card(result))

        improvements_title = QLabel(t("page.performance.improvements_title"))
        improvements_title.setStyleSheet("font-size: 15px; font-weight: 700; color: #E7E9EE;")
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

        desc = QLabel(t("page.performance.optimize_desc"))
        desc.setWordWrap(True)
        desc.setStyleSheet(f"font-size: 12px; color: {STATUS_NEUTRAL};")
        layout.addWidget(desc)

        optimize_row = QHBoxLayout()
        optimize_row.setSpacing(10)

        self.optimize_btn = AnimatedButton(t("page.performance.optimize_btn"), variant="primary")
        self.optimize_btn.clicked.connect(lambda: self._on_optimize_clicked(result))
        optimize_row.addWidget(self.optimize_btn)

        self._optimize_spinner = PulsingLoader(size=20)
        self._optimize_spinner.setVisible(False)
        optimize_row.addWidget(self._optimize_spinner)
        optimize_row.addStretch(1)
        layout.addLayout(optimize_row)

        return frame

    def _on_optimize_clicked(self, result: ScanResult) -> None:
        self._optimize_result = result
        fixable_ids = [c.card_id for c in result.cards if c.can_auto_fix and c.card_id in _AUTO_FIXES]

        if not fixable_ids:
            self._show_optimize_summary([])
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

        # Le preset Fast Flags le plus adapté est recommandé, pas appliqué :
        # la lecture/écriture réelle de ClientAppSettings.json n'existe pas
        # encore (Partie 2.2 du brief, pas encore construite) — on ne fait
        # jamais semblant d'avoir fait quelque chose de réel.
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
        title.setStyleSheet("font-size: 15px; font-weight: 700; color: #E7E9EE;")
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
