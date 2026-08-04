"""
Sidebar latérale : logo en haut, boutons de navigation, bouton Paramètres
(engrenage) épinglé en bas — pattern standard type Discord/Spotify/VS Code.
"""
import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget, QPushButton, QFrame, QLabel, QButtonGroup

from core.i18n import t
from ui.status_colors import STATUS_OK

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")

NAV_ITEMS = [
    ("license", "nav.license"),
    ("performance", "nav.performance"),
    ("macro", "nav.macro"),
    ("fastflags", "nav.fastflags"),
    ("cursor", "nav.cursor"),
]

# Pages accessibles même sans licence active (voir Sidebar.set_locked)
_ALWAYS_UNLOCKED = {"license", "settings"}


class _NavButton(QPushButton):
    """Bouton de nav avec un indicateur "actif" en trait vertical court
    (pas la hauteur du bouton entier) et un petit espace par rapport au bord
    de la fenêtre, plutôt que la bordure QSS d'origine qui touchait le bord."""

    _INDICATOR_WIDTH = 3
    _INDICATOR_HEIGHT = 16
    _INDICATOR_MARGIN_LEFT = 6

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setProperty("class", "navButton")
        self.setCheckable(True)

        self.indicator = QFrame(self)
        self.indicator.setStyleSheet(f"background-color: {STATUS_OK}; border-radius: 1.5px; border: none;")
        self.indicator.setFixedSize(self._INDICATOR_WIDTH, self._INDICATOR_HEIGHT)
        self.indicator.hide()

        self.toggled.connect(self.indicator.setVisible)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        y = (self.height() - self._INDICATOR_HEIGHT) // 2
        self.indicator.move(self._INDICATOR_MARGIN_LEFT, y)


class Sidebar(QWidget):
    page_requested = pyqtSignal(str)  # émet la clé de la page à afficher

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(165)  # ~17.5% plus étroit que les 200px d'origine

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        header_row = QWidget()
        header_row.setObjectName("sidebarLogo")
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(12, 12, 12, 12)
        header_layout.setSpacing(8)

        logo_label = QLabel()
        logo_path = os.path.join(ASSETS_DIR, "logo", "logo_64.png")
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path).scaled(
                50, 50, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            logo_label.setPixmap(pixmap)
        header_layout.addWidget(logo_label)

        brand_column = QVBoxLayout()
        brand_column.setContentsMargins(0, 0, 0, 0)
        brand_column.setSpacing(0)
        for word in ("Zenkai", "Core"):
            word_label = QLabel(word)
            # -15% par rapport à la taille précédente (22px), un peu trop
            # imposante une fois affichée réellement.
            word_label.setStyleSheet(f"color: {STATUS_OK}; font-size: 19px; font-weight: 700;")
            brand_column.addWidget(word_label)
        brand_widget = QWidget()
        brand_widget.setLayout(brand_column)
        header_layout.addWidget(brand_widget, 0, Qt.AlignmentFlag.AlignVCenter)
        header_layout.addStretch(1)

        layout.addWidget(header_row)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}

        for key, label_key in NAV_ITEMS:
            btn = _NavButton(t(label_key))
            btn.clicked.connect(lambda _checked, k=key: self.page_requested.emit(k))
            layout.addWidget(btn)
            self.nav_group.addButton(btn)
            self._buttons[key] = btn

        layout.addStretch(1)

        self.settings_button = QPushButton(t("nav.settings"))
        self.settings_button.setObjectName("settingsButton")
        self.settings_button.setFixedHeight(36)
        self.settings_button.clicked.connect(lambda: self.page_requested.emit("settings"))
        layout.addWidget(self.settings_button)

        # Sélectionne la première page par défaut
        if NAV_ITEMS:
            self._buttons[NAV_ITEMS[0][0]].setChecked(True)

    def select(self, key: str) -> None:
        btn = self._buttons.get(key)
        if btn is not None:
            btn.setChecked(True)

    def retranslate(self) -> None:
        """Rafraîchit les textes après un changement de langue (la sidebar,
        contrairement aux pages, n'est pas reconstruite — elle doit donc
        retraduire ses propres textes explicitement)."""
        for key, label_key in NAV_ITEMS:
            self._buttons[key].setText(t(label_key))
        self.settings_button.setText(t("nav.settings"))

    def set_locked(self, locked: bool) -> None:
        """Active/désactive les sections qui nécessitent une licence valide.
        License et Paramètres restent toujours accessibles."""
        tooltip = t("nav.locked_tooltip") if locked else ""
        for key, btn in self._buttons.items():
            if key in _ALWAYS_UNLOCKED:
                continue
            btn.setEnabled(not locked)
            btn.setToolTip(tooltip)
