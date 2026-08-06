"""
Onglet "Macro type 1" (Simple) de la page Macro : jusqu'à MAX_SLOTS
emplacements indépendants (MacroSimpleSlot), chacun avec sa propre séquence enregistrée
d'actions clavier/souris (features/macro_simple/recorder.py), sa touche de
déclenchement globale (features/macro_simple/hotkey_listener.py) et son
propre thread de rejeu (features/macro_simple/player.py).

Contrairement à Macro Pixel (qui reprend un comportement déjà présent dans
"Global Macro v2.ahk"), il n'existe pas de moteur d'enregistrement/rejeu
générique à porter depuis l'AHK d'origine — ce fichier ne contient que des
séquences figées et un déclencheur pixel, déjà couverts ailleurs. Le
fonctionnement ci-dessous (modes Hold/Toggle/Répétition, tableau d'étapes
éditable) est donc conçu depuis zéro, mais reprend le même pattern "jusqu'à
3 emplacements" que macro_pixel_tab.py.

Distinction de vocabulaire volontaire : "Enregistrer" démarre/arrête la
CAPTURE d'une séquence (touches/clics), alors que "Sauvegarder" persiste la
config de l'emplacement (comme "Enregistrer" dans Macro Pixel) dans la
Bibliothèque — même mécanisme, nom différent pour ne pas les confondre.

Modes de déclenchement ("Activer", touche de déclenchement globale écoutée
même hors focus via HotkeyTriggerListener) :
- Hold ("tant que maintenu") : la séquence tourne tant que la touche reste
  physiquement enfoncée, s'arrête au relâchement.
- Toggle ("ON/OFF") : un appui lance la séquence en boucle, un second appui
  l'arrête. Ni Hold ni Toggle ne sont bornés par le champ Répétitions — ils
  bouclent sans limite, chacun avec sa propre condition d'arrêt naturelle.
- Répétition : un appui lance exactement `repeat_count` (champ Répétitions)
  passages de la séquence puis s'arrête tout seul ; un appui pendant qu'elle
  tourne déjà est ignoré. Remplace l'ancien mode "One-shot" (toujours 1 seul
  passage) par ce fonctionnement configurable.
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractScrollArea, QApplication, QDialog, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
    QPushButton, QSpinBox, QTableWidget, QVBoxLayout, QWidget,
)

from core.config import config
from core.i18n import t
from features.macro_simple.hotkey_listener import HotkeyTriggerListener
from features.macro_simple.macro_simple import (
    ACTION_KEY, ACTION_MOUSE, MacroSimpleConfig, MacroStep,
    TRIGGER_HOLD, TRIGGER_REPEAT, TRIGGER_TOGGLE, save_macro_simple,
)
from features.macro_simple.player import MacroPlayerThread
from features.macro_simple.recorder import MacroRecorder
from ui.action_capture_widget import ActionCaptureWidget
from ui.animated_button import AnimatedButton
from ui.key_capture_widget import KeyCaptureWidget
from ui.mouse_coords_overlay import MouseCoordsOverlay
from ui.status_colors import STATUS_CRITICAL, STATUS_NEUTRAL, STATUS_OK
from ui.styled_dropdown import StyledDropdown
from ui.toggle_switch import ToggleSwitch
from ui.trash_icon_button import TrashIconButton

MAX_SLOTS = 10
_FIELD_HEIGHT = 32
_LABEL_GAP = 5  # -10% (2e passe, cumulée avec la précédente : 7 -> 6 -> 5)
# Largeurs fixes pour une rangée régulière (même principe que
# _HEX_FIELD_WIDTH/_COORD_FIELD_WIDTH dans macro_pixel_tab.py) plutôt que de
# laisser chaque champ prendre sa largeur naturelle (StyledDropdown/QSpinBox
# et KeyCaptureWidget n'ont pas la même largeur "par défaut", ce qui donnait
# des écarts irréguliers entre colonnes). Réduits de 25% (150 -> 112) par
# rapport à la valeur d'origine mesurée pour "XButton1"/"XButton2" sans
# troncature : à cette largeur réduite, KeyCaptureWidget/StyledDropdown
# élident maintenant proprement (voir _refresh_text dans les deux classes)
# plutôt que de couper le texte n'importe où.
_HOTKEY_FIELD_WIDTH = 112
_MODE_FIELD_WIDTH = 112
_REPEAT_FIELD_WIDTH = 70
_LOOP_DELAY_FIELD_WIDTH = 90

# QMenu est une fenêtre top-level détachée (comme le popup natif d'un
# QComboBox, voir ui/styled_dropdown.py pour l'historique du problème) :
# fond+bordure posés sur l'instance directement, avec WA_TranslucentBackground
# pour que les coins soient vraiment découpés par le compositeur au lieu de
# rester carrés sous un border-radius purement QSS.
_CONTEXT_MENU_QSS = """
QMenu {
    background-color: #202027;
    color: #E7E9EE;
    border: 1px solid #17B897;
    border-radius: 8px;
    padding: 4px;
    font-size: 9px;
}
QMenu::item {
    padding: 4px 12px;
    border-radius: 6px;
}
QMenu::item:selected {
    background-color: transparent;
    color: #17B897;
}
"""


def _build_styled_menu(parent: QWidget) -> QMenu:
    menu = QMenu(parent)
    # Un QMenu par défaut a le flag Popup mais PAS FramelessWindowHint
    # (vérifié : `QMenu().windowFlags()` sous Windows renvoie Popup=True,
    # FramelessWindowHint=False). Sans ce flag, la fenêtre native gardée par
    # le système a son propre cadre rectangulaire opaque sous le contenu —
    # WA_TranslucentBackground ne rend transparent que ce que QSS/Qt peint
    # PAR-DESSUS, pas ce cadre natif lui-même, d'où les coins carrés qui
    # dépassaient derrière l'arrondi QSS. Il faut les deux ensemble
    # (FramelessWindowHint pour supprimer ce cadre natif, WA_TranslucentBackground
    # pour que le compositeur alpha-blende vraiment les coins découpés par le
    # border-radius) — l'un sans l'autre ne suffit pas.
    menu.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    # Ombre portée NATIVE ajoutée par le compositeur (DWM) en plus du cadre :
    # elle aussi rectangulaire et non découpée par notre arrondi, désactivée
    # pour la même raison.
    menu.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
    menu.setStyleSheet(_CONTEXT_MENU_QSS)
    return menu


COL_ACTION, COL_CURRENT_POS, COL_X, COL_Y, COL_HOLD, COL_DELAY = range(6)


class _StepsTable(QTableWidget):
    """QTableWidget qui garde l'événement wheel pour lui tout seul. Ce
    tableau vit dans la QScrollArea de la page (voir page_macro.py) : par
    défaut, un QAbstractScrollArea qui ne peut plus défiler (en haut/en bas
    de sa propre liste, ou quand toutes les lignes tiennent déjà à l'écran)
    laisse l'événement wheel remonter au parent — d'où un survol du tableau
    qui fait défiler la PAGE entière en plus (ou à la place) du tableau. On
    laisse d'abord QTableWidget gérer le défilement normalement, puis on
    accepte TOUJOURS l'événement ensuite, même en butée, pour que la molette
    au-dessus de ce tableau ne remonte plus jamais vers le QScrollArea
    parent."""

    def wheelEvent(self, event) -> None:
        super().wheelEvent(event)
        event.accept()


class _NoWheelSpinBox(QSpinBox):
    """QSpinBox qui ignore toujours la molette : par défaut, QAbstractSpinBox
    change sa valeur au survol d'un scroll même SANS le focus (comportement
    Qt natif, indépendant de setFocusPolicy) — un simple survol de la cellule
    X/Y/Appui/Délai pendant un scroll de la page ou du tableau modifiait donc
    discrètement sa valeur.

    event.ignore() seul ne suffit PAS ici : contrairement aux évènements
    clavier/souris, un QWheelEvent ignoré ne remonte PAS automatiquement au
    parent par la file d'évènements Qt normale (vérifié empiriquement :
    QApplication.sendEvent sur l'enfant seul ne déclenche jamais le
    wheelEvent du parent, cette remontée n'existe que dans la couche
    QWidgetWindow des évènements matériels réels). On retransmet donc
    explicitement l'évènement au QAbstractScrollArea ancêtre (ici le
    QTableWidget lui-même, voir _StepsTable) pour que la molette au-dessus
    d'une cellule X/Y/Appui/Délai fasse quand même défiler le tableau
    normalement, au lieu de ne plus rien faire du tout.

    StrongFocus (pas WheelFocus, la valeur par défaut d'un QAbstractSpinBox)
    en plus de l'override ci-dessous : Qt.FocusPolicy.WheelFocus veut aussi
    dire "un simple scroll par-dessus, même sans clic, donne le focus
    clavier au champ" — ce override de wheelEvent() empêche déjà tout effet
    tant qu'on n'appelle jamais super().wheelEvent(), mais retirer
    explicitement le bit Wheel de la focus policy garantit qu'aucun aspect
    de l'ancien comportement (focus inclus, pas seulement le changement de
    valeur) ne peut resurgir. Tab/clic restent inchangés (StrongFocus =
    TabFocus | ClickFocus, WheelFocus en plus)."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event) -> None:
        parent = self.parentWidget()
        while parent is not None and not isinstance(parent, QAbstractScrollArea):
            parent = parent.parentWidget()
        if parent is not None:
            QApplication.sendEvent(parent.viewport(), event)
        else:
            event.ignore()

_MODE_OPTIONS = [
    (TRIGGER_HOLD, "page.macro.simple.mode_hold"),
    (TRIGGER_TOGGLE, "page.macro.simple.mode_toggle"),
    (TRIGGER_REPEAT, "page.macro.simple.mode_repeat"),
]


def _labeled_column(label_text: str, widget: QWidget) -> QWidget:
    """Retourne un QWidget (pas juste un layout) : certains appelants ont
    besoin de masquer/afficher le label + son champ comme un seul bloc (ex:
    Répétitions, visible seulement en mode Répétition) — un layout nu n'a
    pas de setVisible()."""
    container = QWidget()
    column = QVBoxLayout(container)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(_LABEL_GAP)
    label = QLabel(label_text)
    label.setStyleSheet(f"font-size: 12px; color: {STATUS_NEUTRAL};")
    column.addWidget(label)
    column.addWidget(widget)
    return container


class MacroSimpleSlot(QWidget):
    """Un emplacement de macro Simple indépendant : sa propre séquence, sa
    propre touche de déclenchement, son propre enregistreur/lecteur/écouteur."""

    macro_saved = pyqtSignal()
    delete_requested = pyqtSignal(object)  # émet self

    def __init__(self, deletable: bool, parent=None):
        super().__init__(parent)
        self._deletable = deletable
        self._recorder: MacroRecorder | None = None
        self._hotkey_listener: HotkeyTriggerListener | None = None
        self._player: MacroPlayerThread | None = None
        self._armed_config: MacroSimpleConfig | None = None
        self._last_saved: MacroSimpleConfig | None = None
        self._coords_overlay: MouseCoordsOverlay | None = None

        QApplication.instance().aboutToQuit.connect(self._stop_all)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)  # -10% (2e passe : 10 -> 9 -> 8)

        control_row = self._build_control_row()

        layout.addLayout(self._build_header_row())
        layout.addLayout(self._build_name_row())
        layout.addLayout(self._build_hotkey_mode_row())
        layout.addLayout(self._build_record_test_row())

        # Marge à droite : sans ça, le tableau touche directement le bord du
        # viewport (donc la scrollbar de la page) une fois la colonne gauche
        # contrainte à sa largeur exacte par la QScrollArea (voir
        # MacroPage.__init__ dans page_macro.py) — même correctif déjà
        # appliqué à control_row ci-dessous et dans macro_pixel_tab.py.
        table_row = QHBoxLayout()
        table_row.addWidget(self._build_table_container())
        table_row.addStretch(1)
        layout.addLayout(table_row)

        self.validation_label = QLabel("")
        self.validation_label.setWordWrap(True)
        self.validation_label.setStyleSheet(f"font-size: 12px; color: {STATUS_CRITICAL};")
        self.validation_label.setVisible(False)
        layout.addWidget(self.validation_label)

        layout.addLayout(control_row)

    # ------------------------------------------------------------------
    # Construction des champs
    # ------------------------------------------------------------------
    def _build_header_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)  # -10% (2e passe : 8 -> 7 -> 6)

        self.slot_title_label = QLabel()
        self.slot_title_label.setStyleSheet("font-size: 14px; font-weight: 700; color: #E7E9EE;")
        row.addWidget(self.slot_title_label)

        if self._deletable:
            self.delete_slot_btn = TrashIconButton()
            self.delete_slot_btn.setToolTip(t("page.macro.simple.delete_slot_btn"))
            self.delete_slot_btn.clicked.connect(lambda: self.delete_requested.emit(self))
            row.addWidget(self.delete_slot_btn)

        row.addStretch(1)
        return row

    def set_slot_number(self, number: int) -> None:
        self.slot_title_label.setText(f"{t('page.macro.simple.slot_label')} {number}")

    def _build_name_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(t("page.macro.simple.name_label"))
        # Largeur fixe (identique à macro_pixel_tab.py) : sans ça, ce champ
        # seul dans sa ligne s'étire sur toute la largeur disponible.
        self.name_input.setFixedWidth(240)
        row.addWidget(self.name_input)
        row.addStretch(1)
        return row

    def _build_hotkey_mode_row(self) -> QHBoxLayout:
        # exclude_click_buttons=True : touche de DÉCLENCHEMENT (démarre/arrête
        # la macro) — clic gauche/droit réservés à l'usage normal de
        # l'interface, voir key_capture_widget.py.
        self.hotkey_capture = KeyCaptureWidget(exclude_click_buttons=True)
        self.hotkey_capture.setFixedSize(_HOTKEY_FIELD_WIDTH, _FIELD_HEIGHT)
        self.hotkey_capture.keyChanged.connect(self._on_hotkey_field_changed)

        self.mode_combo = StyledDropdown()
        for _, label_key in _MODE_OPTIONS:
            self.mode_combo.addItem(t(label_key))
        self.mode_combo.setFixedSize(_MODE_FIELD_WIDTH, _FIELD_HEIGHT)

        # Répétitions n'a de sens qu'en mode "Répétition" (Hold/Toggle
        # bouclent sans limite, bornés par leur propre condition d'arrêt —
        # voir _start_player) : masqué pour les deux autres modes plutôt que
        # juste ignoré, pour ne pas laisser un champ visible sans effet.
        self.repeat_spin = _NoWheelSpinBox()
        self.repeat_spin.setRange(1, 9999)
        self.repeat_spin.setValue(1)
        self.repeat_spin.setFixedSize(_REPEAT_FIELD_WIDTH, _FIELD_HEIGHT)

        self.repeat_field = _labeled_column(t("page.macro.simple.repeat_label"), self.repeat_spin)

        # Délai entre répétitions : n'a de sens qu'en Hold/Toggle (bouclent
        # sans limite tant que la macro est active — voir _start_player),
        # PAS en mode Répétition (nombre de passages déjà borné par
        # Répétitions ci-dessus) — masqué pour ce mode, même principe que
        # repeat_field ci-dessus mais dans l'autre sens.
        self.loop_delay_spin = _NoWheelSpinBox()
        self.loop_delay_spin.setRange(0, 600000)
        self.loop_delay_spin.setValue(0)
        self.loop_delay_spin.setFixedSize(_LOOP_DELAY_FIELD_WIDTH, _FIELD_HEIGHT)

        self.loop_delay_field = _labeled_column(t("page.macro.simple.loop_delay_label"), self.loop_delay_spin)

        row = QHBoxLayout()
        # Sans ça, l'espacement par défaut du style (6px, voir
        # PM_LayoutHorizontalSpacing) s'ajoutait à chaque addSpacing()
        # manuel ci-dessous, donnant un écart différent de celui
        # d'Enregistrer/Voir les coordonnées (qui utilise setSpacing()
        # partout, sans addSpacing() séparé).
        row.setSpacing(0)
        row.addWidget(_labeled_column(t("page.macro.simple.hotkey_label"), self.hotkey_capture))
        row.addSpacing(8)  # -10% (2e passe : 10 -> 9 -> 8)
        row.addWidget(_labeled_column(t("page.macro.simple.mode_label"), self.mode_combo))
        # Même écart qu'entre Activer et Mode ci-dessus (uniforme sur toute
        # la ligne).
        row.addSpacing(8)  # -10% (2e passe : 10 -> 9 -> 8)
        row.addWidget(self.repeat_field)
        row.addWidget(self.loop_delay_field)
        row.addStretch(1)

        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self._on_mode_changed(self.mode_combo.currentIndex())
        return row

    def _on_mode_changed(self, index: int) -> None:
        mode, _ = _MODE_OPTIONS[index]
        self.repeat_field.setVisible(mode == TRIGGER_REPEAT)
        self.loop_delay_field.setVisible(mode in (TRIGGER_HOLD, TRIGGER_TOGGLE))

    def _build_record_test_row(self) -> QHBoxLayout:
        self.record_btn = AnimatedButton(t("page.macro.simple.record_btn"), variant="neutral")
        self.record_btn.clicked.connect(self._on_record_clicked)

        self.view_coords_btn = AnimatedButton(t("page.macro.simple.view_coords_btn"), variant="neutral")
        self.view_coords_btn.clicked.connect(self._on_view_coords_clicked)

        row = QHBoxLayout()
        row.setSpacing(8)  # -10% (2e passe : 10 -> 9 -> 8)
        row.addWidget(self.record_btn)
        row.addWidget(self.view_coords_btn)
        row.addStretch(1)
        return row

    def _on_view_coords_clicked(self) -> None:
        if self._coords_overlay is not None:
            self._coords_overlay.close()
            return
        self._coords_overlay = MouseCoordsOverlay()
        self._coords_overlay.closed.connect(self._on_coords_overlay_closed)
        self._coords_overlay.show()
        self.view_coords_btn.setText(t("page.macro.simple.hide_coords_btn"))

    def _on_coords_overlay_closed(self) -> None:
        self._coords_overlay = None
        self.view_coords_btn.setText(t("page.macro.simple.view_coords_btn"))

    def _build_table(self) -> QTableWidget:
        table = _StepsTable(0, 6)
        table.setHorizontalHeaderLabels([
            t("page.macro.simple.col_action"),
            t("page.macro.simple.col_current_pos"),
            t("page.macro.simple.col_x"),
            t("page.macro.simple.col_y"),
            t("page.macro.simple.col_hold_ms"),
            t("page.macro.simple.col_delay_ms"),
        ])
        table.verticalHeader().setVisible(False)
        # NoSelection (pas SingleSelection) : cette table n'a AUCUN
        # QTableWidgetItem réel (uniquement des cellWidget, voir
        # _add_step_row), donc la sélection Qt native n'a plus aucun usage
        # fonctionnel ici (le menu contextuel utilise table.rowAt(pos), pas
        # la sélection courante). Un clic — ou pire, un clic droit maintenu
        # + glissé, qui étend la sélection sur tout MouseMove reçu tant qu'un
        # bouton est tenu, quel qu'il soit — déclenchait donc un surlignage
        # de ligne plein (peint par la vue elle-même via QPalette.Highlight,
        # PAS par QSS ::item:selected qui ne matche jamais rien ici) sans
        # aucune utilité. Un event filter avait été tenté pour bloquer
        # spécifiquement les clics/glissés sans désactiver la sélection,
        # mais il interférait avec le grab souris implicite de Qt et rendait
        # les spinbox X/Y intermittentes au clic — NoSelection supprime le
        # mécanisme de sélection à la racine, sans ce risque.
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        # Pas de bandes alternées : juste un fond neutre uniforme.
        table.setAlternatingRowColors(False)
        table.setShowGrid(False)
        table.setFrameShape(QFrame.Shape.NoFrame)
        # Colonnes à largeur fixe, non redimensionnables à la souris (glisser
        # la ligne de titre ne fait plus rien).
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        # Largeurs mesurées par rendu pixel RÉEL (de vraies polices Windows
        # chargées, pas l'environnement de test par défaut qui n'en a
        # aucune) : sizeHint() d'un QSpinBox surestime très largement son
        # besoin réel (mesuré ~104px pour "600000" en isolation, alors que le
        # texte tient très confortablement sur bien moins une fois affiché
        # dans sa vraie cellule) — ET, à l'inverse, QTableWidget.setCellWidget
        # réserve une marge fixe d'environ 6px de chaque côté entre la
        # cellule et le widget qu'elle contient (vérifié : `cellWidget(...)
        # .geometry()` a une largeur/position ~12px plus petite que
        # `columnWidth()`), invisible sur des colonnes larges (83px,
        # l'ancienne valeur) mais qui rogne le texte si la colonne est
        # réduite sans en tenir compte. Toutes les largeurs ci-dessous sont
        # donc vérifiées par capture d'écran RÉELLE (pas juste sizeHint) sur
        # leur pire cas ("-10000"/"600000"/"XButton2"/"printscreen"), avec une
        # marge de sécurité confortable.
        # Le cadre du tableau (QFrame.tableCard, voir _build_table_container)
        # doit tenir dans les mêmes 453px que le reste de la page (voir
        # _build_green_separator(453) dans macro_pixel_tab.py, la largeur de
        # référence du panneau) : la colonne "Position actuelle" a été ajoutée
        # SANS élargir le cadre, en resserrant les autres colonnes plutôt
        # (padding QSpinBox/QHeaderView réduit ci-dessous, voir
        # QSpinBox.tableCellSpin et QHeaderView::section dans theme.qss) —
        # élargir le cadre à 505px avait fait déborder le tableau hors du
        # panneau visible (la colonne Délai se retrouvait coupée à droite).
        table.setColumnWidth(COL_ACTION, 103)
        table.setColumnWidth(COL_CURRENT_POS, 62)
        table.setColumnWidth(COL_X, 68)
        table.setColumnWidth(COL_Y, 68)
        table.setColumnWidth(COL_HOLD, 76)
        table.setColumnWidth(COL_DELAY, 76)
        table.horizontalHeaderItem(COL_CURRENT_POS).setToolTip(t("page.macro.simple.col_current_pos_tooltip"))
        # La dernière colonne absorbe l'espace restant : sans ça, la somme
        # des largeurs fixes est plus étroite que le tableau lui-même, et la
        # ligne de titre s'arrête avant le bord droit du cadre au lieu de le
        # remplir. Un `stretch` reste non redimensionnable à la souris (donc
        # cohérent avec les autres colonnes, voir plus haut).
        table.horizontalHeader().setStretchLastSection(True)
        table.setMinimumHeight(160)
        table.setMaximumHeight(260)
        # Pas de scrollbars visibles : le défilement reste possible (molette),
        # seule la barre elle-même est masquée.
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self._on_table_context_menu)
        return table

    def _build_table_container(self) -> QFrame:
        """Le cadre arrondi vit ici, PAS sur le QTableWidget lui-même : voir
        le commentaire sur QFrame.tableCard dans theme.qss.

        Marge à 0 sur les côtés et en haut : la bande d'en-tête (QHeaderView)
        va jusqu'aux bords gauche/droit/haut du cadre SANS marge résiduelle,
        et ses DEUX coins hauts ont eux-mêmes un rayon assorti à celui du
        cadre (QHeaderView::section:first/:last dans theme.qss) — ils
        épousent donc directement la courbe du cadre au lieu d'y peindre un
        coin carré par-dessus. Seule une marge en bas (8px, ≥ le
        border-radius) reste nécessaire : le corps du tableau (QTableWidget,
        carré) n'a lui pas de coins arrondis assortis, donc son coin bas
        doit rester en retrait du coin arrondi du cadre pour ne pas répéter
        le même problème que l'en-tête en haut."""
        container = QFrame()
        container.setProperty("class", "tableCard")
        # Largeur fixe (453px, la même largeur de panneau que le reste de la
        # page — voir _build_table pour pourquoi ce n'est plus 505) : sans
        # ça, ce cadre s'étire pour remplir tout l'espace restant de sa ligne
        # et déborde à droite par rapport à Enregistrer/Réinitialiser et au
        # trait vert (tous deux alignés sur cette même largeur, voir
        # _build_control_row et __init__ ci-dessus).
        container.setFixedWidth(453)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 8)
        self.table = self._build_table()
        layout.addWidget(self.table)
        return container

    def _on_table_context_menu(self, pos) -> None:
        """Clic droit sur une ligne : "Ajouter une étape" (à la fin si le
        clic n'est sur aucune ligne, sinon juste après) et "Supprimer cette
        étape" (si le clic est sur une ligne) — remplace les boutons
        Ajouter/Supprimer.

        EXCEPTION : si une capture de touche (ActionCaptureWidget, colonne
        Action) est active sur une ligne, ce même clic droit doit être
        capturé par elle comme touche "RButton" (voir ActionCaptureWidget.
        is_listening), pas ouvrir ce menu — sinon les deux réagiraient au
        même clic physique. Hors capture active, le clic droit garde son
        comportement normal partout dans le tableau, y compris sur la
        colonne Action elle-même. Le garde-fou couvre aussi le court instant
        JUSTE APRÈS qu'un clic droit vient de capturer "RButton" (voir
        ActionCaptureWidget.blocks_context_menu) : Windows déclenche
        WM_CONTEXTMENU au relâchement de ce même clic droit, un peu après que
        pynput l'ait déjà traité comme capture — sans ce délai, ce menu
        s'ouvrirait quand même juste après, donnant l'impression que
        "RButton" venait d'être retiré."""
        if self._any_action_capture_listening():
            return

        row = self.table.rowAt(pos.y())
        menu = _build_styled_menu(self.table)
        add_action = menu.addAction(t("page.macro.simple.ctx_add_after"))
        delete_action = menu.addAction(t("page.macro.simple.ctx_delete")) if row >= 0 else None

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is add_action:
            insert_at = row + 1 if row >= 0 else self.table.rowCount()
            self._add_step_row(MacroStep(action=ACTION_KEY, value="", hold_ms=50, delay_after_ms=50), at_row=insert_at)
        elif delete_action is not None and chosen is delete_action:
            # Coupe une éventuelle écoute pynput encore active sur cette
            # ligne avant de la détruire : Qt détruit le widget de cellule,
            # mais pas le thread d'écoute pynput sous-jacent (objet Python
            # indépendant du cycle de vie Qt) — voir _cancel_all_row_listeners.
            action_capture = self._cell_widget(row, COL_ACTION)
            if action_capture is not None:
                action_capture.cancel_listening()
            self.table.removeRow(row)
            # La ligne 0 a pu changer d'identité (celle supprimée l'était
            # peut-être) : voir _refresh_first_row_spacing.
            self._refresh_first_row_spacing()

    def _any_action_capture_listening(self) -> bool:
        for row in range(self.table.rowCount()):
            action_capture = self._cell_widget(row, COL_ACTION)
            if action_capture is not None and action_capture.blocks_context_menu():
                return True
        return False

    def _build_control_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)  # -10% (2e passe : 10 -> 9 -> 8)

        self.start_toggle = ToggleSwitch(checked=False)
        self.start_toggle.toggled.connect(self._on_start_toggle)
        row.addWidget(self.start_toggle)

        self.status_label = QLabel(t("page.macro.simple.status_stopped"))
        self.status_label.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {STATUS_NEUTRAL};")
        row.addWidget(self.status_label)
        row.addStretch(1)

        self.save_btn = AnimatedButton(t("page.macro.simple.save_btn"), variant="neutral")
        self.save_btn.clicked.connect(self._on_save_clicked)
        row.addWidget(self.save_btn)

        self.reset_btn = AnimatedButton(t("page.macro.simple.reset_btn"), variant="neutral")
        self.reset_btn.clicked.connect(self._on_reset_clicked)
        row.addWidget(self.reset_btn)
        # 35px (pas juste les 14px de marge scrollbar) : aligne le bord droit
        # de Réinitialiser avec celui du groupe des 3 onglets "Macro type"
        # tout en haut de la page (mesuré empiriquement).
        row.addSpacing(35)
        return row

    # ------------------------------------------------------------------
    # Tableau des étapes
    # ------------------------------------------------------------------
    _ROW_HEIGHT = 38
    _CELL_HEIGHT = 28

    def _cell_widget(self, row: int, col: int) -> QWidget | None:
        """Comme table.cellWidget(row, col), mais retourne le contrôle RÉEL
        (ActionCaptureWidget/QSpinBox) plutôt que son conteneur de centrage
        (voir _wrap_centered) — seul _add_step_row doit connaître ce
        conteneur, tout le reste du code continue de manipuler les contrôles
        eux-mêmes sans s'en soucier."""
        container = self.table.cellWidget(row, col)
        if container is None:
            return None
        return container.layout().itemAt(0).widget()

    # (_ROW_HEIGHT - _CELL_HEIGHT) / 2 : marge haute = marge basse d'une
    # ligne "normale" une fois son widget centré (voir _wrap_centered).
    _ROW_MARGIN = (_ROW_HEIGHT - _CELL_HEIGHT) // 2

    @staticmethod
    def _wrap_centered(widget: QWidget, top: int, bottom: int, center: bool = False) -> QWidget:
        """QTableWidget.setCellWidget ne centre PAS verticalement un widget
        de hauteur fixe plus petite que sa ligne (vérifié par rendu pixel
        réel : le widget colle au bord HAUT de la ligne, toute la marge de
        fin de ligne se retrouvant en BAS) — ce conteneur (sans hauteur
        fixe, donc étiré par la table pour remplir toute la ligne) avec des
        marges explicites au-dessus/en dessous centre réellement le widget.
        Voir _cell_widget ci-dessus pour le retrouver ensuite, et
        _refresh_first_row_spacing pour pourquoi `top`/`bottom` varient
        selon la ligne plutôt que d'être toujours _ROW_MARGIN des deux
        côtés.

        `center=True` (ActionCaptureWidget/QSpinBox n'en ont PAS besoin,
        laissés à leur comportement par défaut) : à N'UTILISER QUE pour un
        widget significativement plus ÉTROIT que sa colonne (ex: ToggleSwitch,
        44px de large, colonne "Position actuelle") — passer une alignment à
        addWidget() désactive aussi l'étirement HORIZONTAL habituel du
        widget pour remplir la colonne. Appliqué par erreur à un QSpinBox
        (qui n'a pas de largeur fixe), Qt le dimensionne alors à son
        sizeHint() naturel (mesuré ~104px pour "600000", bien plus large que
        la colonne) au lieu de l'largeur de la colonne — le texte est alors
        rogné par le clipping de la cellule, PAS parce qu'il ne "rentre" pas
        (vérifié : le même texte tient très confortablement à 50px de large
        une fois le widget correctement contraint à cette largeur)."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, top, 0, bottom)
        layout.setSpacing(0)
        if center:
            layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignCenter)
        else:
            layout.addWidget(widget)
        return container

    # Écart fixe (mesuré par rendu pixel réel, sur plusieurs valeurs de
    # _ROW_MARGIN) entre le bas de l'en-tête et le haut du corps du tableau,
    # INDÉPENDANT de la hauteur de l'en-tête (agrandir le padding de
    # QHeaderView::section ne change rien à cet écart) — voir
    # _refresh_first_row_spacing pour comment il s'en sert.
    _HEADER_TO_BODY_GAP = 2

    def _refresh_first_row_spacing(self) -> None:
        """L'écart entre le bas de l'en-tête et le haut de la ligne 0 vaut
        _HEADER_TO_BODY_GAP (fixe, imposé par Qt) + la marge haute de la
        ligne 0 elle-même — alors que l'écart entre deux lignes quelconques
        vaut marge basse + marge haute = 2×_ROW_MARGIN (une fois leurs
        widgets centrés, voir _wrap_centered). Pour que les deux
        correspondent, la ligne 0 doit donc avoir une marge haute de
        2×_ROW_MARGIN - _HEADER_TO_BODY_GAP (et une hauteur de ligne
        agrandie d'autant pour l'accueillir) plutôt que _ROW_MARGIN comme
        les autres lignes — vérifié empiriquement par rendu pixel à deux
        valeurs de _ROW_MARGIN différentes, la formule tient dans les deux
        cas. Appelé après CHAQUE changement de structure du tableau (ajout/
        suppression/rechargement), car "la ligne 0" peut changer de contenu
        à tout moment."""
        first_row_top = 2 * self._ROW_MARGIN - self._HEADER_TO_BODY_GAP
        for row in range(self.table.rowCount()):
            is_first = row == 0
            top = first_row_top if is_first else self._ROW_MARGIN
            row_height = self._ROW_HEIGHT + (top - self._ROW_MARGIN) if is_first else self._ROW_HEIGHT
            self.table.setRowHeight(row, row_height)
            for col in range(self.table.columnCount()):
                container = self.table.cellWidget(row, col)
                if container is not None:
                    container.layout().setContentsMargins(0, top, 0, self._ROW_MARGIN)

    def _build_cell_spin(self, value: int, minimum: int, maximum: int, center_text: bool = False) -> QSpinBox:
        """QSpinBox pour une cellule du tableau (X/Y/Appui/Délai) : simple,
        sans event filter ni logique de blocage de clic. `_NoWheelSpinBox`
        ne surcharge QUE wheelEvent (empêche la molette de changer la valeur
        sans clic, voir sa docstring) — clic et saisie clavier restent le
        comportement par défaut d'un QSpinBox, jamais intercepté. NoButtons
        (pas de flèches +/-) : à ces largeurs de colonne, elles ne laissaient
        quasiment plus de place au nombre lui-même. NoContextMenu : sans ça,
        un clic droit affiche le menu d'édition natif de Qt (Couper/Copier/
        Coller) EN PLUS de notre menu "Ajouter une étape"/"Supprimer cette
        étape" — l'évènement ignoré remonte alors au tableau parent
        (vérifié : la position transmise est bien traduite dans son repère,
        table.rowAt() retrouve la bonne ligne), qui affiche seulement notre
        menu personnalisé."""
        spin = _NoWheelSpinBox()
        spin.setProperty("class", "tableCellSpin")
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setFixedHeight(self._CELL_HEIGHT)
        spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        spin.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        if center_text:
            spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return spin

    def _add_step_row(self, step: MacroStep, at_row: int | None = None) -> int:
        row = self.table.rowCount() if at_row is None else at_row
        self.table.insertRow(row)
        self.table.setRowHeight(row, self._ROW_HEIGHT)

        action_capture = ActionCaptureWidget()
        action_capture.set_action(step.action, step.value, step.x, step.y)
        action_capture.setFixedHeight(self._CELL_HEIGHT)
        action_capture.changed.connect(self._on_any_row_action_changed)
        self.table.setCellWidget(row, COL_ACTION, self._wrap_centered(action_capture, self._ROW_MARGIN, self._ROW_MARGIN))

        # "Curseur" : quand actif, l'action se joue là où se trouve déjà le
        # curseur au moment du rejeu (voir player.py), X/Y de CETTE ligne
        # deviennent alors inutilisés — d'où leur désactivation dans
        # _update_row_enabled_state ci-dessous, appelée au toggle.
        current_pos_toggle = ToggleSwitch(checked=step.use_current_position)
        current_pos_toggle.setToolTip(t("page.macro.simple.col_current_pos_tooltip"))
        current_pos_toggle.toggled.connect(self._on_current_pos_toggled)
        self.table.setCellWidget(
            row, COL_CURRENT_POS,
            self._wrap_centered(current_pos_toggle, self._ROW_MARGIN, self._ROW_MARGIN, center=True),
        )

        x_spin = self._build_cell_spin(step.x, -10000, 10000, center_text=True)
        self.table.setCellWidget(row, COL_X, self._wrap_centered(x_spin, self._ROW_MARGIN, self._ROW_MARGIN))

        y_spin = self._build_cell_spin(step.y, -10000, 10000, center_text=True)
        self.table.setCellWidget(row, COL_Y, self._wrap_centered(y_spin, self._ROW_MARGIN, self._ROW_MARGIN))

        hold_spin = self._build_cell_spin(step.hold_ms, 0, 600000)
        self.table.setCellWidget(row, COL_HOLD, self._wrap_centered(hold_spin, self._ROW_MARGIN, self._ROW_MARGIN))

        delay_spin = self._build_cell_spin(step.delay_after_ms, 0, 600000)
        self.table.setCellWidget(row, COL_DELAY, self._wrap_centered(delay_spin, self._ROW_MARGIN, self._ROW_MARGIN))

        self._update_row_enabled_state(row)
        self._refresh_first_row_spacing()
        return row

    def _on_any_row_action_changed(self) -> None:
        widget = self.sender()
        for row in range(self.table.rowCount()):
            if self._cell_widget(row, COL_ACTION) is widget:
                self._update_row_enabled_state(row)
                return

    def _on_current_pos_toggled(self) -> None:
        widget = self.sender()
        for row in range(self.table.rowCount()):
            if self._cell_widget(row, COL_CURRENT_POS) is widget:
                self._update_row_enabled_state(row)
                return

    def _update_row_enabled_state(self, row: int) -> None:
        x_spin = self._cell_widget(row, COL_X)
        y_spin = self._cell_widget(row, COL_Y)
        current_pos_toggle = self._cell_widget(row, COL_CURRENT_POS)
        # X/Y restent TOUJOURS cliquables/éditables, quelle que soit l'action
        # de la ligne (clavier, souris, ou pas encore définie) — seul le
        # toggle "Curseur" les désactive, seule raison légitime de ne pas
        # s'en servir (l'action se joue alors à la position actuelle du
        # curseur). Les lier en plus au type d'action (comme avant) rendait
        # ce champ mystérieusement désactivé selon ce qui était capturé dans
        # une AUTRE colonne, ce qui ressemblait à un bug de saisie — alors
        # que _row_to_step remet déjà x=y=0 à la sauvegarde si l'action
        # n'est pas une souris, donc aucune valeur non pertinente n'est
        # jamais persistée/rejouée.
        use_current_position = current_pos_toggle.isChecked()
        x_spin.setEnabled(not use_current_position)
        y_spin.setEnabled(not use_current_position)

    def _row_to_step(self, row: int) -> MacroStep:
        action_capture = self._cell_widget(row, COL_ACTION)
        x_spin = self._cell_widget(row, COL_X)
        y_spin = self._cell_widget(row, COL_Y)
        current_pos_toggle = self._cell_widget(row, COL_CURRENT_POS)
        hold_spin = self._cell_widget(row, COL_HOLD)
        delay_spin = self._cell_widget(row, COL_DELAY)
        action = action_capture.action() or ACTION_KEY
        return MacroStep(
            action=action, value=action_capture.value(),
            x=x_spin.value() if action == ACTION_MOUSE else 0,
            y=y_spin.value() if action == ACTION_MOUSE else 0,
            hold_ms=hold_spin.value(),
            delay_after_ms=delay_spin.value(),
            use_current_position=action == ACTION_MOUSE and current_pos_toggle.isChecked(),
        )

    def _read_steps(self) -> list[MacroStep]:
        return [self._row_to_step(row) for row in range(self.table.rowCount())]

    def _cancel_all_row_listeners(self) -> None:
        """Coupe toute écoute pynput encore active sur une cellule Action,
        avant de vider/recharger le tableau — même raison que dans
        _on_table_context_menu (le thread d'écoute pynput ne suit pas le
        cycle de vie Qt du widget)."""
        for row in range(self.table.rowCount()):
            action_capture = self._cell_widget(row, COL_ACTION)
            if action_capture is not None:
                action_capture.cancel_listening()

    def _populate_table(self, steps: list[MacroStep]) -> None:
        self._cancel_all_row_listeners()
        self.table.setRowCount(0)
        for step in steps:
            self._add_step_row(step)

    # ------------------------------------------------------------------
    # Enregistrement de la séquence (capture globale clavier/souris)
    # ------------------------------------------------------------------
    def _on_record_clicked(self) -> None:
        if self._recorder is not None:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        # Vide le tableau AVANT de commencer : l'enregistrement remplace
        # toujours la séquence actuellement affichée (comme avant), sauf que
        # les nouvelles lignes arrivent maintenant une par une au fur et à
        # mesure plutôt que toutes d'un coup à l'arrêt (voir
        # _on_step_recorded/_on_step_delay_updated).
        self._populate_table([])

        window = self.window()
        exclude_rect = window.frameGeometry() if window is not None else None
        self._recorder = MacroRecorder(exclude_rect=exclude_rect, parent=self)
        self._recorder.stopped_by_escape.connect(self._stop_recording)
        self._recorder.step_recorded.connect(self._on_step_recorded)
        self._recorder.step_delay_updated.connect(self._on_step_delay_updated)
        self._recorder.start()

        self.record_btn.setText(t("page.macro.simple.stop_record_btn"))

    def _on_step_recorded(self, step: MacroStep) -> None:
        self._add_step_row(step)

    def _on_step_delay_updated(self, index: int, delay_ms: int) -> None:
        # Le délai d'une étape n'est connu qu'une fois l'action SUIVANTE
        # commencée (voir recorder.py) : la ligne apparaît donc d'abord avec
        # "0", puis se corrige toute seule dès que la prochaine action démarre.
        delay_spin = self._cell_widget(index, COL_DELAY)
        if delay_spin is not None:
            delay_spin.setValue(delay_ms)

    def _stop_recording(self) -> None:
        if self._recorder is None:
            return
        self._recorder.stop()
        self._recorder = None
        self.record_btn.setText(t("page.macro.simple.record_btn"))

    # ------------------------------------------------------------------
    # Construction / validation de la config
    # ------------------------------------------------------------------
    def is_empty(self) -> bool:
        return not self.name_input.text().strip() and self.table.rowCount() == 0

    def _build_macro_config(self, name: str) -> MacroSimpleConfig | None:
        steps = self._read_steps()
        hotkey = self.hotkey_capture.key()

        if not hotkey or not steps:
            self.validation_label.setText(t("page.macro.simple.error_incomplete_config"))
            self.validation_label.setVisible(True)
            return None

        mode, _ = _MODE_OPTIONS[self.mode_combo.currentIndex()]
        # Hold/Toggle bouclent la séquence SANS LIMITE tant que la macro est
        # active (voir _start_player) : sans un seul délai après une étape,
        # rien ne freine cette boucle — un enchaînement en rafale, à pleine
        # vitesse CPU, potentiellement des milliers de passages par seconde.
        # Le mode Répétition n'est pas concerné : borné par son propre
        # nombre de passages, il s'arrête de lui-même même sans délai.
        if mode in (TRIGGER_HOLD, TRIGGER_TOGGLE) and not any(step.delay_after_ms > 0 for step in steps):
            self.validation_label.setText(t("page.macro.simple.error_no_delay"))
            self.validation_label.setVisible(True)
            return None

        self.validation_label.setVisible(False)
        return MacroSimpleConfig(
            name=name,
            hotkey=hotkey,
            trigger_mode=mode,
            repeat_count=self.repeat_spin.value(),
            loop_delay_ms=self.loop_delay_spin.value() if mode in (TRIGGER_HOLD, TRIGGER_TOGGLE) else 0,
            steps=steps,
        )

    # ------------------------------------------------------------------
    # Start / Stop (arme/désarme l'écoute de la touche de déclenchement)
    # ------------------------------------------------------------------
    def _on_start_toggle(self, checked: bool) -> None:
        if not checked:
            self._stop_listener()
            return

        if not bool(config.get("macros_globally_enabled", True)):
            self.validation_label.setText(t("page.macro.simple.error_kill_switch"))
            self.validation_label.setVisible(True)
            self.start_toggle.setChecked(False, animate=False)
            return

        macro = self._build_macro_config(self.name_input.text().strip() or t("page.macro.simple.name_placeholder"))
        if macro is None:
            self.start_toggle.setChecked(False, animate=False)
            return

        self._armed_config = macro
        self._hotkey_listener = HotkeyTriggerListener(macro.hotkey, self)
        self._hotkey_listener.pressed.connect(self._on_hotkey_pressed)
        self._hotkey_listener.released.connect(self._on_hotkey_released)
        self._hotkey_listener.start()

        self.status_label.setText(t("page.macro.simple.status_listening"))
        self.status_label.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {STATUS_OK};")

    def _on_hotkey_field_changed(self, new_key: str) -> None:
        """Si la macro est déjà armée (interrupteur "Activer" ON) et qu'on
        change la touche de déclenchement pendant qu'elle tourne, réarme
        immédiatement l'écoute native sur la nouvelle touche (l'ancienne
        redevient libre) plutôt que d'attendre un cycle OFF/ON — même
        principe de prise en compte immédiate que pour le reste de la
        config (voir _refresh_armed_config)."""
        if self._hotkey_listener is None or self._armed_config is None:
            return
        if not new_key or new_key == self._armed_config.hotkey:
            return
        self._hotkey_listener.stop()
        self._hotkey_listener = HotkeyTriggerListener(new_key, self)
        self._hotkey_listener.pressed.connect(self._on_hotkey_pressed)
        self._hotkey_listener.released.connect(self._on_hotkey_released)
        self._hotkey_listener.start()
        self._refresh_armed_config()

    def stop_if_running(self) -> None:
        """Appelé par MacroSimpleTab quand le coupe-circuit global est
        désactivé, ou quand cet emplacement est supprimé."""
        self._stop_listener()

    def _stop_listener(self) -> None:
        if self._hotkey_listener is not None:
            self._hotkey_listener.stop()
            self._hotkey_listener = None
        self._stop_player()
        self._armed_config = None
        self.start_toggle.setChecked(False, animate=False)
        self.status_label.setText(t("page.macro.simple.status_stopped"))
        self.status_label.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {STATUS_NEUTRAL};")
        if self._coords_overlay is not None:
            self._coords_overlay.close()

    def _stop_all(self) -> None:
        """Appelé à la fermeture de l'application : coupe tout ce qui
        pourrait encore tourner (enregistrement, écoute, rejeu)."""
        if self._recorder is not None:
            self._recorder.stop()
            self._recorder = None
        self._cancel_all_row_listeners()
        self._stop_listener()

    # ------------------------------------------------------------------
    # Rejeu déclenché par la touche de déclenchement (Hold/Toggle/Répétition)
    # ------------------------------------------------------------------
    def _refresh_armed_config(self) -> None:
        """Relit la config actuellement affichée à l'écran (touches,
        timings, mode, répétitions...) juste avant de (dé)déclencher le
        rejeu : une macro active applique ainsi immédiatement toute
        modification faite pendant qu'elle tourne, sans avoir à désactiver
        puis réactiver l'interrupteur "Activer". Si l'édition en cours rend
        la config momentanément invalide (ex : toutes les lignes supprimées),
        on garde la dernière config valide plutôt que d'interrompre
        brutalement une macro déjà armée."""
        if self._armed_config is None:
            return
        fresh = self._build_macro_config(self._armed_config.name)
        if fresh is not None:
            self._armed_config = fresh

    def _on_hotkey_pressed(self) -> None:
        if self._armed_config is None:
            return
        self._refresh_armed_config()
        running = self._player is not None and self._player.isRunning()
        mode = self._armed_config.trigger_mode

        if mode == TRIGGER_TOGGLE:
            self._stop_player() if running else self._start_player()
        elif mode in (TRIGGER_HOLD, TRIGGER_REPEAT):
            if not running:
                self._start_player()

    def _on_hotkey_released(self) -> None:
        if self._armed_config is not None and self._armed_config.trigger_mode == TRIGGER_HOLD:
            self._stop_player()

    def _start_player(self) -> None:
        macro = self._armed_config
        # Répétitions ne s'applique qu'au mode Répétition (nombre fixe puis
        # arrêt automatique) ; Hold/Toggle bouclent sans limite, bornés
        # uniquement par leur propre condition d'arrêt (relâchement / second
        # appui) — pas de notion de "infini" exposée à l'utilisateur, juste
        # dérivée ici du mode choisi.
        is_repeat_mode = macro.trigger_mode == TRIGGER_REPEAT
        repeat_count = macro.repeat_count if is_repeat_mode else 1
        infinite = not is_repeat_mode
        self._player = MacroPlayerThread(macro.steps, repeat_count, infinite, macro.loop_delay_ms, self)
        self._player.finished_playback.connect(self._on_player_finished)
        self._player.error.connect(self._on_player_error)
        self._player.start()
        self.status_label.setText(t("page.macro.simple.status_running"))
        self.status_label.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {STATUS_OK};")

    def _stop_player(self) -> None:
        if self._player is not None and self._player.isRunning():
            self._player.stop()
            self._player.wait(2000)
        self._player = None
        if self._hotkey_listener is not None:
            self.status_label.setText(t("page.macro.simple.status_listening"))
            self.status_label.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {STATUS_OK};")

    def _on_player_finished(self) -> None:
        self._player = None
        if self._hotkey_listener is not None:
            self.status_label.setText(t("page.macro.simple.status_listening"))
            self.status_label.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {STATUS_OK};")

    def _on_player_error(self, message: str) -> None:
        self.validation_label.setText(t("page.macro.simple.error_playback").format(error=message))
        self.validation_label.setVisible(True)

    # ------------------------------------------------------------------
    # Sauvegarde / réinitialisation
    # ------------------------------------------------------------------
    def _on_save_clicked(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            self.validation_label.setText(t("page.macro.simple.error_no_name"))
            self.validation_label.setVisible(True)
            return

        macro = self._build_macro_config(name)
        if macro is None:
            return

        save_macro_simple(macro)
        self._last_saved = macro
        self.macro_saved.emit()

    def _on_reset_clicked(self) -> None:
        # Vide ce qui est actuellement affiché à l'écran, jamais le fichier
        # déjà sauvegardé : `_last_saved` (voir _on_save_clicked/load_macro)
        # n'est PAS touché ici, donc rien n'écrase la dernière sauvegarde sur
        # le disque tant que l'utilisateur ne clique pas explicitement sur
        # "Sauvegarder" après ce reset. Revenir à `_last_saved` (l'ancien
        # comportement) rechargeait la sauvegarde au lieu de vider l'écran —
        # ce que "Réinitialiser" ne doit jamais faire.
        self._reset_to_blank()

    def _reset_to_blank(self) -> None:
        self._stop_listener()
        self.name_input.clear()
        self.hotkey_capture.set_key("")
        self.mode_combo.setCurrentIndex(0)
        self.repeat_spin.setValue(1)
        self.loop_delay_spin.setValue(0)
        self._populate_table([])
        self.validation_label.setVisible(False)

    # ------------------------------------------------------------------
    # Chargement depuis la Bibliothèque
    # ------------------------------------------------------------------
    def load_macro(self, macro: MacroSimpleConfig) -> None:
        self._stop_listener()
        self._last_saved = macro
        self.name_input.setText(macro.name)
        self.hotkey_capture.set_key(macro.hotkey)
        mode_index = next((i for i, (m, _) in enumerate(_MODE_OPTIONS) if m == macro.trigger_mode), 0)
        self.mode_combo.setCurrentIndex(mode_index)
        self.repeat_spin.setValue(max(1, macro.repeat_count))
        self.loop_delay_spin.setValue(max(0, macro.loop_delay_ms))
        self._populate_table(macro.steps)
        self.validation_label.setVisible(False)


class SimpleSlotChooserDialog(QDialog):
    """Popup listant les emplacements existants (libre/occupé) + une option
    "nouvel emplacement" si sous la limite — même principe que
    macro_pixel_tab.SlotChooserDialog, dupliqué ici pour rester autonome
    (chaque onglet garde ses propres clés de traduction)."""

    def __init__(self, options: list[tuple[str, bool]], can_add_new: bool, parent=None):
        super().__init__(parent)
        self._can_add_new = can_add_new
        self.setWindowTitle(t("page.macro.simple.slot_chooser_title"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        prompt = QLabel(t("page.macro.simple.slot_chooser_prompt"))
        prompt.setWordWrap(True)
        prompt.setStyleSheet(f"font-size: 13px; color: {STATUS_NEUTRAL};")
        layout.addWidget(prompt)

        self.list_widget = QListWidget()
        self.list_widget.setMinimumWidth(280)
        for label, is_free in options:
            suffix = (
                t("page.macro.simple.slot_free_suffix") if is_free
                else t("page.macro.simple.slot_occupied_suffix")
            )
            self.list_widget.addItem(QListWidgetItem(f"{label} — {suffix}"))
        if can_add_new:
            self.list_widget.addItem(QListWidgetItem(t("page.macro.simple.slot_new_option")))

        default_row = next((i for i, (_, is_free) in enumerate(options) if is_free), 0)
        self.list_widget.setCurrentRow(default_row)
        layout.addWidget(self.list_widget)

        # Charger / Annuler : même style pour les deux (pas de distinction
        # primaire/secondaire ici), centrés côte à côte, "Charger" à gauche.
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)  # -20% puis -10% x2 (10px -> 8px -> 7px -> 6px)
        btn_row.addStretch(1)
        confirm_btn = QPushButton(t("page.macro.simple.slot_chooser_confirm"))
        confirm_btn.setProperty("class", "secondaryButton")
        confirm_btn.clicked.connect(self.accept)
        btn_row.addWidget(confirm_btn)

        cancel_btn = QPushButton(t("page.macro.simple.slot_chooser_cancel"))
        cancel_btn.setProperty("class", "secondaryButton")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

    def selected_index(self) -> int:
        row = self.list_widget.currentRow()
        if self._can_add_new and row == self.list_widget.count() - 1:
            return -1
        return row


def _build_green_separator(width: int) -> QFrame:
    line = QFrame()
    line.setFixedSize(width, 2)
    line.setStyleSheet(f"background-color: {STATUS_OK}; border: none; border-radius: 1px;")
    return line


class MacroSimpleTab(QWidget):
    """Conteneur de 1 à MAX_SLOTS emplacements MacroSimpleSlot. "Emplacement 1"
    existe toujours et n'est pas supprimable ; les emplacements ajoutés en
    plus le sont — même structure que macro_pixel_tab.PixelMacroTab (limitée
    à 3, pas MAX_SLOTS de ce fichier : chaque onglet a sa propre limite)."""

    macro_saved = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._slots: list[MacroSimpleSlot] = []
        # Séparateur vert précédant CHAQUE emplacement sauf le premier (voir
        # _add_slot/_on_slot_delete_requested) : associé au slot qu'il
        # précède pour pouvoir être retiré avec lui à la suppression.
        self._slot_separators: dict[MacroSimpleSlot, QFrame] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        self._slots_layout = QVBoxLayout()
        self._slots_layout.setSpacing(18)
        layout.addLayout(self._slots_layout)

        # Longueur alignée sur la largeur du cadre du tableau (453px, voir
        # _build_table_container) plutôt que de continuer sur toute la
        # largeur — aligné à gauche pour ne pas être centré/étiré par le
        # layout.
        layout.addWidget(_build_green_separator(453), 0, Qt.AlignmentFlag.AlignLeft)

        self.add_slot_btn = AnimatedButton(t("page.macro.simple.add_slot_btn"), variant="neutral")
        self.add_slot_btn.clicked.connect(self._on_add_slot_clicked)
        add_row = QHBoxLayout()
        add_row.addWidget(self.add_slot_btn)
        add_row.addStretch(1)
        layout.addLayout(add_row)

        layout.addStretch(1)

        self._add_slot(deletable=False)  # Emplacement 1 : toujours présent

    def _add_slot(self, deletable: bool) -> MacroSimpleSlot:
        separator = None
        if self._slots:
            # Un séparateur AVANT ce nouvel emplacement (pas seulement un
            # seul, tout en bas, après le dernier) : garde une ligne verte
            # entre CHAQUE emplacement, pas seulement après le dernier.
            separator = _build_green_separator(453)
            self._slots_layout.addWidget(separator, 0, Qt.AlignmentFlag.AlignLeft)

        slot = MacroSimpleSlot(deletable=deletable)
        if separator is not None:
            self._slot_separators[slot] = separator
        slot.macro_saved.connect(self.macro_saved.emit)
        slot.delete_requested.connect(self._on_slot_delete_requested)
        self._slots.append(slot)
        self._slots_layout.addWidget(slot)
        self._renumber_slots()
        self._update_add_button_state()
        return slot

    def _on_add_slot_clicked(self) -> None:
        if len(self._slots) >= MAX_SLOTS:
            return
        self._add_slot(deletable=True)

    def _on_slot_delete_requested(self, slot: MacroSimpleSlot) -> None:
        if slot not in self._slots or len(self._slots) <= 1:
            return
        slot.stop_if_running()
        separator = self._slot_separators.pop(slot, None)
        if separator is not None:
            self._slots_layout.removeWidget(separator)
            separator.setParent(None)
            separator.deleteLater()
        self._slots_layout.removeWidget(slot)
        slot.setParent(None)
        slot.deleteLater()
        self._slots.remove(slot)
        self._renumber_slots()
        self._update_add_button_state()

    def _renumber_slots(self) -> None:
        for index, slot in enumerate(self._slots):
            slot.set_slot_number(index + 1)

    def _update_add_button_state(self) -> None:
        self.add_slot_btn.setEnabled(len(self._slots) < MAX_SLOTS)

    def stop_if_running(self) -> None:
        for slot in self._slots:
            slot.stop_if_running()

    def request_load(self, macro: MacroSimpleConfig) -> None:
        """Charge une macro cliquée dans la Bibliothèque : demande toujours
        confirmation via SimpleSlotChooserDialog, même s'il n'y a qu'un seul
        emplacement — sert de garde-fou contre un chargement accidentel qui
        écraserait silencieusement la config en cours dans cet emplacement."""
        options = [
            (f"{t('page.macro.simple.slot_label')} {i + 1}", slot.is_empty())
            for i, slot in enumerate(self._slots)
        ]
        can_add_new = len(self._slots) < MAX_SLOTS
        dialog = SimpleSlotChooserDialog(options, can_add_new, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        index = dialog.selected_index()
        if index == -1:
            new_slot = self._add_slot(deletable=True)
            new_slot.load_macro(macro)
        else:
            self._slots[index].load_macro(macro)
