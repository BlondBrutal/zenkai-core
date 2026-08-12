"""
Page Paramètres : langue de l'application (Partie 3.2 du brief) et journal
de sécurité (actions sensibles journalisées par l'app — voir
core/security_log.py). Les sections Communauté/À propos viendront dans une
étape ultérieure.

Le changement de langue est appliqué à chaud, sans redémarrage : cette page
se contente de persister le choix et d'émettre language_changed, et c'est
MainWindow.reload_language() qui reconstruit toutes les pages dans la
nouvelle langue (voir ui/main_window.py) — pas de fermeture de l'app ni
d'action manuelle demandée à l'utilisateur.
"""
import logging
import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QVBoxLayout, QWidget,
)

from core.config import config
from core.i18n import get_language, set_language, t
from core.paths import get_logs_dir
from core.security_log import read_events
from ui.animated_button import AnimatedButton
from ui.pages.base_page import BasePage
from ui.segmented_toggle import SegmentedToggle
from ui.status_colors import STATUS_NEUTRAL, STATUS_WARNING
from ui.styled_message_box import show_warning
from ui.toggle_switch import ToggleSwitch

logger = logging.getLogger("zenkaiontop.settings")

_LANGUAGES = [("fr", "FR"), ("en", "EN")]

# Même fond que le reste de l'app (voir CLAUDE.md, design system) : un
# QDialog nu utilise sinon la palette Qt par défaut (fond blanc).
_APP_BACKGROUND = "#1A1A1F"

# Code d'action (voir core/security_log.py::log_event, ex. "protocol_register")
# -> clé de traduction du libellé humain affiché dans le journal. Un code
# absent de ce dict (nouveau type d'action ajouté ailleurs sans mise à jour
# ici) retombe simplement sur son propre code brut, jamais une exception.
_ACTION_LABEL_KEYS = {
    "protocol_register": "page.settings.security_log_action.protocol_register",
    "protocol_unregister": "page.settings.security_log_action.protocol_unregister",
    "fastflags_backup": "page.settings.security_log_action.fastflags_backup",
    "fastflags_restore": "page.settings.security_log_action.fastflags_restore",
    "fastflags_inject": "page.settings.security_log_action.fastflags_inject",
    "uac_elevation": "page.settings.security_log_action.uac_elevation",
    "fix_power_plan": "page.settings.security_log_action.fix_power_plan",
    "fix_game_mode": "page.settings.security_log_action.fix_game_mode",
    "fix_game_dvr": "page.settings.security_log_action.fix_game_dvr",
    "fix_sysmain": "page.settings.security_log_action.fix_sysmain",
}


class _SecurityLogDialog(QDialog):
    """Popup "Voir les logs" : liste en lecture seule des actions sensibles
    déjà journalisées (core/security_log.py), les plus récentes en premier —
    même gabarit qu'une popup existante de la page Fast Flags
    (_KnownFlagsDialog) : simple QDialog + QListWidget stylé par le thème
    global (fond/bordure/coins arrondis 8px déjà définis dans theme.qss,
    aucune feuille de style supplémentaire nécessaire ici). Les lignes
    "sensibles" ressortent uniquement par leur couleur de texte
    (STATUS_WARNING) : jamais d'icône/emoji sur un statut, voir CLAUDE.md."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("page.settings.security_log_dialog_title"))
        self.resize(560, 440)
        self.setStyleSheet(f"background-color: {_APP_BACKGROUND};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        events = read_events()

        if events:
            list_widget = QListWidget()
            for event in events:
                label = t(_ACTION_LABEL_KEYS.get(event.action, event.action))
                result_label = (
                    t("page.settings.security_log_result_ok") if event.result == "ok"
                    else t("page.settings.security_log_result_error")
                )
                item = QListWidgetItem(f"{event.timestamp}   {label}   {event.target}   {result_label}")
                if event.sensitive:
                    item.setForeground(QColor(STATUS_WARNING))
                list_widget.addItem(item)
            layout.addWidget(list_widget, 1)
        else:
            empty_label = QLabel(t("page.settings.security_log_empty"))
            empty_label.setWordWrap(True)
            empty_label.setStyleSheet(f"font-size: 13px; color: {STATUS_NEUTRAL};")
            layout.addWidget(empty_label, 1, Qt.AlignmentFlag.AlignTop)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        close_btn = QPushButton(t("page.settings.security_log_close_btn"))
        close_btn.setProperty("class", "secondaryButton")
        close_btn.clicked.connect(self.close)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)


class SettingsPage(BasePage):
    language_changed = pyqtSignal(str)
    always_on_top_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(t("page.settings.title"), "", parent)
        self.add_info_badge(t("page.settings.placeholder"))

        self.content_layout().addWidget(self._build_general_section())
        self.content_layout().addWidget(self._build_security_section())
        self.content_layout().addStretch(1)

    def _build_general_section(self) -> QWidget:
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel(t("page.settings.section_general"))
        title.setStyleSheet("font-size: 15px; font-weight: 700; color: #E7E9EE;")
        layout.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(10)
        label = QLabel(t("page.settings.language"))
        label.setStyleSheet(f"font-size: 13px; color: {STATUS_NEUTRAL};")
        row.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.language_switch = SegmentedToggle(_LANGUAGES, get_language())
        self.language_switch.valueChanged.connect(self._on_language_changed)
        row.addWidget(self.language_switch, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)
        layout.addLayout(row)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        top_label = QLabel(t("page.settings.always_on_top"))
        top_label.setStyleSheet(f"font-size: 13px; color: {STATUS_NEUTRAL};")
        top_row.addWidget(top_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.always_on_top_toggle = ToggleSwitch(checked=bool(config.get("always_on_top", False)))
        self.always_on_top_toggle.toggled.connect(self._on_always_on_top_toggled)
        top_row.addWidget(self.always_on_top_toggle, 0, Qt.AlignmentFlag.AlignVCenter)
        top_row.addStretch(1)
        layout.addLayout(top_row)

        return section

    def _build_security_section(self) -> QWidget:
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel(t("page.settings.section_security"))
        title.setStyleSheet("font-size: 15px; font-weight: 700; color: #E7E9EE;")
        layout.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(10)

        self.view_logs_btn = AnimatedButton(t("page.settings.view_logs_btn"), variant="neutral")
        self.view_logs_btn.clicked.connect(self._on_view_logs_clicked)
        row.addWidget(self.view_logs_btn)

        self.open_logs_folder_btn = AnimatedButton(t("page.settings.open_logs_folder_btn"), variant="neutral")
        self.open_logs_folder_btn.clicked.connect(self._on_open_logs_folder_clicked)
        row.addWidget(self.open_logs_folder_btn)

        row.addStretch(1)
        layout.addLayout(row)

        return section

    def _on_view_logs_clicked(self) -> None:
        # Reconstruite à chaque clic (pas d'instance persistante) : la
        # liste doit refléter les toutes dernières actions journalisées,
        # même si une action sensible vient de se produire entre deux
        # ouvertures de cette popup.
        _SecurityLogDialog(self).exec()

    def _on_open_logs_folder_clicked(self) -> None:
        # os.startfile (Windows uniquement, comme le reste de l'app) ouvre
        # l'explorateur directement sur ce dossier — jamais bloquant, jamais
        # fatal si ça échoue (dossier supprimé manuellement, etc.).
        try:
            os.startfile(get_logs_dir())
        except OSError as exc:
            logger.error("Impossible d'ouvrir le dossier des logs (%s)", exc)
            show_warning(
                self,
                t("page.settings.open_logs_folder_error_title"),
                t("page.settings.open_logs_folder_error"),
            )

    def _on_language_changed(self, code: str) -> None:
        if code == get_language():
            return
        set_language(code)
        config.set("language", code)
        self.language_changed.emit(code)

    def _on_always_on_top_toggled(self, checked: bool) -> None:
        config.set("always_on_top", checked)
        self.always_on_top_changed.emit(checked)
