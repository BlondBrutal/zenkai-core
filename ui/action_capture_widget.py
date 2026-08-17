"""
Capture combinée touche clavier OU clic souris, pour une étape de macro
Simple (le tableau n'a plus de colonne "Type" séparée : cliquer "Définir"
détecte automatiquement s'il s'agit d'une touche ou d'un clic).

Contrairement à KeyCaptureWidget (clavier uniquement, capture locale via
grabKeyboard — l'app doit juste avoir le focus), ce widget doit aussi
détecter un clic de souris n'importe où à l'écran (pour en capturer aussi
les coordonnées X/Y) : capture donc globalement via pynput (clavier +
souris), plutôt que localement.

Un très court délai après le début de l'écoute ignore les clics (voir
_IGNORE_CLICKS_AFTER_START_S) : filet de sécurité pour ne jamais se capturer
lui-même. Une ancienne version excluait spatialement TOUTE la fenêtre de
l'app pendant toute la durée de l'écoute (pas juste un court délai) — ce qui
avalait aussi silencieusement un clic droit/milieu volontairement fait
DANS l'app pour définir la réaction (ex: un clic droit dans le tableau lui-
même), empêchant toute capture de bouton de souris à cet endroit. Un simple
délai suffit : le clic qui a lancé l'écoute (pression du bouton "Définir"
lui-même) est déjà entièrement terminé au niveau de l'OS avant même que
`_start_listening` ne s'exécute (Qt n'émet `clicked` qu'APRÈS le relâchement),
donc l'écouteur pynput ne peut de toute façon jamais le voir a posteriori.

Le callback pynput s'exécute sur son propre thread : on ne touche jamais un
widget directement dedans, seulement `emit()` (Qt met la connexion en file
vers le thread GUI) — l'arrêt des écouteurs et la mise à jour visuelle ne se
font que dans les slots connectés, sur le thread GUI.
"""
import logging
import time

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtWidgets import QPushButton

from pynput import keyboard as pynput_keyboard
from pynput import mouse as pynput_mouse

from core.i18n import t
from features.macro_pixel.key_names import pynput_key_to_pydirectinput
from features.macro_simple.macro_simple import ACTION_KEY, ACTION_MOUSE

logger = logging.getLogger("zenkaiontop.macro_simple")

_LISTENING_STYLE = "QPushButton { color: #17B897; border-color: #17B897; }"
_IGNORE_CLICKS_AFTER_START_S = 0.2
# Après la fin d'une écoute (capture réussie OU annulation), un clic natif
# Qt sur CE bouton reste ignoré pendant cette fenêtre — voir
# mousePressEvent/mouseReleaseEvent ci-dessous pour le bug précis que ça
# corrige (boucle "LButton"/n'importe quelle valeur qui rouvre aussitôt
# l'écoute). Même ordre de grandeur que
# _SUPPRESS_CONTEXT_MENU_AFTER_RIGHT_CLICK_S, même famille de problème
# (évènement Qt natif qui arrive après un traitement pynput déjà terminé).
_SUPPRESS_NATIVE_CLICK_AFTER_STOP_S = 0.3
# Un clic droit qui capture "RButton" est aussi, séparément, ce qui déclenche
# WM_CONTEXTMENU sous Windows au RELÂCHEMENT du bouton — un évènement Qt natif
# distinct et légèrement POSTÉRIEUR au clic lui-même déjà traité par pynput
# (qui a déjà mis fin à l'écoute au moment de l'appui). Sans ce délai, le menu
# contextuel du tableau (_on_table_context_menu) s'ouvrirait juste après,
# donnant l'impression que "RButton" vient d'être retiré alors qu'il est bien
# resté appliqué (voir is_listening/blocks_context_menu ci-dessous).
_SUPPRESS_CONTEXT_MENU_AFTER_RIGHT_CLICK_S = 0.3

# Les 5 boutons de souris réels de pynput (voir mouse.Button) : un bouton
# capturé qui ne serait PAS dans cette table (ex: les boutons latéraux avant
# ce correctif) était silencieusement ignoré par _on_click, laissant ce
# widget bloqué EN ÉCOUTE POUR TOUJOURS (écouteurs pynput globaux clavier+
# souris jamais arrêtés) — la touche suivante tapée n'IMPORTE OÙ dans l'OS
# (pynput écoute globalement, pas seulement quand l'app a le focus) était
# alors captée par CE widget comme nouvelle action, désactivant du même coup
# les colonnes X/Y de sa ligne (voir _update_row_enabled_state) : c'est ce
# qui donnait l'impression que "les champs X/Y ne s'écrivent plus", alors que
# le vrai problème était un bouton de souris jamais reconnu.
_MOUSE_BUTTON_NAMES = {
    pynput_mouse.Button.left: "left",
    pynput_mouse.Button.right: "right",
    pynput_mouse.Button.middle: "middle",
    pynput_mouse.Button.x1: "x1",
    pynput_mouse.Button.x2: "x2",
}
_MOUSE_BUTTON_LABEL_KEYS = {
    "left": "page.macro.simple.type_click_left",
    "right": "page.macro.simple.type_click_right",
    "middle": "page.macro.simple.type_click_middle",
    "x1": "page.macro.simple.type_click_x1",
    "x2": "page.macro.simple.type_click_x2",
}


class ActionCaptureWidget(QPushButton):
    """`changed` est émis à chaque changement d'action capturée (capture
    réelle ou set_action() programmatique), pour que la ligne du tableau
    puisse activer/désactiver ses colonnes X/Y en conséquence."""

    changed = pyqtSignal()
    # Signaux internes : émis depuis le thread du callback pynput, jamais
    # traités directement dedans (voir docstring du module).
    _captured = pyqtSignal(str, str, int, int)
    _canceled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("class", "tableCellButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._action = ""
        self._value = ""
        self._x = 0
        self._y = 0
        self._listening = False
        self._kb_listener: pynput_keyboard.Listener | None = None
        self._mouse_listener: pynput_mouse.Listener | None = None
        self._listen_started_at = 0.0
        self._right_click_captured_at = 0.0
        self._self_global_rect = QRect()
        # Valeur de repli si _stop_listeners() était jamais appelée sans
        # _start_listening() préalable (n'arrive pas en pratique, tous les
        # appelants sont gardés par self._listening) : la politique de focus
        # par défaut d'un QPushButton, jamais NoFocus.
        self._focus_policy_before_listening = self.focusPolicy()
        # Voir mousePressEvent/mouseReleaseEvent : fenêtre de temps pendant
        # laquelle un clic natif Qt sur CE bouton est ignoré, juste après la
        # fin d'une écoute.
        self._native_click_blocked_until = 0.0

        self.clicked.connect(self._start_listening)
        self._captured.connect(self._on_captured)
        self._canceled.connect(self._on_canceled)
        self._refresh_text()

    # ------------------------------------------------------------------
    def action(self) -> str:
        return self._action

    def value(self) -> str:
        return self._value

    def x(self) -> int:
        return self._x

    def y(self) -> int:
        return self._y

    def set_action(self, action: str, value: str, x: int = 0, y: int = 0) -> None:
        self._action = action
        self._value = value
        self._x = x
        self._y = y
        self._refresh_text()
        self.changed.emit()

    def cancel_listening(self) -> None:
        """Coupe une écoute en cours sans capturer — utilisé à la fermeture
        de l'app pour ne jamais laisser un écouteur global orphelin actif."""
        if self._listening:
            self._listening = False
            self._stop_listeners()
            self._refresh_text()

    def is_listening(self) -> bool:
        """Utilisé par macro_simple_tab._on_table_context_menu : pendant une
        capture active sur une ligne, un clic droit doit être capturé comme
        touche ("RButton") par CETTE capture plutôt que d'ouvrir le menu
        contextuel du tableau — les deux réagissent au même clic physique
        (l'un via le hook global pynput, l'autre via l'événement Qt natif),
        donc le menu doit savoir s'effacer pendant qu'une capture écoute."""
        return self._listening

    def blocks_context_menu(self) -> bool:
        """Comme is_listening(), mais reste vrai un court instant APRÈS
        qu'un clic droit vient de capturer "RButton" (voir
        _SUPPRESS_CONTEXT_MENU_AFTER_RIGHT_CLICK_S) : is_listening() seul
        passe à False dès l'appui du clic droit (la capture est déjà
        terminée), mais WM_CONTEXTMENU (donc customContextMenuRequested) est
        déclenché par Windows au RELÂCHEMENT de ce même clic droit — un
        évènement Qt natif distinct et légèrement postérieur, qui sans ce
        garde-fou ouvrirait quand même le menu du tableau juste après,
        donnant l'impression que "RButton" venait d'être retiré."""
        if self._listening:
            return True
        return (time.monotonic() - self._right_click_captured_at) < _SUPPRESS_CONTEXT_MENU_AFTER_RIGHT_CLICK_S

    # ------------------------------------------------------------------
    def focusOutEvent(self, event) -> None:
        """Filet de sécurité (même principe que KeyCaptureWidget) : sans
        ça, une capture démarrée puis abandonnée sans clic/touche reconnu(e)
        — par ex. l'utilisateur clique "Définir" puis va directement cliquer
        ailleurs dans l'app (un autre bouton "Définir", un champ X/Y...) —
        reste en écoute globale indéfiniment. N'importe quel clic ultérieur
        n'IMPORTE OÙ dans l'app (pynput écoute globalement, pas seulement ce
        bouton) serait alors silencieusement capturé comme la valeur de CETTE
        ligne, un symptôme qui ressemble à "les champs X/Y ne s'écrivent
        plus" alors que la vraie cause est une écoute jamais arrêtée."""
        if self._listening:
            self.cancel_listening()
        super().focusOutEvent(event)

    def mousePressEvent(self, event) -> None:
        # Racine du bug "boucle LButton" (voir historique/CLAUDE.md) : un
        # clic RÉEL qui atterrit sur CE bouton pendant l'écoute est vu à LA
        # FOIS par pynput (_on_click, global — capture ou annule, met fin à
        # l'écoute) ET nativement par Qt (ce mousePressEvent/
        # mouseReleaseEvent, TOUJOURS actifs quelle que soit la politique de
        # focus — le clearFocus()/NoFocus de _start_listening ne bloque que
        # le clavier, jamais la souris). Sans ce garde-fou, le relâchement de
        # CE MÊME clic émet ensuite clicked() normalement côté Qt, qui
        # relance _start_listening() — juste après que pynput ait déjà
        # traité ce clic, donnant l'impression d'une réouverture immédiate
        # et donc d'une boucle infinie dès qu'on reclique sur le bouton pour
        # définir une valeur. self._listening peut déjà être retombé à False
        # à ce stade (pynput tourne sur son propre thread, plus rapide que
        # le passage par la file d'évènements Qt du signal _captured/
        # _canceled) — d'où la fenêtre de temps supplémentaire
        # (_native_click_blocked_until) après la fin de l'écoute, pas
        # seulement pendant.
        blocked = self._listening or time.monotonic() < self._native_click_blocked_until
        logger.debug(
            "mousePressEvent: listening=%s blocked_until_active=%s -> %s",
            self._listening, time.monotonic() < self._native_click_blocked_until,
            "avalé" if blocked else "transmis",
        )
        if blocked:
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        blocked = self._listening or time.monotonic() < self._native_click_blocked_until
        logger.debug(
            "mouseReleaseEvent: listening=%s blocked_until_active=%s -> %s",
            self._listening, time.monotonic() < self._native_click_blocked_until,
            "avalé" if blocked else "transmis",
        )
        if blocked:
            return
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------------
    def _start_listening(self) -> None:
        logger.debug("_start_listening: listening avant appel=%s", self._listening)
        if self._listening:
            return
        # Retire le focus Qt (et empêche d'en reprendre) AVANT de marquer
        # l'écoute active, PAS après (essayé d'abord, voir historique) :
        # clearFocus() ci-dessous déclenche synchronement focusOutEvent, qui
        # annule l'écoute dès qu'il la voit active (self._listening déjà à
        # True) — se retirer le focus À SOI-MÊME annulerait donc
        # immédiatement l'écoute qu'on est en train de démarrer si l'ordre
        # était inversé (vérifié : l'écoute se terminait aussitôt commencée,
        # ET les écouteurs pynput créés juste après restaient orphelins,
        # jamais arrêtés).
        #
        # Contrairement à KeyCaptureWidget (qui capture localement via ses
        # propres keyPressEvent/mousePressEvent, jamais transmis à super()),
        # ce widget capture globalement via pynput SANS jamais toucher aux
        # gestionnaires d'évènements Qt natifs — un QPushButton qui garde le
        # focus reste donc pleinement actif côté Qt PENDANT l'écoute :
        # Key_Space sur un bouton focusé déclenche l'activation native du
        # bouton (clicked()) à SON relâchement, un évènement Qt distinct et
        # postérieur à la capture pynput déjà effectuée sur LA MÊME pression
        # — ce clicked() tardif relance _start_listening(), écrasant la
        # valeur tout juste appliquée (symptôme : "Espace" capturé puis
        # aussitôt annulé). Sans focus, ce bouton ne peut plus recevoir le
        # moindre évènement clavier natif, quel qu'il soit — la capture
        # réelle continue de fonctionner normalement puisqu'elle ne dépend
        # jamais du focus Qt (pynput écoute au niveau du système). Politique
        # de focus restaurée dans _stop_listeners().
        self._focus_policy_before_listening = self.focusPolicy()
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clearFocus()

        self._listening = True
        self._listen_started_at = time.monotonic()
        # Pris ici (thread GUI) une fois pour toutes : _on_click tourne sur
        # le thread pynput et ne doit jamais interroger la géométrie du
        # widget directement depuis là (accès Qt hors thread GUI). Un simple
        # QRect figé suffit, ce bouton ne bouge/redimensionne pas pendant
        # une capture.
        self._self_global_rect = QRect(self.mapToGlobal(self.rect().topLeft()), self.size())
        self.setStyleSheet(_LISTENING_STYLE)
        self.setText(t("page.macro.pixel.key_listening"))
        self._kb_listener = pynput_keyboard.Listener(on_press=self._on_key_press)
        self._mouse_listener = pynput_mouse.Listener(on_click=self._on_click)
        self._kb_listener.start()
        self._mouse_listener.start()

    def _on_key_press(self, key) -> None:
        if not self._listening:
            return
        name = pynput_key_to_pydirectinput(key)
        if name is None:
            return
        if name == "esc":
            logger.debug("_on_key_press [thread pynput]: Echap -> annulation")
            self._listening = False
            self._canceled.emit()
            return
        logger.debug("_on_key_press [thread pynput]: capture clavier %r", name)
        self._listening = False
        self._captured.emit(ACTION_KEY, name, 0, 0)

    def _on_click(self, x, y, button, pressed) -> None:
        if not self._listening or not pressed:
            return
        if time.monotonic() - self._listen_started_at < _IGNORE_CLICKS_AFTER_START_S:
            logger.debug(
                "_on_click [thread pynput]: ignoré (dans _IGNORE_CLICKS_AFTER_START_S) bouton=%s pos=(%s,%s)",
                button, x, y,
            )
            return
        in_self_rect = self._self_global_rect.contains(QPoint(int(x), int(y)))
        logger.debug(
            "_on_click [thread pynput]: bouton=%s pos=(%s,%s) self_rect=%s contains=%s",
            button, x, y, self._self_global_rect, in_self_rect,
        )
        if in_self_rect:
            # Un clic sur CE bouton "Définir" pendant que sa propre capture
            # est déjà en cours annule simplement l'écoute, plutôt que de
            # capturer ce clic comme l'action — un clic ici n'a jamais de
            # sens comme réaction d'une macro qui cible normalement une
            # fenêtre de jeu, pas ce bouton lui-même.
            self._listening = False
            self._canceled.emit()
            return
        name = _MOUSE_BUTTON_NAMES.get(button)
        if name is None:
            # Bouton non reconnu (en pratique jamais avec les 5 boutons réels
            # de pynput ci-dessus tous couverts) : annule plutôt que d'ignorer
            # silencieusement, pour ne JAMAIS rester bloqué en écoute (voir le
            # commentaire sur _MOUSE_BUTTON_NAMES).
            self._listening = False
            self._canceled.emit()
            return
        logger.debug("_on_click [thread pynput]: capture souris %r pos=(%s,%s)", name, x, y)
        self._listening = False
        if name == "right":
            self._right_click_captured_at = time.monotonic()
        self._captured.emit(ACTION_MOUSE, name, x, y)

    def _on_captured(self, action: str, value: str, x: int, y: int) -> None:
        logger.debug("_on_captured [thread GUI]: action=%r value=%r pos=(%s,%s)", action, value, x, y)
        self._stop_listeners()
        self.set_action(action, value, x, y)

    def _on_canceled(self) -> None:
        logger.debug("_on_canceled [thread GUI]")
        self._stop_listeners()
        self._refresh_text()

    def _stop_listeners(self) -> None:
        logger.debug("_stop_listeners [thread GUI]")
        if self._kb_listener is not None:
            self._kb_listener.stop()
            self._kb_listener = None
        if self._mouse_listener is not None:
            self._mouse_listener.stop()
            self._mouse_listener = None
        # Repose la politique de focus normale (retirée dans
        # _start_listening) : ce bouton redevient cliquable/focusable comme
        # n'importe quel autre une fois l'écoute terminée.
        self.setFocusPolicy(self._focus_policy_before_listening)
        # Voir mousePressEvent/mouseReleaseEvent : le clic RÉEL qui vient de
        # mettre fin à l'écoute (capturé ou annulé côté pynput) atteint
        # aussi, séparément, ces gestionnaires Qt natifs — parfois
        # légèrement APRÈS ce _stop_listeners() (l'ordre exact entre
        # l'évènement souris natif et le signal en file d'attente venant du
        # thread pynput n'est pas garanti). Bloque tout clic natif sur ce
        # bouton pendant cette fenêtre, pour ne jamais rouvrir l'écoute à
        # cause de CE MÊME clic physique.
        self._native_click_blocked_until = time.monotonic() + _SUPPRESS_NATIVE_CLICK_AFTER_STOP_S
        self.setStyleSheet("")

    # ------------------------------------------------------------------
    def _refresh_text(self) -> None:
        # `not self._value` (pas `not self._action`) : une étape jamais
        # capturée a value="" quel que soit `action` (voir l'étape par
        # défaut créée par "Ajouter une étape" dans macro_simple_tab.py),
        # alors qu'une touche/un clic réellement capturé a toujours une
        # valeur non vide ("e", "left", etc.).
        if not self._value:
            self.setText(t("page.macro.pixel.key_placeholder"))
        elif self._action == ACTION_MOUSE:
            self.setText(t(_MOUSE_BUTTON_LABEL_KEYS.get(self._value, self._value)))
        else:
            self.setText(self._value)
