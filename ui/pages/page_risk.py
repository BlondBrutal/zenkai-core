"""
Contenu "Risque" : estimation heuristique du risque de bannissement (Partie 6
du brief). CE N'EST PAS une mesure garantie ni un chiffre officiel Roblox —
juste une estimation interne basée sur les réglages actuels, présentée
comme telle partout dans l'UI (jamais comme un fait certain).

Vit maintenant comme un onglet de la page Performance ("Risque", entre
"Overlay" et "À venir" — voir page_performance.py), plus comme une page à
part entière dans la sidebar : ce contenu était trop peu dense pour
justifier sa propre entrée de navigation, isolée du reste des diagnostics.

Interrupteur pour tout désactiver : le calcul lui-même est instantané (pas
de thread ni de polling, juste une lecture de config), mais on respecte
quand même le principe "aucune analyse sans consentement explicite" —
désactivé, ce panneau n'affiche/ne calcule rien du tout.
"""
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from core.config import config
from core.i18n import t
from features.risk.risk_score import RiskEstimate, compute_risk_estimate
from ui.ring_gauge import RingGauge
from ui.status_colors import STATUS_CRITICAL, STATUS_NEUTRAL, STATUS_OK, STATUS_WARNING
from ui.toggle_switch import ToggleSwitch

_LEVEL_COLORS = {"low": STATUS_OK, "moderate": STATUS_WARNING, "high": STATUS_CRITICAL}
_LEVEL_LABEL_KEYS = {
    "low": "page.risk.level_low",
    "moderate": "page.risk.level_moderate",
    "high": "page.risk.level_high",
}


class RiskControlsPanel(QFrame):
    """Contenu de l'onglet "Risque" de la page Performance : interrupteur en
    haut (même position que "Activer l'overlay" dans l'onglet Overlay), puis
    la carte de score ou la carte "désactivé" en dessous — repris tel quel
    de l'ancienne page dédiée, juste sans son propre titre de page (l'onglet
    lui-même porte déjà le libellé "Risque")."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(8)
        toggle_label = QLabel(t("page.risk.toggle_label"))
        toggle_label.setStyleSheet("font-size: 14px; font-weight: 700; color: #E7E9EE;")
        toggle_row.addWidget(toggle_label)
        toggle_row.addStretch(1)
        self.analysis_toggle = ToggleSwitch(checked=bool(config.get("risk_analysis_enabled", True)))
        self.analysis_toggle.toggled.connect(self._on_toggle)
        toggle_row.addWidget(self.analysis_toggle)
        layout.addLayout(toggle_row)

        self.body_layout = QVBoxLayout()
        self.body_layout.setSpacing(14)
        layout.addLayout(self.body_layout)
        layout.addStretch(1)

        self._render()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Recalculé à chaque affichage (bascule vers cet onglet incluse) :
        # pas un thread, juste une lecture de config instantanée, donc pas de
        # souci à la relancer à chaque fois.
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

    def _build_disabled_card(self) -> QFrame:
        # Pas de classe "card" ici : le conteneur extérieur commun aux 3
        # onglets de la page Performance (voir
        # PerformancePage._build_scrollable_tab_container) porte déjà la
        # bordure/le fond — un second contour imbriqué au même endroit
        # ferait une double bordure.
        frame = QFrame()
        frame.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(24, 24, 24, 24)
        label = QLabel(t("page.risk.disabled_text"))
        label.setWordWrap(True)
        label.setStyleSheet(f"font-size: 13px; color: {STATUS_NEUTRAL};")
        layout.addWidget(label)
        return frame

    def _build_score_card(self, estimate: RiskEstimate) -> QFrame:
        # Pas de classe "card" ici non plus, même raison que _build_disabled_card.
        frame = QFrame()
        frame.setStyleSheet("background: transparent;")
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
