"""
Remplace QComboBox pour "Mode" (Macro Simple) : le popup natif d'un
QComboBox vit dans un conteneur top-level séparé qui n'hérite PAS de la
cascade QSS globale de l'appli (QComboBoxPrivateContainer — vérifié :
`combo.isAncestorOf(popup)` renvoie False et `popup.styleSheet()` est vide
malgré une vraie relation `QObject.parent()`). Plusieurs tentatives de
stylage QSS ciblé (sur le combo, sur "QComboBox QAbstractItemView", sur le
conteneur du popup directement) ont toutes échoué à produire un rendu fiable
(reste un rectangle noir basique par endroits) — plutôt que de continuer à
forcer un style natif qui résiste, ce widget peint TOUT lui-même : un
QPushButton (même classe QSS "neutralButton" que KeyCaptureWidget juste à
côté dans la même ligne, pour un rendu assorti) qui ouvre un QMenu stylé
directement en Python (même technique que _build_styled_menu dans
macro_simple_tab.py : FramelessWindowHint + WA_TranslucentBackground pour de
vrais coins arrondis, pas juste un border-radius QSS qui laisse dépasser le
cadre natif carré).
"""
import time

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QMenu, QPushButton

# Padding horizontal total de .neutralButton (voir theme.qss : "padding: 10px
# 18px") : à soustraire de la largeur du bouton pour savoir combien de place
# reste réellement pour le texte avant de devoir le tronquer.
_TEXT_HORIZONTAL_PADDING = 36

# Un clic sur CE bouton pendant que son propre menu est déjà ouvert ferme le
# menu (clic hors de son rectangle, capté par le grab souris du QMenu) — mais
# Qt continue ensuite de délivrer ce MÊME clic au widget se trouvant sous le
# curseur une fois le popup fermé (comportement standard, voir par ex. une
# barre de menu : cliquer sur "Édition" pendant que "Fichier" est ouvert doit
# fermer "Fichier" ET ouvrir "Édition" en un seul clic) : ici, ce widget est
# le bouton lui-même, qui reçoit donc un clic complet et rouvre aussitôt un
# nouveau menu. `_menu_open` seul ne suffit PAS à l'empêcher : ce drapeau est
# déjà remis à False au moment où `menu.exec()` retourne (avant même que Qt
# ne redistribue ce même clic au bouton) — le clic "de fermeture" doit donc
# être ignoré via une fenêtre de temps après la fermeture, pas via un simple
# drapeau de réentrance.
_IGNORE_REOPEN_AFTER_CLOSE_S = 0.25

_MENU_QSS = """
QMenu {
    background-color: #202027;
    color: #E7E9EE;
    border: 1px solid #33333C;
    border-radius: 8px;
    padding: 4px;
    font-size: 12px;
}
QMenu::item {
    padding: 6px 14px;
    border-radius: 6px;
}
QMenu::item:selected {
    background-color: transparent;
    color: #17B897;
}
"""


class StyledDropdown(QPushButton):
    """Sous-ensemble d'API compatible avec QComboBox (addItem/currentIndex/
    setCurrentIndex/currentIndexChanged) : le code appelant existant
    (macro_simple_tab.py) n'a donc rien d'autre à changer que la
    construction elle-même."""

    currentIndexChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        # .compactNeutralButton (pas .neutralButton) : ce widget vit toujours
        # à une hauteur FIXE et compacte (32px dans macro_simple_tab.py, 34px
        # dans page_fleasion.py, jamais une hauteur libre) — le padding
        # vertical de .neutralButton (10px 10px), pensé pour un bouton qui
        # peut grandir librement, ne laissait plus assez de place à la
        # hauteur réelle de la police une fois figé à ces tailles-là,
        # rognant le bas des lettres descendantes (audit complet du texte
        # coupé sur les boutons, voir CLAUDE.md/design system — mesuré via
        # QFontMetrics, pas juste à l'œil).
        self.setProperty("class", "compactNeutralButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Alignement à gauche (comme un QComboBox) : un QPushButton centre
        # son texte par défaut, ce qui casserait la ressemblance visuelle
        # avec les autres champs de la même ligne (tous alignés à gauche).
        self.setStyleSheet("text-align: left;")
        self._labels: list[str] = []
        self._current_index = 0
        self._menu_open = False
        self._menu_closed_at = 0.0
        self.clicked.connect(self._open_menu)

    def addItem(self, label: str) -> None:
        self._labels.append(label)
        if len(self._labels) == 1:
            self._refresh_text()

    def currentIndex(self) -> int:
        return self._current_index

    def setCurrentIndex(self, index: int) -> None:
        if index == self._current_index:
            self._refresh_text()
            return
        self._current_index = index
        self._refresh_text()
        self.currentIndexChanged.emit(index)

    def _refresh_text(self) -> None:
        if not (0 <= self._current_index < len(self._labels)):
            return
        full_text = f"{self._labels[self._current_index]}  ▾"
        # QPushButton ne tronque JAMAIS son texte tout seul (contrairement à
        # QLabel avec certains modes) : sans ceci, un texte trop long pour la
        # largeur du bouton serait juste coupé net par le moteur de rendu,
        # sans "…" et parfois en coupant par le milieu selon l'espace
        # restant. elidedText(..., ElideRight, ...) coupe explicitement à LA
        # FIN (le début du texte reste toujours visible) et ajoute "…".
        available_width = max(0, self.width() - _TEXT_HORIZONTAL_PADDING)
        metrics = QFontMetrics(self.font())
        elided = metrics.elidedText(full_text, Qt.TextElideMode.ElideRight, available_width)
        self.setText(elided)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Réélide au bon endroit une fois la taille finale connue : au
        # moment du tout premier _refresh_text() (appelé depuis addItem()),
        # setFixedSize() n'a souvent pas encore été appliqué par l'appelant.
        self._refresh_text()

    def _open_menu(self) -> None:
        if not self._labels:
            return
        # Réentrance (clic qui ferme ce menu redélivré à CE bouton avant même
        # que menu.exec() ci-dessous ne soit revenu) : couvert par
        # _menu_open. Redélivrance APRÈS le retour de exec() (le cas réel le
        # plus courant, voir le commentaire sur _IGNORE_REOPEN_AFTER_CLOSE_S
        # plus haut) : couverte par le délai sur _menu_closed_at.
        if self._menu_open:
            return
        if time.monotonic() - self._menu_closed_at < _IGNORE_REOPEN_AFTER_CLOSE_S:
            return
        menu = QMenu(self)
        menu.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        menu.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
        menu.setStyleSheet(_MENU_QSS)
        actions = [menu.addAction(label) for label in self._labels]
        # Sans ça, le menu ne fait que la largeur de son contenu (souvent
        # plus étroit que le bouton, ex: "ON/OFF" vs les 150px du champ
        # "Mode") : il doit au moins égaler la largeur du bouton qui l'ouvre.
        menu.setMinimumWidth(self.width())

        self._menu_open = True
        try:
            chosen = menu.exec(self.mapToGlobal(self.rect().bottomLeft()))
        finally:
            self._menu_open = False
            self._menu_closed_at = time.monotonic()
        if chosen is None:
            return
        self.setCurrentIndex(actions.index(chosen))
