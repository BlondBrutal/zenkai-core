"""
Petit champ cliquable qui capture la prochaine touche clavier OU bouton de
souris pressé, pour définir une touche de macro (déclenchement, réaction,
swap). Traduit la touche/le bouton en identifiant compatible `pydirectinput`
(clavier, seule bibliothèque utilisée pour simuler les appuis clavier dans
l'app) ou en identifiant interne "mouse_*" (souris, voir
features/macro_pixel/key_names.py), donc le format doit correspondre
exactement à ce qu'attendent les écouteurs globaux et les simulateurs.
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QPushButton

from core.i18n import t
from features.macro_pixel.key_names import qt_key_to_pydirectinput, qt_mouse_button_to_name

_LISTENING_STYLE = "QPushButton { color: #17B897; border-color: #17B897; }"
# Padding horizontal total de .compactNeutralButton (voir theme.qss : "padding:
# 4px 18px") : à soustraire de la largeur du bouton pour élider le texte au
# bon endroit plutôt que de laisser Qt le couper net sans "…" (QPushButton
# n'élide jamais tout seul).
_TEXT_HORIZONTAL_PADDING = 36

_MOUSE_LABEL_KEYS = {
    "mouse_left": "page.macro.pixel.key_mouse_left",
    "mouse_right": "page.macro.pixel.key_mouse_right",
    "mouse_middle": "page.macro.pixel.key_mouse_middle",
    "mouse_x1": "page.macro.pixel.key_mouse_x1",
    "mouse_x2": "page.macro.pixel.key_mouse_x2",
}
# Boutons jamais capturables quand `exclude_click_buttons=True` (touche de
# DÉCLENCHEMENT) : le clic gauche/droit sert normalement à interagir avec
# l'interface (cliquer sur ce bouton lui-même, sur d'autres widgets...) et ne
# doit donc jamais pouvoir être détourné en touche de déclenchement globale,
# sous peine de rendre l'appli inutilisable au clic normal. Sans effet sur une
# touche de RÉACTION (le clic simulé PAR la macro), qui elle peut légitimement
# être n'importe quel bouton.
_RESERVED_FOR_UI = ("mouse_left", "mouse_right")


def display_label(key: str) -> str:
    """Libellé lisible d'un identifiant de touche/bouton capturé par ce
    widget (ex: pour le toast de "changement rapide de touche" dans
    macro_pixel_tab.py) : le clavier reste affiché tel quel (déjà lisible,
    "f6"/"space"/"a"), un bouton de souris passe par la même table de
    libellés traduits que _refresh_text ci-dessous."""
    if not key:
        return ""
    label_key = _MOUSE_LABEL_KEYS.get(key)
    return t(label_key) if label_key else key


class KeyCaptureWidget(QPushButton):
    keyChanged = pyqtSignal(str)  # identifiant pydirectinput ou "mouse_*" (ex: "space", "a", "f6", "mouse_middle")

    def __init__(self, initial_key: str = "", exclude_click_buttons: bool = False, parent=None):
        super().__init__(parent)
        # .compactNeutralButton (pas .neutralButton) : ce widget a toujours une
        # hauteur FIXE (32px, voir _FIELD_HEIGHT dans macro_simple_tab.py/
        # macro_pixel_tab.py) — le padding vertical de .neutralButton, pensé
        # pour un bouton de hauteur libre, tronquait le haut du texte dans ce
        # cadre figé (voir theme.qss).
        self.setProperty("class", "compactNeutralButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # QPushButton a Qt.ContextMenuPolicy.DefaultContextMenu par défaut
        # (pas NoContextMenu, vérifié) : ce widget capture LUI-MÊME tous les
        # boutons de souris (voir mousePressEvent, y compris le clic droit
        # en réaction), jamais de menu contextuel légitime ici — explicite
        # plutôt que de compter sur le défaut Qt, pour ne laisser aucune
        # chance à un évènement ContextMenu natif de s'interposer.
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._key = initial_key
        self._listening = False
        self._exclude_click_buttons = exclude_click_buttons
        self.clicked.connect(self._start_listening)
        self._refresh_text()

    def key(self) -> str:
        return self._key

    def set_key(self, key: str) -> None:
        self._key = key
        self._refresh_text()

    def _start_listening(self) -> None:
        if self._listening:
            return
        self._listening = True
        self.setStyleSheet(_LISTENING_STYLE)
        self.setText(t("page.macro.pixel.key_listening"))
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.grabKeyboard()

    def _stop_listening(self) -> None:
        self._listening = False
        self.setStyleSheet("")
        self.releaseKeyboard()
        self._refresh_text()

    def _apply_captured(self, key_name: str | None) -> None:
        self._stop_listening()
        if key_name is not None:
            self._key = key_name
            self._refresh_text()
            self.keyChanged.emit(key_name)

    def keyPressEvent(self, event) -> None:
        if not self._listening:
            super().keyPressEvent(event)
            return

        if event.key() == Qt.Key.Key_Escape:
            self._stop_listening()
            return

        key_name = qt_key_to_pydirectinput(event.key(), event.text())
        self._apply_captured(key_name)

    def mousePressEvent(self, event) -> None:
        if not self._listening:
            super().mousePressEvent(event)
            return

        name = qt_mouse_button_to_name(event.button())
        if name is None:
            return
        if self._exclude_click_buttons and name in _RESERVED_FOR_UI:
            # Ce bouton ("Définir") ne peut de toute façon jamais capturer
            # clic gauche/droit ici (voir _RESERVED_FOR_UI) : un clic dessus
            # pendant l'écoute ne peut donc être qu'une tentative d'annuler,
            # jamais une capture valide — annule plutôt que d'ignorer
            # silencieusement (qui laissait l'écoute tourner indéfiniment).
            self._stop_listening()
            return
        self._apply_captured(name)

    def mouseReleaseEvent(self, event) -> None:
        if self._listening:
            # Avale le relâchement pendant l'écoute : la pression correspon-
            # dante n'a pas été transmise à super() ci-dessus, donc la laisser
            # remonter ici ne servirait qu'à risquer une réémission de
            # clicked() par le mécanisme interne de QAbstractButton.
            return
        super().mouseReleaseEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if self._listening:
            # Même principe que mouseReleaseEvent ci-dessus, côté clavier :
            # l'appui correspondant n'a pas été transmis à super() dans
            # keyPressEvent (capturé nous-mêmes), donc laisser passer le
            # relâchement ici risquerait de faire réagir le mécanisme interne
            # de QAbstractButton (ex: Key_Space, qu'il traite normalement en
            # deux temps, pression PUIS relâchement) — jamais vérifié
            # inoffensif, donc avalé par prudence plutôt que transmis.
            return
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event) -> None:
        # Sans ça, un grabKeyboard() jamais relâché (l'utilisateur clique
        # ailleurs dans l'appli sans appuyer sur Échap ni sur une touche/un
        # bouton valide) capture TOUS les événements clavier de l'application
        # pour de bon, y compris dans des champs sans rapport (ex: Pixel X/
        # Pixel Y) : plus aucune touche tapée n'atteint alors le champ qui a
        # pourtant le focus visuel. Perdre le focus (clic sur un autre widget,
        # changement d'onglet...) arrête donc l'écoute au même titre qu'Échap.
        if self._listening:
            self._stop_listening()
        super().focusOutEvent(event)

    def _refresh_text(self) -> None:
        full_text = display_label(self._key) if self._key else t("page.macro.pixel.key_placeholder")
        available_width = max(0, self.width() - _TEXT_HORIZONTAL_PADDING)
        metrics = QFontMetrics(self.font())
        self.setText(metrics.elidedText(full_text, Qt.TextElideMode.ElideRight, available_width))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Réélide une fois la taille finale connue : au tout premier
        # _refresh_text() (appelé depuis __init__), setFixedSize() n'a
        # souvent pas encore été appliqué par l'appelant.
        self._refresh_text()
