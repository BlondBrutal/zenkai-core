"""
Onglet "Macro type 2" (Pixel) de la page Macro : jusqu'à 3 emplacements
indépendants (PixelMacroSlot), chacun avec son propre pixel surveillé (couleur
exacte, sans tolérance), sa touche de réaction et son thread de détection
(features/macro_pixel/pixel_watcher.py) qui reprend le comportement de
déclenchement de "Global Macro v2.ahk" (page TP) : front montant de
correspondance de couleur, sans mode ni délai anti-spam configurables
séparément (voir pixel_watcher.py).

Chaque emplacement a aussi son propre "changement rapide de touche" (repris
de ChangementToucheHandler dans le même fichier AHK) : une touche dédiée,
écoutée globalement même hors focus (features/macro_pixel/
key_swap_listener.py), échange à la volée la touche de réaction avec une
seconde touche cible — pratique pour alterner entre deux actions liées au
même déclencheur sans rouvrir la config.

PixelMacroTab est le conteneur : "Emplacement 1" existe toujours (non
supprimable), suivi d'une séparation verte puis d'un bouton "Ajouter un
nouvel emplacement" (désactivé à 3 emplacements). Chaque emplacement ajouté
en plus a son propre bouton "Supprimer l'emplacement".

La surveillance de chaque emplacement continue de tourner même si on quitte
cet onglet ou change de page : c'est tout le principe d'une macro (rester
active pendant que l'utilisateur joue, pas seulement pendant qu'il regarde
cet écran) — donc pas d'arrêt automatique sur hideEvent, contrairement au
monitoring en direct de la page Performance. Chaque watcher s'arrête sur
demande explicite (interrupteur Start/Off de son emplacement, coupe-circuit
global, suppression de l'emplacement) ou à la fermeture de l'application.

Plusieurs emplacements actifs simultanément tournent chacun dans leur propre
QThread indépendant (features/macro_pixel/pixel_watcher.py) : le coût CPU
supplémentaire par emplacement est faible (voir le docstring de
pixel_watcher.py) — pas de mutualisation nécessaire pour 3 emplacements.
"""
import re

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QDoubleValidator, QIntValidator
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from core.config import config
from core.i18n import t
from features.macro_pixel.key_swap_listener import KeySwapListener
from features.macro_pixel.pixel_macro import PixelMacroConfig, save_pixel_macro
from features.macro_pixel.pixel_watcher import PixelWatcherThread
from ui.animated_button import AnimatedButton
from ui.key_capture_widget import KeyCaptureWidget, display_label
from ui.pixel_picker_overlay import PixelPickerOverlay
from ui.scrollbar_style import apply_viewport_scrollbar_gap
from ui.status_colors import STATUS_CRITICAL, STATUS_NEUTRAL, STATUS_OK
from ui.toggle_switch import ToggleSwitch
from ui.trash_icon_button import TrashIconButton

_FIELD_HEIGHT = 32
# Ligne "Nom de la macro" : champ -20% de largeur / +10% de hauteur par
# rapport aux valeurs standard ci-dessus (demande spécifique à cette ligne,
# ne touche pas _FIELD_HEIGHT/240 utilisés ailleurs — mêmes valeurs que
# macro_simple_tab.py, pour garder les deux champs identiques, y compris son
# recul supplémentaire à 178 — voir le commentaire détaillé là-bas).
_NAME_FIELD_WIDTH = 178
_NAME_ROW_HEIGHT = round(_FIELD_HEIGHT * 1.1)
# Largeurs ajustées au contenu attendu (6 caractères hexa, jusqu'à
# "-99999" pour les coordonnées) plutôt qu'un espace vide inutile.
_HEX_FIELD_WIDTH = 68
# -6px (64 -> 58) : nécessaire pour que la carte "Détection" tienne dans la
# largeur RÉELLEMENT disponible (voir _SLOT_RIGHT_MARGIN) — un champ de
# saisie affiche son contenu avec défilement interne s'il ne tient pas
# entièrement (jamais une troncature silencieuse comme un bouton).
_COORD_FIELD_WIDTH = 58
# Largeur fixe des 3 boutons "Définir" (Réaction 1/Réaction 2/Alterner) —
# voir le commentaire dans _build_reaction_keys_row pour le pourquoi.
_KEY_CAPTURE_WIDTH = 100
# Espacement label -> élément associé (x1.2 par rapport aux 6px d'origine).
_LABEL_GAP = 5  # -10% (2e passe, cumulée avec la précédente : 7 -> 6 -> 5)
_HEX_RE = re.compile(r"[^0-9A-Fa-f]")
# Marge droite partagée par TOUS les enfants directs de PixelMacroTab (les
# emplacements eux-mêmes, les traits verts de séparation, la rangée du
# bouton "Ajouter un nouvel emplacement") — posée UNE SEULE FOIS ici (voir
# PixelMacroTab.__init__), jamais dupliquée à l'intérieur de chaque
# PixelMacroSlot comme avant : cette ancienne duplication est justement ce
# qui avait rendu nécessaire un calibrage manuel, en pixels, de la longueur
# du trait vert (_SEPARATOR_WIDTH, retiré) pour qu'il s'arrête "au bon
# endroit" — une valeur qui dérivait à chaque changement de largeur de
# bouton ailleurs dans ce fichier (453 -> 540 déjà constaté une fois), et qui
# s'est révélée fausse une seconde fois : calibrée à la largeur de fenêtre
# RÉELLE mais mesurée sur page de test à 987px, alors que la vraie largeur
# disponible (fenêtre 987px MOINS la sidebar de 165px, voir
# ui/main_window.py/ui/sidebar.py) n'est que d'environ 822px — d'où le
# débordement réel (rectangles/boutons rognés par le viewport, scrollbar
# horizontale désactivée) que ce calibrage en dur ne pouvait plus rattraper.
# Le trait vert est maintenant Expanding (voir _build_green_separator) : il
# occupe TOUJOURS exactement la largeur disponible, quelle qu'elle soit,
# sans plus jamais avoir besoin d'un nombre calibré à la main.
_SLOT_RIGHT_MARGIN = 14

MAX_SLOTS = 3


def _swatch_style(color: tuple[int, int, int] | None) -> str:
    bg = f"rgb({color[0]}, {color[1]}, {color[2]})" if color else "#202027"
    return f"background-color: {bg}; border: 1px solid #33333C; border-radius: 6px;"


def _sanitize_hex(text: str) -> str:
    return _HEX_RE.sub("", text).upper()[:6]


def _show_swap_notification(new_key: str) -> None:
    """Petit toast près du curseur montrant la nouvelle touche de réaction,
    repris de ShowReactionNotification dans l'AHK d'origine (même principe :
    apparaît à côté du curseur, disparaît tout seul après ~250ms)."""
    bubble = QLabel(display_label(new_key).upper())
    bubble.setWindowFlags(
        Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
    )
    bubble.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    bubble.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    bubble.setStyleSheet(
        "background-color: rgba(20, 20, 24, 235); color: #E7E9EE;"
        "font-size: 15px; font-weight: 700; padding: 8px 16px; border-radius: 8px;"
    )
    bubble.adjustSize()
    cursor_pos = QCursor.pos()
    bubble.move(cursor_pos.x() + 12, cursor_pos.y())
    bubble.show()
    QTimer.singleShot(250, bubble.close)


class PixelMacroSlot(QWidget):
    """Un emplacement de macro Pixel indépendant : sa propre config, son
    propre watcher, ses propres boutons Enregistrer/Réinitialiser (et
    Supprimer l'emplacement si `deletable`)."""

    macro_saved = pyqtSignal()
    delete_requested = pyqtSignal(object)  # émet self

    def __init__(self, deletable: bool, parent=None):
        super().__init__(parent)
        self._deletable = deletable
        self._overlay: PixelPickerOverlay | None = None
        self._watcher: PixelWatcherThread | None = None
        self._swap_listener: KeySwapListener | None = None
        self._swap_listener_key: str | None = None
        self._last_saved: PixelMacroConfig | None = None

        QApplication.instance().aboutToQuit.connect(self._stop_watcher)

        layout = QVBoxLayout(self)
        # PAS de marge droite ici : posée UNE SEULE FOIS, partagée par tous
        # les emplacements, au niveau de PixelMacroTab (_SLOT_RIGHT_MARGIN)
        # — voir sa définition en haut du fichier pour l'historique de bug
        # que cette centralisation corrige.
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)  # -10% (2e passe : 10 -> 9 -> 8)

        control_row = self._build_control_row()

        layout.addLayout(self._build_header_row())
        layout.addLayout(self._build_name_row())
        # Même largeur que la carte "Activation" de macro_simple_tab.py :
        # ajoutées directement (pas de marge droite supplémentaire dédiée à
        # ces deux cartes en particulier — un essai précédent en ajoutait
        # une, mais ça les rendait plus étroites que "Activation", une
        # incohérence visuelle entre les deux sous-pages pire que le
        # problème qu'elle réglait).
        layout.addWidget(self._build_detection_card())
        layout.addWidget(self._build_reaction_card())

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
        self.slot_title_label.setStyleSheet("font-size: 14px; font-weight: 700; color: #E7E9EE; padding-bottom: 3px;")
        row.addWidget(self.slot_title_label)

        if self._deletable:
            self.delete_slot_btn = TrashIconButton()
            self.delete_slot_btn.setToolTip(t("page.macro.pixel.delete_slot_btn"))
            self.delete_slot_btn.clicked.connect(lambda: self.delete_requested.emit(self))
            row.addWidget(self.delete_slot_btn)

        row.addStretch(1)

        return row

    def set_slot_number(self, number: int) -> None:
        self.slot_title_label.setText(f"{t('page.macro.pixel.slot_label')} {number}")

    def _build_name_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(t("page.macro.pixel.name_label"))
        self.name_input.setFixedWidth(_NAME_FIELD_WIDTH)
        # Hauteur fixe (_NAME_ROW_HEIGHT) : sans ça, la hauteur naturelle d'un
        # QLineEdit (calculée par Qt à partir du padding/police QSS) ne
        # correspondait pas exactement à celle du même champ dans Macro
        # Simple (macro_simple_tab.py, où setFixedHeight est déjà posé) —
        # les deux "Nom de la macro" doivent avoir la même hauteur.
        self.name_input.setFixedHeight(_NAME_ROW_HEIGHT)
        row.addWidget(self.name_input)
        row.addStretch(1)
        return row

    @staticmethod
    def _labeled_column(label_text: str, widget: QWidget) -> QVBoxLayout:
        """Une mini-colonne : un label court juste au-dessus de son
        widget — le motif répété pour que CHAQUE champ/bouton/toggle ait son
        étiquette au-dessus de lui, jamais à côté (plusieurs colonnes de ce
        type placées côte à côte forment une "même ligne")."""
        column = QVBoxLayout()
        column.setSpacing(_LABEL_GAP)
        label = QLabel(label_text)
        label.setStyleSheet(f"font-size: 12px; color: {STATUS_NEUTRAL};")
        # Sans ces deux lignes, un libellé plus long que son champ (ex:
        # "Réaction 1" au-dessus d'un champ de _KEY_CAPTURE_WIDTH=100px)
        # forçait toute la colonne à s'élargir jusqu'à la largeur du TEXTE
        # plutôt que du champ — cause réelle d'un débordement de carte
        # silencieux (scrollbar horizontale désactivée, voir
        # MacroPage._build_tab_scroll_area) découvert en testant à la
        # largeur RÉELLEMENT disponible (fenêtre 987px moins la sidebar de
        # 165px, voir ui/main_window.py — jamais 987px plein, une erreur de
        # test répétée plusieurs fois dans ce fichier). Un simple retour à
        # la ligne (2 lignes au pire) suffit, sans jamais tronquer
        # l'information contrairement à un texte de bouton élidé.
        label.setWordWrap(True)
        # widget.width() n'est PAS fiable ici : à ce stade (widget tout
        # juste construit, pas encore ajouté à un layout), un widget
        # dimensionné via sizeHint() (ex: AnimatedButton "Sélectionner") n'a
        # pas encore de géométrie réelle et renvoie une largeur par défaut
        # sans rapport (constaté : 640px pour un bouton dont le sizeHint
        # réel est 194px) — seul un widget explicitement figé via
        # setFixedWidth AVANT cet appel a un width() déjà correct. Ce calcul
        # manuel reproduit ce que Qt ferait lui-même une fois posé dans un
        # layout (borné entre min/max, sizeHint() en repli), fiable
        # immédiatement.
        effective_width = min(widget.maximumWidth(), max(widget.minimumWidth(), widget.sizeHint().width()))
        if effective_width > 0:
            label.setFixedWidth(effective_width)
        column.addWidget(label)
        column.addWidget(widget)
        return column

    @staticmethod
    def _build_card(title_text: str) -> tuple[QFrame, QVBoxLayout]:
        """Carte de groupe ("Détection"/"Réaction") : même style que les
        cartes de la page Curseur (QFrame.card, voir theme.qss — fond
        #1F1F25, bordure #2A2A32, rayon 14px) et même agencement interne
        (marges/espacement/titre) que _CursorSection dans
        ui/pages/page_cursor.py, pris comme référence explicite — sauf le
        padding, réduit par rapport à cette référence, ces cartes-ci
        contenant moins de contenu vertical (un titre + une seule ligne de
        champs) qu'une section Curseur : haut/bas -40% (24 -> 14) puis -15%
        supplémentaire (14 -> 12) ; gauche -30% (24 -> 17, mesuré par rendu
        pixel réel) ; droite inchangée (24)."""
        card = QFrame()
        card.setProperty("class", "card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(17, 12, 24, 12)
        layout.setSpacing(9)  # -20% (14 -> 11), puis -15% (11 -> 9) : espace sous le titre de carte

        title = QLabel(title_text)
        title.setStyleSheet("font-size: 15px; font-weight: 700; color: #E7E9EE; padding-bottom: 3px;")
        layout.addWidget(title)

        return card, layout

    def _build_detection_card(self) -> QFrame:
        """Carte "Détection" : aperçu/couleur/Pixel X/Pixel Y (chacun avec
        son label au-dessus, dans l'esprit de l'AHK d'origine) PUIS le
        bouton "Sélectionner un pixel" à DROITE de ces champs, sur la MÊME
        ligne (pas en dessous) — on choisit d'abord de voir les champs déjà
        remplis avant d'en changer la source, l'action pour le faire reste
        juste à côté plutôt que sur sa propre ligne."""
        card, layout = self._build_card(t("page.macro.pixel.detection_card_title"))

        # Même hauteur que les champs voisins (Couleur/Pixel X/Pixel Y),
        # pas un petit carré plaqué en haut d'un conteneur de cette hauteur :
        # plus besoin de conteneur intermédiaire pour centrer/aligner
        # puisque sa taille correspond déjà exactement à la leur.
        self.color_swatch = QFrame()
        self.color_swatch.setFixedSize(_FIELD_HEIGHT, _FIELD_HEIGHT)
        self.color_swatch.setStyleSheet(_swatch_style(None))

        self.hex_input = QLineEdit()
        self.hex_input.setFixedWidth(_HEX_FIELD_WIDTH)
        self.hex_input.setFixedHeight(_FIELD_HEIGHT)
        self.hex_input.textChanged.connect(self._on_hex_changed)

        self.x_input = QLineEdit()
        self.x_input.setValidator(QIntValidator(-99999, 99999, self))
        self.x_input.setFixedWidth(_COORD_FIELD_WIDTH)
        self.x_input.setFixedHeight(_FIELD_HEIGHT)

        self.y_input = QLineEdit()
        self.y_input.setValidator(QIntValidator(-99999, 99999, self))
        self.y_input.setFixedWidth(_COORD_FIELD_WIDTH)
        self.y_input.setFixedHeight(_FIELD_HEIGHT)

        # Après les champs (pas avant, voir docstring) — texte en couleur
        # neutre standard (STATUS_NEUTRAL), pas l'accent turquoise habituel
        # de variant="neutral" (voir ui/animated_button.py : ce nom désigne
        # le CONTOUR gris, le texte reste turquoise par défaut) : ce bouton
        # ne doit plus ressortir visuellement au milieu des champs déjà
        # remplis. Hauteur = _FIELD_HEIGHT (pas la hauteur par défaut
        # d'AnimatedButton, 40px) pour s'aligner exactement sur les champs
        # voisins une fois sur leur même ligne.
        # horizontal_padding réduit (38 par défaut -> 16) : nécessaire pour
        # que la carte "Détection" tienne dans la largeur RÉELLEMENT
        # disponible (voir _SLOT_RIGHT_MARGIN) — jamais le TEXTE lui-même
        # qui recule, seulement la marge autour, même principe déjà appliqué
        # à "Voir les coordonnées" dans macro_simple_tab.py.
        self.pick_btn = AnimatedButton(
            t("page.macro.pixel.pick_btn"), variant="neutral", text_color=STATUS_NEUTRAL,
            height=_FIELD_HEIGHT, horizontal_padding=16,
        )
        self.pick_btn.clicked.connect(self._start_picking)

        columns_row = QHBoxLayout()
        # -6 (8 -> 6) : nécessaire (avec _COORD_FIELD_WIDTH/le padding de
        # pick_btn réduits ci-dessus) pour que la carte "Détection" tienne
        # dans la largeur RÉELLEMENT disponible (voir _SLOT_RIGHT_MARGIN) —
        # au-delà de l'uniformisation avec "Réaction" faite juste avant.
        columns_row.setSpacing(6)
        # Pas de texte de label au-dessus du carré de couleur (juste
        # l'aperçu lui-même) : une chaîne vide plutôt qu'un label absent,
        # pour que sa colonne garde la même hauteur de départ que ses
        # voisines (Couleur/Pixel X/Pixel Y) et reste alignée avec elles.
        columns_row.addLayout(self._labeled_column("", self.color_swatch))
        columns_row.addLayout(self._labeled_column(t("page.macro.pixel.color_label"), self.hex_input))
        columns_row.addLayout(self._labeled_column(t("page.macro.pixel.pixel_x_label"), self.x_input))
        columns_row.addLayout(self._labeled_column(t("page.macro.pixel.pixel_y_label"), self.y_input))
        # Même traitement que le carré de couleur : label vide au-dessus pour
        # garder ce bouton aligné avec les champs (dont le label occupe de la
        # hauteur au-dessus), plutôt qu'un bouton "flottant" plus haut que les
        # autres.
        columns_row.addLayout(self._labeled_column("", self.pick_btn))
        columns_row.addStretch(1)
        layout.addLayout(columns_row)

        return card

    def _build_reaction_card(self) -> QFrame:
        """Carte "Réaction" : touche réaction 1 (déclenchée par le watcher),
        touche réaction 2 (celle avec laquelle le "changement rapide de
        touche" l'échange), la touche de swap elle-même (celle qui déclenche
        l'échange, écoutée globalement — voir key_swap_listener.py) et le
        Cooldown (repris de TP_COOLDOWN_MS dans l'AHK d'origine, voir
        pixel_watcher.py — toujours actif, pas de toggle séparé, un champ à
        0/vide équivaut à aucun délai), tous les quatre sur une même ligne.
        Le swap est toujours actif dès qu'une touche de swap est définie —
        pas de toggle séparé (repris de ChangementToucheHandler dans l'AHK
        d'origine, sans le on/off de g_ChangementToucheEnabled)."""
        card, layout = self._build_card(t("page.macro.pixel.reaction_card_title"))

        # Largeur fixe et IDENTIQUE pour les 3 boutons "Définir" (même
        # principe que _HOTKEY_FIELD_WIDTH dans macro_simple_tab.py) : sans
        # ça, chacun prend sa largeur naturelle (sizeHint), qui dépend du
        # texte affiché (touche capturée ou "Définir") — donnant 3 largeurs
        # différentes selon ce qui est configuré, au lieu d'une ligne
        # régulière. KeyCaptureWidget élide proprement si le texte capturé
        # ne tient pas (voir _refresh_text dans key_capture_widget.py).
        self.key_capture = KeyCaptureWidget()
        self.key_capture.setFixedSize(_KEY_CAPTURE_WIDTH, _FIELD_HEIGHT)

        self.swap_target_capture = KeyCaptureWidget()
        self.swap_target_capture.setFixedSize(_KEY_CAPTURE_WIDTH, _FIELD_HEIGHT)

        # exclude_click_buttons=True : touche de DÉCLENCHEMENT du swap (voir
        # docstring ci-dessus) — clic gauche/droit réservés à l'usage normal
        # de l'interface, voir key_capture_widget.py. Sans effet sur
        # key_capture/swap_target_capture ci-dessus (touches de RÉACTION :
        # le clic simulé PAR la macro, n'importe quel bouton est légitime).
        self.swap_key_capture = KeyCaptureWidget(exclude_click_buttons=True)
        self.swap_key_capture.setFixedSize(_KEY_CAPTURE_WIDTH, _FIELD_HEIGHT)
        self.swap_key_capture.keyChanged.connect(lambda _key: self._sync_swap_listener())

        self.cooldown_seconds_input = QLineEdit()
        self.cooldown_seconds_input.setValidator(QDoubleValidator(0.0, 3600.0, 2, self))
        self.cooldown_seconds_input.setPlaceholderText("0.0")
        self.cooldown_seconds_input.setFixedWidth(_COORD_FIELD_WIDTH + 20)
        self.cooldown_seconds_input.setFixedHeight(_FIELD_HEIGHT)

        row = QHBoxLayout()
        row.setSpacing(6)  # même valeur que columns_row de "Détection" (uniformisées)
        row.addLayout(self._labeled_column(t("page.macro.pixel.reaction1_label"), self.key_capture))
        row.addLayout(self._labeled_column(t("page.macro.pixel.reaction2_label"), self.swap_target_capture))
        row.addLayout(self._labeled_column(t("page.macro.pixel.swap_key_label"), self.swap_key_capture))
        row.addLayout(
            self._labeled_column(t("page.macro.pixel.cooldown_seconds_label"), self.cooldown_seconds_input)
        )
        row.addStretch(1)
        layout.addLayout(row)

        return card

    def _build_control_row(self) -> QHBoxLayout:
        # Sur une seule ligne (toggle+statut, puis Enregistrer/Réinitialiser
        # à droite) : revenu à une seule ligne à la demande, même correctif
        # que macro_simple_tab.py::MacroSimpleSlot._build_control_row (voir
        # son commentaire pour l'historique — l'ancien passage à 2 lignes
        # datait d'un calibrage fait à une largeur de test encore fausse à
        # l'époque). Tient largement dans la largeur RÉELLEMENT disponible
        # (voir _SLOT_RIGHT_MARGIN) sans tronquer aucun texte.
        row = QHBoxLayout()
        row.setSpacing(8)  # -10% (2e passe : 10 -> 9 -> 8)
        self.start_toggle = ToggleSwitch(checked=False)
        self.start_toggle.toggled.connect(self._on_start_toggle)
        row.addWidget(self.start_toggle)

        self.status_label = QLabel(t("page.macro.pixel.status_stopped"))
        self.status_label.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {STATUS_NEUTRAL};")
        row.addWidget(self.status_label)
        row.addStretch(1)

        self.save_btn = AnimatedButton(t("page.macro.pixel.save_btn"), variant="neutral")
        self.save_btn.clicked.connect(self._on_save_clicked)
        row.addWidget(self.save_btn)

        self.reset_btn = AnimatedButton(t("page.macro.pixel.reset_btn"), variant="neutral")
        self.reset_btn.clicked.connect(self._on_reset_clicked)
        row.addWidget(self.reset_btn)

        return row

    # ------------------------------------------------------------------
    # Couleur : champ hexa <-> carré coloré (les deux sens, comme
    # OnEditColorChange dans l'AHK d'origine — nettoyage à la volée des
    # caractères non hexa, majuscules, 6 caractères max).
    # ------------------------------------------------------------------
    def _on_hex_changed(self, text: str) -> None:
        clean = _sanitize_hex(text)
        if clean != text:
            self.hex_input.blockSignals(True)
            self.hex_input.setText(clean)
            self.hex_input.blockSignals(False)
        color = self._current_color()
        self.color_swatch.setStyleSheet(_swatch_style(color))

    def _current_color(self) -> tuple[int, int, int] | None:
        clean = _sanitize_hex(self.hex_input.text())
        if len(clean) != 6:
            return None
        return (int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16))

    # ------------------------------------------------------------------
    # Sélection du pixel : remplit les champs (hexa + X + Y), qui restent
    # librement modifiables à la main ensuite.
    # ------------------------------------------------------------------
    def _start_picking(self) -> None:
        self._overlay = PixelPickerOverlay()
        self._overlay.picked.connect(self._on_pixel_picked)
        self._overlay.cancelled.connect(self._on_pick_cancelled)
        # Masque la fenêtre principale le temps de la sélection : sans ça,
        # elle peut recouvrir/gêner le clic sur le pixel visé à l'écran
        # (notamment si celui-ci se trouve derrière la fenêtre de l'app).
        # self.window() retrouve la fenêtre de haut niveau (MainWindow) peu
        # importe la profondeur d'imbrication de ce widget.
        window = self.window()
        if window is not None:
            window.hide()
        self._overlay.show()

    def _on_pick_cancelled(self) -> None:
        self._restore_main_window_after_picking()

    def _restore_main_window_after_picking(self) -> None:
        window = self.window()
        if window is not None:
            window.show()

    def _on_pixel_picked(self, x: int, y: int, color: tuple) -> None:
        self.x_input.setText(str(x))
        self.y_input.setText(str(y))
        self.hex_input.setText(f"{color[0]:02X}{color[1]:02X}{color[2]:02X}")
        self._restore_main_window_after_picking()

    # ------------------------------------------------------------------
    # Construction / validation de la config
    # ------------------------------------------------------------------
    def is_empty(self) -> bool:
        """Un emplacement est "libre" s'il n'a encore ni nom ni pixel/couleur
        configurés — utilisé pour prioriser les emplacements proposés lors
        d'un import/chargement depuis la Bibliothèque."""
        return not self.name_input.text().strip() and self._current_color() is None

    def _build_macro_config(self, name: str) -> PixelMacroConfig | None:
        color = self._current_color()
        try:
            x = int(self.x_input.text())
            y = int(self.y_input.text())
        except ValueError:
            x = y = None

        if color is None or x is None or not self.key_capture.key():
            self.validation_label.setText(t("page.macro.pixel.error_incomplete_config"))
            self.validation_label.setVisible(True)
            return None

        self.validation_label.setVisible(False)

        try:
            cooldown_seconds = float(self.cooldown_seconds_input.text())
        except ValueError:
            cooldown_seconds = 0.0

        return PixelMacroConfig(
            name=name,
            x=x,
            y=y,
            target_color=color,
            key=self.key_capture.key(),
            swap_key=self.swap_key_capture.key(),
            swap_target_key=self.swap_target_capture.key(),
            cooldown_seconds=cooldown_seconds,
        )

    # ------------------------------------------------------------------
    # Start / Stop
    # ------------------------------------------------------------------
    def _on_start_toggle(self, checked: bool) -> None:
        if not checked:
            self._stop_watcher()
            return

        if not bool(config.get("macros_globally_enabled", True)):
            self.validation_label.setText(t("page.macro.pixel.error_kill_switch"))
            self.validation_label.setVisible(True)
            self.start_toggle.setChecked(False, animate=False)
            return

        macro = self._build_macro_config(self.name_input.text().strip() or t("page.macro.pixel.name_placeholder"))
        if macro is None:
            self.start_toggle.setChecked(False, animate=False)
            return

        self._watcher = PixelWatcherThread(macro, self)
        self._watcher.triggered.connect(self._on_triggered)
        self._watcher.error.connect(self._on_watcher_error)
        self._watcher.finished.connect(self._on_watcher_finished)
        self._watcher.start()
        self._sync_swap_listener()

        self.status_label.setText(t("page.macro.pixel.status_running"))
        self.status_label.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {STATUS_OK};")

    def stop_if_running(self) -> None:
        """Appelé par MacroPage quand le coupe-circuit global est désactivé,
        ou par le conteneur quand cet emplacement est supprimé."""
        self._stop_watcher()

    def _stop_watcher(self) -> None:
        if self._watcher is not None and self._watcher.isRunning():
            self._watcher.stop()
            self._watcher.wait(2000)
        self._watcher = None
        self._set_stopped_ui()
        self._sync_swap_listener()

    def _on_watcher_finished(self) -> None:
        self._watcher = None
        self._set_stopped_ui()

    def _set_stopped_ui(self) -> None:
        self.start_toggle.setChecked(False, animate=False)
        self.status_label.setText(t("page.macro.pixel.status_stopped"))
        self.status_label.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {STATUS_NEUTRAL};")

    def _on_triggered(self) -> None:
        self.status_label.setText(t("page.macro.pixel.status_triggered"))
        self.status_label.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {STATUS_OK};")

    def _on_watcher_error(self, message: str) -> None:
        self.validation_label.setText(t("page.macro.pixel.error_capture").format(error=message))
        self.validation_label.setVisible(True)

    # ------------------------------------------------------------------
    # Changement rapide de touche (ChangementToucheHandler dans l'AHK
    # d'origine) : une touche dédiée, écoutée globalement, échange à la
    # volée la touche de réaction avec une seconde touche cible. Toujours
    # actif dès qu'une touche de swap est définie (pas de toggle séparé).
    # N'a d'effet observable que pendant que cet emplacement tourne (comme
    # g_MacroEnabled gate ChangementToucheHandler côté AHK) : l'écoute
    # démarre/s'arrête avec le watcher plutôt que de tourner en permanence
    # pour rien tant que la macro n'est pas active.
    # ------------------------------------------------------------------
    def _sync_swap_listener(self) -> None:
        swap_key = self.swap_key_capture.key()
        should_run = self._watcher is not None and bool(swap_key)

        # Redémarre l'écoute si la touche de swap a changé pendant qu'elle
        # tournait déjà (sinon elle resterait bloquée sur l'ancienne touche).
        if self._swap_listener is not None and (not should_run or self._swap_listener_key != swap_key):
            self._swap_listener.stop()
            self._swap_listener = None
            self._swap_listener_key = None

        if should_run and self._swap_listener is None:
            self._swap_listener = KeySwapListener(swap_key, self)
            self._swap_listener_key = swap_key
            self._swap_listener.triggered.connect(self._on_swap_triggered)
            self._swap_listener.start()

    def _on_swap_triggered(self) -> None:
        old_reaction = self.key_capture.key()
        old_target = self.swap_target_capture.key()
        if not old_target:
            return

        self.key_capture.set_key(old_target)
        self.swap_target_capture.set_key(old_reaction)

        if self._watcher is not None:
            self._watcher.set_key(self.key_capture.key())

        _show_swap_notification(self.key_capture.key())

    # ------------------------------------------------------------------
    # Sauvegarde / réinitialisation
    # ------------------------------------------------------------------
    def _on_save_clicked(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            self.validation_label.setText(t("page.macro.pixel.error_no_name"))
            self.validation_label.setVisible(True)
            return

        macro = self._build_macro_config(name)
        if macro is None:
            return

        save_pixel_macro(macro)
        self._last_saved = macro
        self.macro_saved.emit()

    def _on_reset_clicked(self) -> None:
        if self._last_saved is not None:
            self.load_macro(self._last_saved)
        else:
            self._reset_to_blank()

    def _reset_to_blank(self) -> None:
        """Aucune sauvegarde existante (nouvel emplacement jamais encore
        enregistré) : "Réinitialiser" vide alors complètement la config
        plutôt que de ne rien faire (il n'y a pas de _last_saved vers lequel
        revenir)."""
        self._stop_watcher()
        self.name_input.clear()
        self.hex_input.clear()  # déclenche _on_hex_changed -> remet le swatch neutre
        self.x_input.clear()
        self.y_input.clear()
        self.key_capture.set_key("")
        self.swap_key_capture.set_key("")
        self.swap_target_capture.set_key("")
        self.cooldown_seconds_input.setText("")
        self.validation_label.setVisible(False)

    # ------------------------------------------------------------------
    # Chargement depuis la Bibliothèque
    # ------------------------------------------------------------------
    def load_macro(self, macro: PixelMacroConfig) -> None:
        self._stop_watcher()
        self._last_saved = macro
        self.name_input.setText(macro.name)
        self._on_pixel_picked(macro.x, macro.y, tuple(macro.target_color))
        self.key_capture.set_key(macro.key)
        self.swap_key_capture.set_key(macro.swap_key)
        self.swap_target_capture.set_key(macro.swap_target_key)
        self.cooldown_seconds_input.setText(str(macro.cooldown_seconds) if macro.cooldown_seconds else "")
        self.validation_label.setVisible(False)


class SlotChooserDialog(QDialog):
    """Popup listant les emplacements existants (libre/occupé) + une option
    "nouvel emplacement" si sous la limite, pour choisir où charger une
    macro cliquée dans la Bibliothèque quand plusieurs emplacements
    existent déjà."""

    def __init__(self, options: list[tuple[str, bool]], can_add_new: bool, parent=None):
        super().__init__(parent)
        self._can_add_new = can_add_new
        self.setWindowTitle(t("page.macro.pixel.slot_chooser_title"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        prompt = QLabel(t("page.macro.pixel.slot_chooser_prompt"))
        prompt.setWordWrap(True)
        prompt.setStyleSheet(f"font-size: 13px; color: {STATUS_NEUTRAL};")
        layout.addWidget(prompt)

        self.list_widget = QListWidget()
        self.list_widget.setMinimumWidth(280)
        # Espace entre le texte et la scrollbar — règle globale, voir
        # CLAUDE.md/ui/scrollbar_style.py.
        apply_viewport_scrollbar_gap(self.list_widget)
        for label, is_free in options:
            suffix = (
                t("page.macro.pixel.slot_free_suffix") if is_free
                else t("page.macro.pixel.slot_occupied_suffix")
            )
            self.list_widget.addItem(QListWidgetItem(f"{label} — {suffix}"))
        if can_add_new:
            self.list_widget.addItem(QListWidgetItem(t("page.macro.pixel.slot_new_option")))

        # Sélectionne par défaut le premier emplacement libre, sinon le premier.
        default_row = next((i for i, (_, is_free) in enumerate(options) if is_free), 0)
        self.list_widget.setCurrentRow(default_row)
        layout.addWidget(self.list_widget)

        # Charger / Annuler : même style pour les deux (pas de distinction
        # primaire/secondaire ici), centrés côte à côte, "Charger" à gauche.
        # Espacement réduit de 20% puis 10% x2 (10px -> 8px -> 7px -> 6px,
        # même valeur que macro_simple_tab.SimpleSlotChooserDialog pour
        # rester cohérent).
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        btn_row.addStretch(1)
        confirm_btn = QPushButton(t("page.macro.pixel.slot_chooser_confirm"))
        confirm_btn.setProperty("class", "secondaryButton")
        confirm_btn.clicked.connect(self.accept)
        btn_row.addWidget(confirm_btn)

        cancel_btn = QPushButton(t("page.macro.pixel.slot_chooser_cancel"))
        cancel_btn.setProperty("class", "secondaryButton")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

    def selected_index(self) -> int:
        """Index de l'emplacement choisi, ou -1 si "nouvel emplacement"."""
        row = self.list_widget.currentRow()
        if self._can_add_new and row == self.list_widget.count() - 1:
            return -1
        return row


def _build_green_separator() -> QFrame:
    # Expanding (pas setFixedSize) : occupe toujours toute la largeur
    # disponible de son layout parent, quelle qu'elle soit — voir
    # _SLOT_RIGHT_MARGIN pour l'historique du bug qu'évite cette approche
    # (un ancien calibrage en pixels qui dérivait/débordait).
    line = QFrame()
    line.setFixedHeight(2)
    line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    line.setStyleSheet(f"background-color: {STATUS_OK}; border: none; border-radius: 1px;")
    return line


class PixelMacroTab(QWidget):
    """Conteneur de 1 à 3 emplacements PixelMacroSlot. "Emplacement 1" existe
    toujours et n'est pas supprimable ; les emplacements ajoutés en plus le
    sont. Chaque emplacement a son propre watcher indépendant."""

    macro_saved = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._slots: list[PixelMacroSlot] = []
        # Séparateur vert précédant CHAQUE emplacement sauf le premier (voir
        # _add_slot/_on_slot_delete_requested) : associé au slot qu'il
        # précède pour pouvoir être retiré avec lui à la suppression.
        self._slot_separators: dict[PixelMacroSlot, QFrame] = {}

        layout = QVBoxLayout(self)
        # Marge droite partagée par tous les enfants de ce layout (voir
        # _SLOT_RIGHT_MARGIN, en tête de fichier, pour l'historique) : posée
        # UNE SEULE FOIS ici plutôt que dans chaque PixelMacroSlot.
        layout.setContentsMargins(0, 0, _SLOT_RIGHT_MARGIN, 0)
        # -20% (18 -> 14), puis encore -20% (14 -> 11) : espace au-dessus/
        # en dessous du trait de séparation vert (voir _build_green_separator)
        # — un seul spacing gouverne les deux écarts entourant ce trait,
        # layout n'ayant que 3 éléments visibles (_slots_layout, séparateur,
        # add_row). Même réduction que macro_simple_tab.py, pour rester
        # cohérent entre tous les sous-onglets Macro.
        layout.setSpacing(11)

        self._slots_layout = QVBoxLayout()
        # -20% (18 -> 14), puis encore -20% (14 -> 11) : même réduction pour
        # les traits verts ENTRE emplacements (voir _add_slot).
        self._slots_layout.setSpacing(11)
        layout.addLayout(self._slots_layout)

        # Expanding (voir _build_green_separator) : remplit toute la largeur
        # disponible de ce layout, pas besoin d'AlignLeft/de largeur figée.
        layout.addWidget(_build_green_separator())

        self.add_slot_btn = AnimatedButton(t("page.macro.pixel.add_slot_btn"), variant="neutral")
        self.add_slot_btn.clicked.connect(self._on_add_slot_clicked)
        add_row = QHBoxLayout()
        add_row.addWidget(self.add_slot_btn)
        add_row.addStretch(1)
        layout.addLayout(add_row)

        layout.addStretch(1)

        self._add_slot(deletable=False)  # Emplacement 1 : toujours présent

    # ------------------------------------------------------------------
    # Gestion des emplacements
    # ------------------------------------------------------------------
    def _add_slot(self, deletable: bool) -> PixelMacroSlot:
        separator = None
        if self._slots:
            # Un séparateur AVANT ce nouvel emplacement (pas seulement un
            # seul, tout en bas, après le dernier) : garde une ligne verte
            # entre CHAQUE emplacement, pas seulement après le dernier.
            separator = _build_green_separator()
            self._slots_layout.addWidget(separator)

        slot = PixelMacroSlot(deletable=deletable)
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

    def _on_slot_delete_requested(self, slot: PixelMacroSlot) -> None:
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

    # ------------------------------------------------------------------
    # Appelé par MacroPage
    # ------------------------------------------------------------------
    def stop_if_running(self) -> None:
        """Appelé par MacroPage quand le coupe-circuit global est désactivé :
        arrête tous les emplacements, pas seulement le premier."""
        for slot in self._slots:
            slot.stop_if_running()

    def request_load(self, macro: PixelMacroConfig) -> None:
        """Charge une macro cliquée dans la Bibliothèque : demande toujours
        confirmation via SlotChooserDialog, même s'il n'y a qu'un seul
        emplacement — sert de garde-fou contre un chargement accidentel qui
        écraserait silencieusement la config en cours dans cet emplacement."""
        options = [
            (f"{t('page.macro.pixel.slot_label')} {i + 1}", slot.is_empty())
            for i, slot in enumerate(self._slots)
        ]
        can_add_new = len(self._slots) < MAX_SLOTS
        dialog = SlotChooserDialog(options, can_add_new, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        index = dialog.selected_index()
        if index == -1:
            new_slot = self._add_slot(deletable=True)
            new_slot.load_macro(macro)
        else:
            self._slots[index].load_macro(macro)
