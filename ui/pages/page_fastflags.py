"""
Page FastFlagsPage — squelette pour l'étape de scaffolding.
La logique réelle (lecture/écriture de ClientAppSettings.json, presets,
import/export) sera implémentée à son tour, dans l'ordre défini par le prompt.

show_recommendation() est le seul point d'accroche déjà câblé : la page
Performance calcule quel preset (Hard/Balanced) convient le mieux à ce PC et
l'envoie ici plutôt que de dupliquer cette logique — pour l'instant on
l'affiche juste en information, l'application réelle du preset viendra avec
le reste de la feature Fast Flags.
"""
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout

from core.i18n import t
from ui.pages.base_page import BasePage
from ui.status_colors import STATUS_NEUTRAL, STATUS_OK

_PRESET_NAME_KEYS = {
    "hard": "page.fastflags.preset_hard",
    "balanced": "page.fastflags.preset_balanced",
}


class FastFlagsPage(BasePage):
    def __init__(self, parent=None):
        # Pas de sous-titre : le texte descriptif n'existe plus qu'une seule
        # fois, dans le tooltip du badge "?" à côté du titre (il était avant
        # affiché deux fois : en sous-titre ET en texte "🚧" en dessous).
        super().__init__(t("page.fastflags.title"), "", parent)
        self.add_info_badge(t("page.fastflags.placeholder"))

        self.recommendation_card = QFrame()
        self.recommendation_card.setProperty("class", "card")
        self.recommendation_card.setVisible(False)
        rec_layout = QVBoxLayout(self.recommendation_card)
        rec_layout.setContentsMargins(16, 14, 16, 14)
        rec_layout.setSpacing(6)

        title = QLabel(t("page.fastflags.recommendation_title"))
        title.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {STATUS_OK};")
        rec_layout.addWidget(title)

        self.recommendation_label = QLabel("")
        self.recommendation_label.setWordWrap(True)
        self.recommendation_label.setStyleSheet(f"font-size: 12px; color: {STATUS_NEUTRAL};")
        rec_layout.addWidget(self.recommendation_label)

        self.content_layout().addWidget(self.recommendation_card)
        self.content_layout().addStretch(1)

    def show_recommendation(self, preset_key: str, reason: str) -> None:
        preset_name = t(_PRESET_NAME_KEYS.get(preset_key, "page.fastflags.preset_balanced"))
        self.recommendation_label.setText(
            t("page.fastflags.recommendation_text").format(preset=preset_name, reason=reason)
        )
        self.recommendation_card.setVisible(True)
