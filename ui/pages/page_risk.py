"""
Page Risque : estimation heuristique du risque de bannissement (Partie 6 du
brief). CE N'EST PAS une mesure garantie ni un chiffre officiel Roblox —
juste une estimation interne basée sur les réglages actuels, présentée
comme telle partout dans l'UI (jamais comme un fait certain).

Interrupteur pour tout désactiver : le calcul lui-même est instantané (pas
de thread ni de polling, juste une lecture de config), mais on respecte
quand même le principe "aucune analyse sans consentement explicite" —
désactivé, la page n'affiche/ne calcule rien du tout.
"""
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from core.config import config
from core.i18n import t
from features.risk.risk_score import RiskEstimate, compute_risk_estimate
from ui.pages.base_page import BasePage
from ui.ring_gauge import RingGauge
from ui.status_colors import STATUS_CRITICAL, STATUS_NEUTRAL, STATUS_OK, STATUS_WARNING
from ui.toggle_switch import ToggleSwitch

_LEVEL_COLORS = {"low": STATUS_OK, "moderate": STATUS_WARNING, "high": STATUS_CRITICAL}
_LEVEL_LABEL_KEYS = {
    "low": "page.risk.level_low",
    "moderate": "page.risk.level_moderate",
    "high": "page.risk.level_high",
}


class RiskPage(BasePage):
    def __init__(self, parent=None):
        super().__init__(t("page.risk.title"), "", parent)
        self.add_info_badge(t("page.risk.subtitle"))

        toggle_control = QWidget()
        toggle_row = QHBoxLayout(toggle_control)
        toggle_row.setContentsMargins(0, 0, 0, 0)
        toggle_row.setSpacing(8)

        toggle_label = QLabel(t("page.risk.toggle_label"))
        toggle_label.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {STATUS_NEUTRAL};")
        toggle_row.addWidget(toggle_label)

        self.analysis_toggle = ToggleSwitch(checked=bool(config.get("risk_analysis_enabled", True)))
        self.analysis_toggle.toggled.connect(self._on_toggle)
        toggle_row.addWidget(self.analysis_toggle)

        self.header_layout().addWidget(toggle_control)

        self.body_layout = QVBoxLayout()
        self.body_layout.setSpacing(14)
        self.content_layout().addLayout(self.body_layout, 1)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Recalculé à chaque affichage : pas un thread, juste une lecture de
        # config instantanée, donc pas de souci à la relancer à chaque visite.
        self._render()

    def _on_toggle(self, checked: bool) -> None:
        config.set("risk_analysis_enabled", checked)
        self._render()

    def _render(self) -> None:
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not self.analysis_toggle.isChecked():
            self.body_layout.addWidget(self._build_disabled_card())
            return

        estimate = compute_risk_estimate()
        self.body_layout.addWidget(self._build_score_card(estimate))
        self.body_layout.addStretch(1)

    def _build_disabled_card(self) -> QFrame:
        frame = QFrame()
        frame.setProperty("class", "card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(24, 24, 24, 24)
        label = QLabel(t("page.risk.disabled_text"))
        label.setWordWrap(True)
        label.setStyleSheet(f"font-size: 13px; color: {STATUS_NEUTRAL};")
        layout.addWidget(label)
        return frame

    def _build_score_card(self, estimate: RiskEstimate) -> QFrame:
        frame = QFrame()
        frame.setProperty("class", "card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        color = _LEVEL_COLORS.get(estimate.level, STATUS_OK)

        eyebrow = QLabel(t("page.risk.estimate_label"))
        eyebrow.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {STATUS_NEUTRAL};")
        layout.addWidget(eyebrow)

        gauge_row = QHBoxLayout()
        gauge_row.setSpacing(20)

        gauge = RingGauge(size=120)
        gauge.set_target(estimate.score, color)
        gauge_row.addWidget(gauge)

        text_col = QVBoxLayout()
        text_col.setSpacing(6)

        level_label = QLabel(t(_LEVEL_LABEL_KEYS.get(estimate.level, "page.risk.level_low")))
        level_label.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {color};")
        text_col.addWidget(level_label)

        disclaimer = QLabel(t("page.risk.disclaimer"))
        disclaimer.setWordWrap(True)
        disclaimer.setStyleSheet(f"font-size: 11.5px; color: {STATUS_NEUTRAL};")
        text_col.addWidget(disclaimer)
        text_col.addStretch(1)

        gauge_row.addLayout(text_col, 1)
        layout.addLayout(gauge_row)

        layout.addWidget(self._build_list_section(
            t("page.risk.contributors_title"),
            estimate.contributor_keys,
            fallback_key="page.risk.no_contributors",
        ))

        if estimate.recommendation_keys:
            layout.addWidget(self._build_list_section(
                t("page.risk.recommendations_title"),
                estimate.recommendation_keys,
            ))

        return frame

    def _build_list_section(self, title_text: str, item_keys: list, fallback_key: str | None = None) -> QWidget:
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        title = QLabel(title_text)
        title.setStyleSheet("font-size: 13px; font-weight: 700; color: #E7E9EE;")
        layout.addWidget(title)

        if item_keys:
            for key in item_keys:
                item = QLabel("— " + t(key))
                item.setWordWrap(True)
                item.setStyleSheet(f"font-size: 12px; color: {STATUS_NEUTRAL};")
                layout.addWidget(item)
        elif fallback_key:
            item = QLabel(t(fallback_key))
            item.setWordWrap(True)
            item.setStyleSheet(f"font-size: 12px; color: {STATUS_NEUTRAL};")
            layout.addWidget(item)

        return section
