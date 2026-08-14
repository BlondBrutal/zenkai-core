"""
Page Custom Script : bibliothèque de scripts AutoHotkey v2 personnalisés,
collés/importés en texte (jamais de binaire), analysés (heuristique
synchrone + scan Windows Defender asynchrone) avant tout premier lancement,
activés/désactivés par script via un interrupteur dédié. Toute la logique
non-UI (persistance, analyse, détection de l'interpréteur, lancement
dé-élevé, arrêt fiable) vit dans features/custom_script/ — cette page se
contente d'orchestrer et d'afficher.
"""
import logging
import os
import uuid
from datetime import datetime

from PyQt6.QtCore import QRectF, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QPlainTextEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from core.config import config
from core.i18n import t
from core.security_log import Category, log_event
from features.custom_script import ahk_detect
from features.custom_script.defender_scan import DefenderScanResult, scan_file
from features.custom_script.heuristics import analyze_script
from features.custom_script.process_manager import RunningScript, start_script, stop_script, write_companion_ahk_file
from features.custom_script.script_store import (
    CustomScriptEntry, ScriptAnalysis, delete_script, export_script, is_analysis_current, list_scripts, save_script,
)
from ui.animated_button import AnimatedButton
from ui.pages.base_page import BasePage
from ui.scrollbar_style import apply_viewport_scrollbar_gap, style_scrollbar_directly
from ui.status_colors import STATUS_CRITICAL, STATUS_NEUTRAL, STATUS_OK, STATUS_WARNING
from ui.styled_message_box import show_confirm, show_high_risk_confirm, show_warning
from ui.toggle_switch import ToggleSwitch

logger = logging.getLogger("zenkaiontop.custom_script")

_SEVERITY_COLORS = {
    "none": STATUS_OK, "moderate": STATUS_WARNING, "severe": STATUS_CRITICAL, "pending": STATUS_NEUTRAL,
}
_SEVERITY_BADGE_KEYS = {
    "none": "page.custom_script.badge_none", "moderate": "page.custom_script.badge_moderate",
    "severe": "page.custom_script.badge_severe", "pending": "page.custom_script.badge_pending",
}
_SEVERITY_BADGE_COMPACT_KEYS = {
    "none": "page.custom_script.badge_compact_none", "moderate": "page.custom_script.badge_compact_moderate",
    "severe": "page.custom_script.badge_compact_severe", "pending": "page.custom_script.badge_compact_pending",
}

_ROW_BADGE_WIDTH = 48
_ROW_NAME_MAX_CHARS = 16  # marges/espacement resserrés (voir _ScriptRowWidget) : un peu plus de place pour le nom

# Même menu contextuel stylé que celui de la Bibliothèque de macros (voir
# ui/pages/page_macro.py::_build_styled_menu) — copie locale volontaire,
# cohérente avec la convention déjà en place de légère duplication de ce
# petit helper plutôt que de le factoriser prématurément.
_CONTEXT_MENU_QSS = """
QMenu {
    background-color: #202027;
    color: #E7E9EE;
    border: 1px solid #17B897;
    border-radius: 8px;
    padding: 4px;
    font-size: 9px;
}
QMenu::item {
    padding: 4px 12px;
    border-radius: 6px;
}
QMenu::item:selected {
    background-color: transparent;
    color: #17B897;
}
"""


def _build_styled_menu(parent: QWidget) -> QMenu:
    menu = QMenu(parent)
    menu.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    menu.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
    menu.setStyleSheet(_CONTEXT_MENU_QSS)
    return menu


def _elide_right(text: str, max_chars: int) -> str:
    """Troncature par NOMBRE DE CARACTÈRES (pas QFontMetrics.elidedText()) —
    voir ui/pages/page_settings.py::_LogRowWidget pour le bug de
    chevauchement Qt déjà diagnostiqué que cette technique évite."""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _effective_severity(entry: CustomScriptEntry) -> str:
    """Combine le verdict heuristique et celui de Defender. "pending" si
    l'analyse ne correspond plus au texte actuel du script (exigence de
    ré-analyse après modification)."""
    if not is_analysis_current(entry):
        return "pending"
    severity = entry.analysis.heuristic_severity
    if entry.analysis.defender_clean is False:
        severity = "severe"  # un vrai hit Defender ne redescend jamais en dessous de "severe"
    return severity


class PulsingLoader(QWidget):
    """Copie locale de ui/pages/page_performance.py::PulsingLoader — même
    convention de légère duplication que _build_styled_menu ci-dessus,
    plutôt qu'un couplage entre deux pages pour un petit QWidget
    autonome."""

    _COLOR = QColor(23, 184, 151)
    _TRACK_COLOR = QColor(255, 255, 255, 30)
    _SPAN_DEGREES = 100
    _DEGREES_PER_TICK = 6

    def __init__(self, size: int = 18, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
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


class _ScriptRowWidget(QWidget):
    """Ligne de la bibliothèque : nom (extensible, tronqué) + badge de
    sévérité compact (coloré, texte seul — jamais de pastille remplie, voir
    CLAUDE.md/convention déjà établie ailleurs dans l'app) + interrupteur
    ON/OFF. Même technique que _LogRowWidget (ui/pages/page_settings.py,
    lignes ~136-206), déjà déboguée dans ce projet pour exactement ce
    besoin : troncature par caractères, setMinimumWidth(0) sur la colonne
    extensible, largeurs fixes prudentes, AUCUN "background: transparent"
    explicite sur ce widget (a causé un bug de rémanence visuelle distinct
    ailleurs)."""

    def __init__(self, name: str, severity: str, checked: bool, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        # Marge gauche à 8px (pas 4) : même écart bord-texte que les autres
        # listes Bibliothèque de l'app (Fast Flags, Macro), qui s'appuient
        # sur le padding "6px 8px" app-wide de QListWidget::item (voir
        # theme.qss) — ici ce padding est neutralisé (mis à 0 sur la liste,
        # voir _build_library_column) à cause du bug de double-padding déjà
        # rencontré, donc la marge gauche doit être portée explicitement
        # par ce widget de ligne pour rester visuellement identique.
        # Spacing réduit (4, pas 8) entre nom/badge/interrupteur : libère de
        # la place pour le nom, qui reste la colonne extensible/prioritaire.
        layout.setContentsMargins(8, 2, 4, 2)
        layout.setSpacing(4)

        name_label = QLabel(_elide_right(name, _ROW_NAME_MAX_CHARS))
        name_label.setStyleSheet("color: #E7E9EE; font-size: 12px;")
        name_label.setMinimumWidth(0)
        layout.addWidget(name_label, 1, Qt.AlignmentFlag.AlignVCenter)

        badge_label = QLabel(t(_SEVERITY_BADGE_COMPACT_KEYS[severity]))
        badge_label.setFixedWidth(_ROW_BADGE_WIDTH)
        badge_label.setStyleSheet(f"color: {_SEVERITY_COLORS[severity]}; font-size: 10px; font-weight: 700;")
        layout.addWidget(badge_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.toggle = ToggleSwitch(checked=checked)
        layout.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignVCenter)


class _ScriptAnalysisDialog(QDialog):
    """Résultat d'analyse d'un Custom Script, en fenêtre SÉPARÉE — même
    principe que "Voir les logs" (_SecurityLogDialog, ui/pages/
    page_settings.py) : simple QDialog modal, jamais affiché inline sous
    l'éditeur. Ouverte automatiquement juste après "Enregistrer"/
    "Réanalyser" (le scan Defender, déjà démarré en tâche de fond avant
    l'ouverture, continue de tourner pendant que la fenêtre est affichée —
    voir CustomScriptPage._show_analysis_dialog) et peut être rouverte à
    tout moment via le bouton "Voir l'analyse" pour le script chargé."""

    def __init__(self, entry: CustomScriptEntry, scanning: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("page.custom_script.analysis_dialog_title"))
        # Largeur fixe (pour un habillage de texte lisible), hauteur PAS
        # imposée : self.adjustSize() (appelé à la fin de __init__ et de
        # chaque update_for_entry) calcule la hauteur réelle nécessaire au
        # contenu affiché, au lieu d'une taille fixe surdimensionnée avec un
        # grand vide quand il y a peu de findings.
        self.setFixedWidth(420)
        self.setStyleSheet("background-color: #1A1A1F;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        name_label = QLabel(entry.name)
        name_label.setStyleSheet("font-size: 14px; font-weight: 700; color: #E7E9EE; padding-bottom: 3px;")
        layout.addWidget(name_label)

        badge_row = QHBoxLayout()
        badge_row.setSpacing(8)
        self._spinner = PulsingLoader(size=18)
        badge_row.addWidget(self._spinner)
        self.severity_badge = QLabel("")
        self.severity_badge.setStyleSheet("font-size: 12px; font-weight: 700;")
        badge_row.addWidget(self.severity_badge)
        badge_row.addStretch(1)
        layout.addLayout(badge_row)

        self.findings_label = QLabel("")
        self.findings_label.setWordWrap(True)
        self.findings_label.setStyleSheet(f"font-size: 11.5px; color: {STATUS_NEUTRAL};")
        layout.addWidget(self.findings_label)

        self.ahk_missing_label = QLabel(t("page.custom_script.ahk_missing_text"))
        self.ahk_missing_label.setWordWrap(True)
        self.ahk_missing_label.setStyleSheet(f"font-size: 11.5px; color: {STATUS_WARNING};")
        self.ahk_missing_label.setVisible(ahk_detect.health_check() != "ok")
        layout.addWidget(self.ahk_missing_label)

        # Disclaimer PERMANENT (jamais fermable) — jamais de message
        # "script sûr" sans nuance.
        disclaimer_label = QLabel(t("page.custom_script.disclaimer"))
        disclaimer_label.setWordWrap(True)
        disclaimer_label.setStyleSheet(f"font-size: 11px; color: {STATUS_NEUTRAL};")
        layout.addWidget(disclaimer_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        close_btn = QPushButton(t("page.custom_script.close_btn"))
        close_btn.setProperty("class", "secondaryButton")
        close_btn.clicked.connect(self.close)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

        self.update_for_entry(entry, scanning=scanning)

    def update_for_entry(self, entry: CustomScriptEntry, scanning: bool = False) -> None:
        self.ahk_missing_label.setVisible(ahk_detect.health_check() != "ok")

        if scanning:
            self._spinner.setVisible(True)
            self._spinner.start()
        else:
            self._spinner.stop()
            self._spinner.setVisible(False)

        severity = _effective_severity(entry) if entry.analysis is not None else "pending"
        self.severity_badge.setText(t(_SEVERITY_BADGE_KEYS[severity]))
        self.severity_badge.setStyleSheet(
            f"font-size: 12px; font-weight: 700; color: {_SEVERITY_COLORS[severity]};"
        )

        if entry.analysis is None:
            self.findings_label.setText("")
        else:
            finding_lines = [t(key) for key in entry.analysis.heuristic_finding_keys]
            if scanning:
                finding_lines.append(t("page.custom_script.scan_in_progress"))
            elif entry.analysis.defender_available and entry.analysis.defender_clean is False:
                finding_lines.append(t("page.custom_script.defender_not_clean"))
            elif not entry.analysis.defender_available:
                finding_lines.append(t("page.custom_script.defender_unavailable"))
            self.findings_label.setText("\n".join(finding_lines))

        # Recalcule la hauteur au contenu réel à chaque mise à jour (le
        # nombre de lignes de findings/la visibilité de ahk_missing_label
        # peuvent changer entre l'ouverture et la fin du scan Defender).
        self.adjustSize()


class _DefenderScanWorker(QThread):
    """QThread simple, calqué sur _FixWorker/_OptimizeWorker de
    page_performance.py : jamais d'exception qui remonte, le résultat part
    toujours par le signal."""

    finished_scan = pyqtSignal(str, object)  # (zkscript_path, DefenderScanResult)

    def __init__(self, zkscript_path: str, ahk_path: str, parent=None):
        super().__init__(parent)
        self._zkscript_path = zkscript_path
        self._ahk_path = ahk_path

    def run(self) -> None:
        try:
            result = scan_file(self._ahk_path)
        except Exception:
            logger.exception("Échec inattendu pendant le scan Defender")
            result = DefenderScanResult(available=True, clean=None, exit_code=None, raw_output="")
        self.finished_scan.emit(self._zkscript_path, result)


class CustomScriptPage(BasePage):
    def __init__(self, parent=None):
        super().__init__(t("page.custom_script.title"), "", parent)
        self.add_info_badge(t("page.custom_script.subtitle"))

        self._current_path: str | None = None
        self._current_entry: CustomScriptEntry | None = None
        self._entries: dict[str, tuple[str, CustomScriptEntry]] = {}
        self._running: dict[str, RunningScript] = {}
        self._defender_worker: _DefenderScanWorker | None = None
        self._analysis_dialog: _ScriptAnalysisDialog | None = None
        self._analysis_dialog_entry_id: str | None = None

        self.header_layout().addWidget(self._build_kill_switch_control())

        margins = self.content_layout().contentsMargins()
        self.content_layout().setContentsMargins(margins.left(), margins.top(), 16, margins.bottom())

        main_row = QHBoxLayout()
        # Espacement normal (16px, comme le reste de l'app) : le résultat
        # d'analyse vit désormais dans une fenêtre séparée (_ScriptAnalysisDialog),
        # plus besoin d'une QScrollArea de page pour absorber sa croissance —
        # la colonne éditeur remplit directement l'espace vertical disponible,
        # même principe que le tableau de la page Fast Flags.
        main_row.setSpacing(16)
        main_row.addWidget(self._build_editor_column(), 1)
        main_row.addWidget(self._build_library_column())
        self.content_layout().addLayout(main_row, 1)

        self._refresh_library()

        QApplication.instance().aboutToQuit.connect(self._stop_all_running_scripts)

    # ------------------------------------------------------------------
    # Interrupteur global : coupe d'un coup tous les scripts actifs. Même
    # pattern que MacroPage._build_kill_switch_control (macros_globally_enabled).
    # ------------------------------------------------------------------
    def _build_kill_switch_control(self) -> QWidget:
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        label = QLabel(t("page.custom_script.kill_switch_label"))
        label.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {STATUS_NEUTRAL};")
        row.addWidget(label)

        initial_enabled = bool(config.get("custom_scripts_globally_enabled", True))
        self.kill_switch = ToggleSwitch(checked=initial_enabled)
        self.kill_switch.toggled.connect(self._on_kill_switch_toggled)
        row.addWidget(self.kill_switch)
        return wrapper

    def _on_kill_switch_toggled(self, checked: bool) -> None:
        config.set("custom_scripts_globally_enabled", checked)
        if not checked:
            self._stop_all_running_scripts()
            self._refresh_library()

    # ------------------------------------------------------------------
    # Colonne éditeur
    # ------------------------------------------------------------------
    def _build_editor_column(self) -> QWidget:
        wrapper = QWidget()
        wrapper.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Une seule ligne (nom + actions), même principe que le top_row de
        # Fast Flags (recherche + "Ajouter un flag" + "Parcourir les flags",
        # voir page_fastflags.py::_build_editor_column) : le champ prend tout
        # l'espace disponible (stretch=1), les boutons suivent à droite, sans
        # stretch final. Hauteur/padding laissés au défaut standard
        # d'AnimatedButton (voir ui/animated_button.py, calé sur les boutons
        # QSS du haut de Fast Flags), plus besoin de les fixer ici.
        # font_pixel_size=13 reste explicite (matche la police du QLineEdit
        # voisin, indépendant de la hauteur du bouton).
        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(t("page.custom_script.name_placeholder"))
        top_row.addWidget(self.name_input, 1)

        self.import_btn = AnimatedButton(t("page.custom_script.import_btn"), variant="neutral", font_pixel_size=13)
        self.import_btn.clicked.connect(self._on_import_clicked)
        top_row.addWidget(self.import_btn)

        # "Exporter" (pas "Nouveau") : même comportement/logique que
        # "Exporter" en bibliothèque Macro/Fast Flags — exporte l'élément
        # actuellement SÉLECTIONNÉ dans la Bibliothèque (voir
        # _on_export_clicked), pas le contenu de l'éditeur. "Nouveau" reste
        # une méthode interne (_on_new_clicked, appelée par _on_delete_entry
        # pour vider l'éditeur si le script supprimé y était chargé) mais n'a
        # plus de bouton dédié.
        self.export_btn = AnimatedButton(t("page.custom_script.export_btn"), variant="neutral", font_pixel_size=13)
        self.export_btn.clicked.connect(self._on_export_clicked)
        top_row.addWidget(self.export_btn)
        layout.addLayout(top_row)

        self.script_edit = QPlainTextEdit()
        # Remplit tout l'espace vertical disponible (stretch=1 ci-dessous),
        # comme le tableau de la page Fast Flags entre son en-tête et ses
        # boutons du bas — plus de hauteur fixe : le résultat d'analyse vit
        # désormais dans une fenêtre séparée (_ScriptAnalysisDialog), rien
        # ne vient plus comprimer l'éditeur qui aurait justifié de le figer.
        # Sa propre scrollbar interne reste légitime pour un script dont le
        # texte dépasse l'espace visible (contrairement à l'ancienne
        # scrollbar de PAGE, retirée) — espace texte/scrollbar toujours
        # réservé (règle globale, voir CLAUDE.md/ui/scrollbar_style.py).
        apply_viewport_scrollbar_gap(self.script_edit)
        style_scrollbar_directly(self.script_edit.verticalScrollBar())
        layout.addWidget(self.script_edit, 1)

        # Ligne d'actions alignée à DROITE (stretch AVANT les boutons, pas
        # après) — dernière ligne de la colonne, donc en bas à droite de sa
        # zone. Le résultat d'analyse ne s'affiche plus ici : il vit dans
        # _ScriptAnalysisDialog, une fenêtre séparée (même principe que
        # "Voir les logs"), ouverte automatiquement après "Enregistrer" (voir
        # _analyze_and_save) — plus de bouton "Analyser" séparé, l'analyse se
        # déclenche déjà automatiquement à l'enregistrement.
        bottom_button_row = QHBoxLayout()
        bottom_button_row.setSpacing(10)
        bottom_button_row.addStretch(1)
        # Toujours activé (contrairement à un premier essai qui le
        # désactivait tant qu'aucun script n'était chargé) : l'état
        # "disabled" d'AnimatedButton peint une bordure claire
        # (STATUS_NEUTRAL, #9BA1AB) au lieu du contour gris #33333C des
        # autres boutons — visuellement incohérent juste à côté des autres.
        # Le handler gère déjà le no-op si rien n'est chargé, donc rien à
        # perdre à le laisser actif en permanence.
        self.save_btn = AnimatedButton(t("page.custom_script.save_btn"), variant="neutral")
        self.save_btn.clicked.connect(self._on_save_clicked)
        bottom_button_row.addWidget(self.save_btn)
        self.reset_btn = AnimatedButton(t("page.custom_script.reset_btn"), variant="neutral")
        self.reset_btn.clicked.connect(self._on_reset_clicked)
        bottom_button_row.addWidget(self.reset_btn)
        layout.addLayout(bottom_button_row)

        return wrapper

    # ------------------------------------------------------------------
    # Fenêtre séparée "Résultat de l'analyse" (voir _ScriptAnalysisDialog)
    # ------------------------------------------------------------------
    def _show_analysis_dialog(self, entry: CustomScriptEntry, scanning: bool = False) -> None:
        self._analysis_dialog = _ScriptAnalysisDialog(entry, scanning=scanning, parent=self)
        self._analysis_dialog_entry_id = entry.id
        self._analysis_dialog.finished.connect(self._on_analysis_dialog_closed)
        self._analysis_dialog.exec()

    def _on_analysis_dialog_closed(self, _result: int) -> None:
        self._analysis_dialog = None
        self._analysis_dialog_entry_id = None

    # ------------------------------------------------------------------
    # Enregistrer / Analyser / Réinitialiser / Nouveau / Importer
    # ------------------------------------------------------------------
    def _on_save_clicked(self) -> None:
        name = self.name_input.text().strip()
        text = self.script_edit.toPlainText()
        if not name or not text.strip():
            show_warning(self, t("page.custom_script.title"), t("page.custom_script.save_empty_error"))
            return
        self._analyze_and_save(name, text)

    def _on_reset_clicked(self) -> None:
        # Bouton "Réinitialiser" : vide juste le texte de l'éditeur, sans
        # toucher au nom du script ni au script actuellement chargé.
        self.script_edit.clear()

    def _analyze_and_save(self, name: str, text: str) -> None:
        entry = self._current_entry or CustomScriptEntry(
            id=uuid.uuid4().hex, name=name, script_text=text, created_at=_now_iso(), updated_at="",
        )
        entry.name = name
        entry.script_text = text

        heuristic = analyze_script(text)  # synchrone, instantané
        entry.analysis = ScriptAnalysis(
            heuristic_severity=heuristic.severity,
            heuristic_categories=list(heuristic.categories),
            heuristic_finding_keys=heuristic.finding_keys,
            defender_available=False, defender_clean=None, defender_exit_code=None,
            analyzed_hash=entry.content_hash(), analyzed_at=_now_iso(), unlocked=False,
        )
        log_event("custom_script_heuristic_scan", Category.SCRIPT_SCAN, entry.name, "ok")

        self._current_path = save_script(entry, existing_path=self._current_path)
        self._current_entry = entry
        self._refresh_library()
        # Le thread démarre AVANT l'ouverture de la fenêtre modale : il
        # continue de tourner en tâche de fond pendant que la fenêtre est
        # affichée (une QDialog.exec() ne bloque que le thread appelant,
        # jamais les autres threads — voir _on_defender_scan_finished qui
        # met à jour la fenêtre en place si elle est encore ouverte).
        self._start_defender_scan(entry)
        self._show_analysis_dialog(entry, scanning=True)

    def _start_defender_scan(self, entry: CustomScriptEntry) -> None:
        ahk_path = write_companion_ahk_file(entry, self._current_path)
        self._defender_worker = _DefenderScanWorker(self._current_path, ahk_path, self)
        self._defender_worker.finished_scan.connect(self._on_defender_scan_finished)
        self._defender_worker.start()

    def _on_defender_scan_finished(self, zkscript_path: str, result: DefenderScanResult) -> None:
        entries_by_path = {path: entry for path, entry in self._entries.values()}
        entry = entries_by_path.get(zkscript_path)
        if entry is None or entry.analysis is None:
            return

        entry.analysis.defender_available = result.available
        entry.analysis.defender_clean = result.clean
        entry.analysis.defender_exit_code = result.exit_code
        save_script(entry, existing_path=zkscript_path)

        if result.available:
            log_event(
                "custom_script_defender_scan", Category.SCRIPT_SCAN, entry.name,
                "ok" if result.clean else "error",
            )

        self._refresh_library()
        if self._current_path == zkscript_path:
            self._current_entry = entry
        if self._analysis_dialog is not None and self._analysis_dialog_entry_id == entry.id:
            self._analysis_dialog.update_for_entry(entry, scanning=False)

    def _on_new_clicked(self) -> None:
        self._current_path = None
        self._current_entry = None
        self.name_input.clear()
        self.script_edit.clear()

    def _on_import_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, t("page.custom_script.import_btn"), "", "AutoHotkey Script (*.ahk)",
        )
        if not path:
            return
        try:
            with open(path, "rb") as f:
                raw = f.read()
            if raw[:2] == b"MZ" or b"\x00" in raw[:4096]:
                raise ValueError("binary_content")
            text = raw.decode("utf-8", errors="replace")
        except Exception:
            show_warning(self, t("page.custom_script.import_btn"), t("page.custom_script.import_error_binary"))
            return
        self.script_edit.setPlainText(text)
        if not self.name_input.text().strip():
            self.name_input.setText(os.path.splitext(os.path.basename(path))[0])

    # ------------------------------------------------------------------
    # Bibliothèque
    # ------------------------------------------------------------------
    def _build_library_column(self) -> QFrame:
        column = QFrame()
        column.setProperty("class", "card")
        column.setFixedWidth(260)

        layout = QVBoxLayout(column)
        layout.setContentsMargins(13, 13, 13, 13)
        layout.setSpacing(6)

        title = QLabel(t("page.custom_script.library_title"))
        title.setStyleSheet("font-size: 14px; font-weight: 700; color: #E7E9EE; padding-bottom: 3px;")
        layout.addWidget(title)

        self.library_list = QListWidget()
        # Surcharge locale (pas touché à theme.qss, qui reste inchangé pour
        # les autres listes de l'app) : le style app-wide de QListWidget::item
        # a un padding vertical de 6px ET un fond turquoise translucide au
        # survol/à la sélection (voir theme.qss) — ici, la ligne porte déjà
        # son propre contenu peint (badge coloré, interrupteur), donc ce fond
        # est un aplat de couleur superflu (contraire à la philosophie du
        # design system : jamais de fond plein au clic/survol, seuls texte et
        # badge doivent rester visibles). Le padding QSS s'ajoutait en plus
        # des marges internes de _ScriptRowWidget, ce qui réduisait l'espace
        # vertical réellement dispo pour l'interrupteur (24px de haut) dans
        # les 34px de la ligne, au point de le faire paraître coupé en haut —
        # padding remis à 0 ici, les marges de _ScriptRowWidget suffisent.
        self.library_list.setStyleSheet(
            "QListWidget::item { padding: 0px; }"
            "QListWidget::item:hover { background-color: transparent; }"
            "QListWidget::item:selected { background-color: transparent; }"
        )
        self.library_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Espace entre le contenu (badge, interrupteur) et la scrollbar —
        # règle globale, voir CLAUDE.md/ui/scrollbar_style.py.
        apply_viewport_scrollbar_gap(self.library_list)
        self.library_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.library_list.customContextMenuRequested.connect(self._on_library_context_menu)
        # Cliquer une ligne (hors interrupteur, qui capte lui-même son clic)
        # la charge dans l'éditeur pour consultation/modification — le
        # script reste toujours visible/modifiable, jamais une boîte noire.
        self.library_list.itemClicked.connect(self._on_library_item_clicked)
        layout.addWidget(self.library_list, 1)

        return column

    def _refresh_library(self) -> None:
        self.library_list.clear()
        self._entries = {}
        for path, entry in list_scripts():
            self._entries[entry.id] = (path, entry)
            severity = _effective_severity(entry)
            checked = entry.id in self._running
            row_widget = _ScriptRowWidget(entry.name, severity, checked)
            row_widget.toggle.toggled.connect(
                lambda checked, entry_id=entry.id, row=row_widget: self._on_script_toggled(entry_id, checked, row)
            )
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            item.setSizeHint(QSize(0, 34))
            self.library_list.addItem(item)
            self.library_list.setItemWidget(item, row_widget)

    def _on_library_item_clicked(self, item: QListWidgetItem) -> None:
        entry_id = item.data(Qt.ItemDataRole.UserRole)
        result = self._entries.get(entry_id)
        if result is None:
            return
        path, entry = result
        self._current_path = path
        self._current_entry = entry
        self.name_input.setText(entry.name)
        self.script_edit.setPlainText(entry.script_text)

    def _on_library_context_menu(self, pos) -> None:
        item = self.library_list.itemAt(pos)
        if item is None:
            return
        self.library_list.setCurrentItem(item)
        entry_id = item.data(Qt.ItemDataRole.UserRole)

        menu = _build_styled_menu(self.library_list)
        delete_action = menu.addAction(t("page.custom_script.library_delete_btn"))
        chosen = menu.exec(self.library_list.viewport().mapToGlobal(pos))
        if chosen is delete_action:
            self._on_delete_entry(entry_id)

    def _on_delete_entry(self, entry_id: str) -> None:
        result = self._entries.get(entry_id)
        if result is None:
            return
        path, entry = result
        running = self._running.pop(entry_id, None)
        if running is not None:
            stop_script(running)
        delete_script(path)
        if self._current_path == path:
            self._on_new_clicked()
        self._refresh_library()

    def _on_export_clicked(self) -> None:
        """Exporte l'élément actuellement SÉLECTIONNÉ dans la Bibliothèque
        (pas le contenu de l'éditeur) — même comportement que "Exporter" en
        bibliothèque Macro/Fast Flags (voir page_macro.py::_on_export_clicked)."""
        item = self.library_list.currentItem()
        if item is None:
            return
        entry_id = item.data(Qt.ItemDataRole.UserRole)
        result = self._entries.get(entry_id)
        if result is None:
            return
        source_path, entry = result
        dest_path, _ = QFileDialog.getSaveFileName(
            self, t("page.custom_script.export_btn"), f"{entry.name}.zkscript", "Zenkai Script (*.zkscript)"
        )
        if not dest_path:
            return
        export_script(source_path, dest_path)

    # ------------------------------------------------------------------
    # ON/OFF — cœur de la logique de sécurité (voir CLAUDE.md /
    # features/custom_script/heuristics.py pour les deux paliers)
    # ------------------------------------------------------------------
    def _on_script_toggled(self, entry_id: str, checked: bool, row_widget: _ScriptRowWidget) -> None:
        result = self._entries.get(entry_id)
        if result is None:
            row_widget.toggle.setChecked(False, animate=False)
            return
        path, entry = result

        if checked:
            if not bool(config.get("custom_scripts_globally_enabled", True)):
                row_widget.toggle.setChecked(False, animate=False)
                return
            if not is_analysis_current(entry):
                row_widget.toggle.setChecked(False, animate=False)
                show_warning(self, t("page.custom_script.title"), t("page.custom_script.warn_not_analyzed"))
                return
            if ahk_detect.health_check() != "ok":
                row_widget.toggle.setChecked(False, animate=False)
                show_warning(
                    self, t("page.custom_script.ahk_missing_title"), t("page.custom_script.ahk_missing_text"),
                )
                return

            severity = _effective_severity(entry)
            if severity == "severe" and not entry.analysis.unlocked:
                confirmed = show_high_risk_confirm(
                    self, t("dialog.security_warning_title"), t("page.custom_script.warn_severe"),
                    confirm_label=t("page.custom_script.launch_confirm_btn"),
                )
                if not confirmed:
                    row_widget.toggle.setChecked(False, animate=False)
                    return
                entry.analysis.unlocked = True
                save_script(entry, existing_path=path)
                log_event("custom_script_unlock", Category.SCRIPT_EXECUTION, entry.name, "ok")
            elif severity == "moderate":
                if not show_confirm(
                    self, t("dialog.security_warning_title"), t("page.custom_script.warn_moderate"),
                    confirm_label=t("page.custom_script.launch_confirm_btn"),
                ):
                    row_widget.toggle.setChecked(False, animate=False)
                    return
            # severity == "none" : lancement direct, sans confirmation supplémentaire

            running, error_detail = start_script(entry, path)
            if running is None:
                row_widget.toggle.setChecked(False, animate=False)
                if error_detail:
                    show_warning(
                        self, t("page.custom_script.title"),
                        t("page.custom_script.launch_failed_detail").format(detail=error_detail),
                    )
                else:
                    show_warning(self, t("page.custom_script.title"), t("page.custom_script.launch_failed"))
                return
            self._running[entry_id] = running
            if self._current_path == path:
                self._current_entry = entry
        else:
            running = self._running.pop(entry_id, None)
            if running is not None and not stop_script(running):
                show_warning(self, t("page.custom_script.title"), t("page.custom_script.stop_failed"))

    def _stop_all_running_scripts(self) -> None:
        for entry_id, running in list(self._running.items()):
            stop_script(running)
            self._running.pop(entry_id, None)

    def shutdown(self) -> None:
        """Arrêt INCONDITIONNEL et SYNCHRONE de tout ce qui pourrait encore
        tourner — appelé juste avant que cette page soit réellement détruite
        (voir MainWindow.reload_language), pas seulement masquée. Un scan
        Defender en cours (_defender_worker) est laissé finir (best-effort,
        borné à 2s comme les autres arrêts synchrones de ce projet — jamais
        interrompu de force, un scan antivirus tué au milieu n'a pas de
        sens) plutôt que détruit en cours de route."""
        self._stop_all_running_scripts()
        if self._defender_worker is not None and self._defender_worker.isRunning():
            self._defender_worker.wait(2000)
