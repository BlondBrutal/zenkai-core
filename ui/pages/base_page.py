"""
Page de base : titre + sous-titre + zone de contenu.
Toutes les pages de l'app héritent de ceci pour garder une hiérarchie
visuelle cohérente (une action principale par écran).
"""
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QLabel, QWidget

from ui.info_badge import InfoBadge, WarningBadge

# Marge fixe (constante pour toutes les pages) entre le haut de la rangée
# titre et le haut du badge "?". Essayé plusieurs approches "intelligentes"
# basées sur les métriques de police ou sur les pixels réellement dessinés
# du texte du titre : toutes calculent une valeur DIFFÉRENTE selon les
# lettres du mot du titre (un mot avec un jambage comme "Risque"/"Flags" ne
# donne pas le même résultat qu'un mot sans, comme "Macro"/"Licence"), ce qui
# rendait l'alignement incohérent d'une page à l'autre malgré un calcul
# "correct" pour chaque titre pris isolément. Une valeur fixe, identique
# partout, garantit une position réellement cohérente d'une page à l'autre —
# calibrée sur le rendu jugé correct (pages Risque/Fast Flags).
_BADGE_TOP_MARGIN = 8


class BasePage(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(32, 28, 32, 28)
        self._layout.setSpacing(6)

        # Rangée titre + zone d'actions à droite (ex: interrupteur ON/OFF),
        # au même niveau visuel que le titre plutôt que noyée plus bas.
        self._header_layout = QHBoxLayout()
        self._header_layout.setContentsMargins(0, 0, 0, 0)
        # -30% (12 -> 8) puis -25% (8 -> 6) puis -30% supplémentaires
        # (6 -> 4) : écart entre la fin du texte du titre et le badge "?"
        # (voir add_info_badge, inséré juste après le titre dans ce même
        # layout) jugé trop large à chaque passe. Ce même spacing gouverne
        # aussi l'écart entre le badge "?" et un éventuel badge bêta (voir
        # add_beta_badge) — un seul réglage, uniforme par construction sur
        # TOUS les enfants de ce layout, jamais deux valeurs qui pourraient
        # diverger.
        self._header_layout.setSpacing(4)

        self.title_label = QLabel(title)
        self.title_label.setProperty("class", "pageTitle")
        self._header_layout.addWidget(self.title_label)
        self._header_layout.addStretch(1)

        self._layout.addLayout(self._header_layout)

        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setProperty("class", "pageSubtitle")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setVisible(bool(subtitle))
        self._layout.addWidget(self.subtitle_label)

        # Sans sous-titre, l'espace généreux prévu pour lui devient un vide
        # inutile au-dessus du contenu : on le réduit dans ce cas.
        self._layout.addSpacing(18 if subtitle else 6)

    def content_layout(self) -> QVBoxLayout:
        """Layout où les sous-classes ajoutent le contenu réel de la page."""
        return self._layout

    def header_layout(self) -> QHBoxLayout:
        """Layout horizontal du titre : les sous-classes y ajoutent un
        contrôle (interrupteur, bouton) aligné à droite, au même niveau que
        le titre — il s'insère avant le stretch final donc reste bien à droite."""
        return self._header_layout

    def add_info_badge(self, tooltip_text: str) -> None:
        """Insère un badge "?" juste après le titre (avant le stretch), pour
        remplacer un texte descriptif affiché en clair sous le titre par un
        tooltip au survol — évite de répéter en permanence à l'écran un
        texte qui n'aide pas à la lecture rapide de la page. Marge fixe
        (_BADGE_TOP_MARGIN), identique pour toutes les pages : voir le
        commentaire sur cette constante pour pourquoi un calcul par titre a
        été abandonné."""
        badge = InfoBadge(tooltip_text)

        wrapper = QWidget()
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, _BADGE_TOP_MARGIN, 0, 0)
        wrapper_layout.setSpacing(0)
        wrapper_layout.addWidget(badge)
        wrapper_layout.addStretch(1)

        self._header_layout.insertWidget(1, wrapper)

    def add_beta_badge(self, tooltip_text: str) -> None:
        """Insère un petit panneau de signalisation rouge ("!") juste après
        le badge "?" (voir add_info_badge, à appeler AVANT celui-ci — la
        position d'insertion, index 2, suppose le badge "?" déjà en index 1)
        — même mécanique de bulle au survol, réservée à un avertissement
        ponctuel (ex: "Fonctionnalité en bêta") plutôt qu'un texte
        informatif neutre. Même espacement que titre<->badge "?" (le
        spacing du header_layout est UNIFORME sur tous ses enfants, voir
        __init__), jamais une valeur recalculée séparément."""
        badge = WarningBadge(tooltip_text)

        wrapper = QWidget()
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, _BADGE_TOP_MARGIN, 0, 0)
        wrapper_layout.setSpacing(0)
        wrapper_layout.addWidget(badge)
        wrapper_layout.addStretch(1)

        self._header_layout.insertWidget(2, wrapper)

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)

    def set_subtitle(self, subtitle: str) -> None:
        self.subtitle_label.setText(subtitle)
        self.subtitle_label.setVisible(bool(subtitle))
