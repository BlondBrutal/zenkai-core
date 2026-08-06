"""
Page Paramètres : langue de l'application (Partie 3.2 du brief). Les
sections Communauté/À propos viendront dans une étape ultérieure.

Le changement de langue est appliqué à chaud, sans redémarrage : cette page
se contente de persister le choix et d'émettre language_changed, et c'est
MainWindow.reload_language() qui reconstruit toutes les pages dans la
nouvelle langue (voir ui/main_window.py) — pas de fermeture de l'app ni
d'action manuelle demandée à l'utilisateur.
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from core.config import config
from core.i18n import get_language, set_language, t
from ui.pages.base_page import BasePage
from ui.segmented_toggle import SegmentedToggle
from ui.status_colors import STATUS_NEUTRAL
from ui.toggle_switch import ToggleSwitch

_LANGUAGES = [("fr", "FR"), ("en", "EN")]


class SettingsPage(BasePage):
    language_changed = pyqtSignal(str)
    always_on_top_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(t("page.settings.title"), "", parent)
        self.add_info_badge(t("page.settings.placeholder"))

        self.content_layout().addWidget(self._build_general_section())
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

    def _on_language_changed(self, code: str) -> None:
        if code == get_language():
            return
        set_language(code)
        config.set("language", code)
        self.language_changed.emit(code)

    def _on_always_on_top_toggled(self, checked: bool) -> None:
        config.set("always_on_top", checked)
        self.always_on_top_changed.emit(checked)
