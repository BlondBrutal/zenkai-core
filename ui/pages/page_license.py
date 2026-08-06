"""
Page Licence : saisie de la clé au premier lancement, puis vérification en
ligne (registre central via Gist GitHub) à chaque démarrage et à la demande,
avec une grâce hors-ligne de 3 jours si le réseau est indisponible.
Voir Partie 4 du brief.

Le check initial n'est PAS lancé dans __init__ : c'est MainWindow qui appelle
run_startup_check() une fois le signal license_validated connecté, pour être
certain de ne rater aucun état (le thread réseau ne doit jamais émettre dans
le vide).
"""
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from core.i18n import t
from core.static_config import load_json_config
from features.license.license_manager import LicenseCheckWorker, LicenseStatus, validate_key_format
from features.license.license_store import clear_license, load_license
from ui.pages.base_page import BasePage
from ui.status_colors import STATUS_CRITICAL, STATUS_NEUTRAL, STATUS_OK, STATUS_WARNING

_UNLOCKED_STATUSES = {LicenseStatus.VALID, LicenseStatus.VALID_OFFLINE_GRACE}
_KEY_MAX_LENGTH = len("ZK-XXXX-XXXX-XXXX")

# Le statut n'est plus signalé par un emoji mais par la couleur du texte
# (sobre, façon interface pro) : teal = actif, ambre = avertissement, rouge = bloqué.
_STATUS_COLOR_NEUTRAL = STATUS_NEUTRAL
_STATUS_COLOR_OK = STATUS_OK
_STATUS_COLOR_WARN = STATUS_WARNING
_STATUS_COLOR_BLOCKED = STATUS_CRITICAL

_STATUS_COLORS = {
    LicenseStatus.VALID: _STATUS_COLOR_OK,
    LicenseStatus.VALID_OFFLINE_GRACE: _STATUS_COLOR_WARN,
    LicenseStatus.DEACTIVATED: _STATUS_COLOR_BLOCKED,
    LicenseStatus.NOT_FOUND: _STATUS_COLOR_BLOCKED,
    LicenseStatus.OFFLINE_EXPIRED: _STATUS_COLOR_BLOCKED,
    LicenseStatus.REGISTRY_ERROR: _STATUS_COLOR_WARN,
}


class LicensePage(BasePage):
    license_validated = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(t("page.license.title"), "", parent)
        self.add_info_badge(t("page.license.placeholder"))

        # Marge droite réduite (32 -> 16), comme la page Macro (référence) :
        # cohérence de largeur de contenu entre toutes les pages (voir aussi
        # page_performance.py/page_cursor.py/page_fastflags.py).
        margins = self.content_layout().contentsMargins()
        self.content_layout().setContentsMargins(margins.left(), margins.top(), 16, margins.bottom())

        self._worker = None  # référence gardée pour éviter le garbage collection pendant le run()

        # --- Formulaire de saisie (première activation / changement de clé) ---
        self.entry_frame = QFrame()
        self.entry_frame.setProperty("class", "card")
        entry_layout = QVBoxLayout(self.entry_frame)
        entry_layout.setContentsMargins(20, 18, 20, 18)
        entry_layout.setSpacing(10)

        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText(t("page.license.key_placeholder"))
        self.key_input.setMaxLength(_KEY_MAX_LENGTH)
        self.key_input.textChanged.connect(self._on_key_input_changed)
        self.key_input.returnPressed.connect(self._on_activate_clicked)
        entry_layout.addWidget(self.key_input)

        self.activate_btn = QPushButton(t("page.license.activate_btn"))
        self.activate_btn.setProperty("class", "primaryButton")
        self.activate_btn.clicked.connect(self._on_activate_clicked)
        entry_layout.addWidget(self.activate_btn)

        self.content_layout().addWidget(self.entry_frame)

        # --- Carte de statut (clé déjà enregistrée) ---
        self.status_frame = QFrame()
        self.status_frame.setProperty("class", "card")
        status_layout = QVBoxLayout(self.status_frame)
        status_layout.setContentsMargins(20, 18, 20, 18)
        status_layout.setSpacing(10)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        status_layout.addWidget(self.status_label)

        buttons_row = QHBoxLayout()
        self.recheck_btn = QPushButton(t("page.license.recheck_btn"))
        self.recheck_btn.setProperty("class", "secondaryButton")
        self.recheck_btn.clicked.connect(self._start_saved_check)
        buttons_row.addWidget(self.recheck_btn)

        self.change_key_btn = QPushButton(t("page.license.change_key_btn"))
        self.change_key_btn.setProperty("class", "secondaryButton")
        self.change_key_btn.clicked.connect(self._on_change_key_clicked)
        buttons_row.addWidget(self.change_key_btn)
        buttons_row.addStretch(1)
        status_layout.addLayout(buttons_row)

        self.content_layout().addWidget(self.status_frame)

        # --- Message d'erreur / info commun (langage humain, jamais de jargon technique) ---
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #FF6B6B; font-size: 12px;")
        self.content_layout().addWidget(self.error_label)

        self.content_layout().addStretch(1)

        local = load_license()
        if local and local.get("key"):
            self._show_status_mode()
            self._set_status_text(t("page.license.checking"))
        else:
            self._show_entry_mode()

    # ------------------------------------------------------------------
    # Appelé une seule fois par MainWindow, après connexion du signal
    # ------------------------------------------------------------------
    def run_startup_check(self) -> None:
        local = load_license()
        if local and local.get("key"):
            self._start_saved_check()
        else:
            self.license_validated.emit(False)

    # ------------------------------------------------------------------
    # Bascule entre le formulaire de saisie et la carte de statut
    # ------------------------------------------------------------------
    def _show_entry_mode(self) -> None:
        self.entry_frame.setVisible(True)
        self.status_frame.setVisible(False)
        self.error_label.setText("")

    def _show_status_mode(self) -> None:
        self.entry_frame.setVisible(False)
        self.status_frame.setVisible(True)
        self.error_label.setText("")

    def _on_key_input_changed(self, text: str) -> None:
        upper = text.upper()
        if upper != text:
            cursor_pos = self.key_input.cursorPosition()
            self.key_input.blockSignals(True)
            self.key_input.setText(upper)
            self.key_input.setCursorPosition(cursor_pos)
            self.key_input.blockSignals(False)

    # ------------------------------------------------------------------
    # Activation d'une nouvelle clé (formulaire)
    # ------------------------------------------------------------------
    def _on_activate_clicked(self) -> None:
        key = self.key_input.text().strip().upper()
        if not validate_key_format(key):
            self.error_label.setText(t("page.license.invalid_format"))
            return

        self.error_label.setText(t("page.license.checking"))
        self.activate_btn.setEnabled(False)

        worker = LicenseCheckWorker(key=key)
        worker.finished_check.connect(self._on_activation_finished)
        self._worker = worker
        worker.start()

    def _on_activation_finished(self, result) -> None:
        self.activate_btn.setEnabled(True)
        unlocked = result.status in _UNLOCKED_STATUSES
        if unlocked:
            self._show_status_mode()
            self._set_status_text(self._build_status_message(result), _STATUS_COLORS.get(result.status))
        else:
            self.error_label.setText(self._build_status_message(result))
        self.license_validated.emit(unlocked)

    def _on_change_key_clicked(self) -> None:
        clear_license()
        self.key_input.clear()
        self._show_entry_mode()
        self.license_validated.emit(False)

    # ------------------------------------------------------------------
    # Vérification de la clé déjà enregistrée (démarrage + bouton Revérifier)
    # ------------------------------------------------------------------
    def _start_saved_check(self) -> None:
        self.recheck_btn.setEnabled(False)
        self._set_status_text(t("page.license.checking"))

        worker = LicenseCheckWorker(key=None)
        worker.finished_check.connect(self._on_saved_check_finished)
        self._worker = worker
        worker.start()

    def _on_saved_check_finished(self, result) -> None:
        self.recheck_btn.setEnabled(True)

        if result.status == LicenseStatus.NO_KEY:
            # Ne devrait pas arriver ici (on ne lance ce check que si une clé
            # locale existe), mais on ne prend aucun risque de rester bloqué.
            self._show_entry_mode()
            self.license_validated.emit(False)
            return

        self._set_status_text(self._build_status_message(result), _STATUS_COLORS.get(result.status))
        if result.status in (LicenseStatus.DEACTIVATED, LicenseStatus.NOT_FOUND):
            self.error_label.setText(self._contact_hint_text())
        else:
            self.error_label.setText("")

        self.license_validated.emit(result.status in _UNLOCKED_STATUSES)

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------
    def _build_status_message(self, result) -> str:
        if result.status == LicenseStatus.VALID:
            base = t("page.license.status_active")
            return f"{base} — {result.nom}" if result.nom else base
        if result.status == LicenseStatus.VALID_OFFLINE_GRACE:
            base = t("page.license.status_grace").format(days=result.days_left or 0)
            return f"{base} — {result.nom}" if result.nom else base
        if result.status == LicenseStatus.DEACTIVATED:
            return t("page.license.status_deactivated")
        if result.status == LicenseStatus.NOT_FOUND:
            return t("page.license.status_not_found")
        if result.status == LicenseStatus.OFFLINE_EXPIRED:
            return t("page.license.status_offline_expired")
        return t("page.license.status_registry_error")

    def _contact_hint_text(self) -> str:
        url = load_json_config("community_links.json").get("discord_url", "")
        return t("page.license.contact_hint").format(url=url) if url else ""

    def _set_status_text(self, text: str, color: str = _STATUS_COLOR_NEUTRAL) -> None:
        self.status_label.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {color};")
        self.status_label.setText(text)
