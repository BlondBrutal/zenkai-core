"""
Page FastFlagsPage : éditeur libre de Fast Flags Roblox (tableau nom/valeur/
type, ajout/suppression de lignes, recherche par nom) + colonne
"Bibliothèque" à droite, reprenant la structure de la Bibliothèque de la
page Macro (voir page_macro.py::_build_library_column) : titre, recherche,
bouton Importer, liste (ou message vide), boutons Ouvrir/Supprimer.
Les 3 presets prédéfinis (Hard/Balanced/Quality) et les presets
personnalisés (importés ou enregistrés depuis l'éditeur) cohabitent dans la
MÊME liste — seuls les presets personnalisés sont supprimables (les 3
prédéfinis sont en lecture seule, jamais de bouton "Supprimer" actif dessus).

Cliquer un élément de la Bibliothèque ne fait que le SÉLECTIONNER
(surbrillance) : il faut cliquer explicitement "Ouvrir" pour charger son
contenu dans l'éditeur (ce système à deux temps remplace une ancienne
confirmation par popup, devenue inutile puisqu'aucun clic accidentel ne peut
plus écraser la config en cours).

Bootstrapper Roblox (voir features/fastflags/launcher.py et protocol.py) :
pas de bouton "Lancer Roblox"/"Fermer Roblox" dans cette page (retirés,
Roblox se lance normalement depuis le site/l'app Roblox) — "Enregistrer"
(_on_save_preset) sauvegarde le tableau comme preset nommé dans la
Bibliothèque ET écrit la configuration "active" (get_fastflags_active_config_path)
que le protocole roblox-player:// intercepté réinjecte dans le vrai
ClientAppSettings.json à CHAQUE vrai lancement de Roblox, même sans que
cette page/l'app soit ouverte — c'est cette action qui rend un preset
"celui qui s'applique désormais", pas un simple lancement.

show_recommendation() reste le point d'accroche utilisé par la page
Performance (bouton "Optimiser pour Roblox" → bottleneck détecté → preset
recommandé, voir main_window.py) : son bouton charge directement le preset
recommandé dans l'éditeur.
"""
import os

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
    QPushButton, QStackedWidget, QStyle, QStyledItemDelegate,
    QStyleOptionViewItem, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.config import config
from core.i18n import t
from core.paths import get_fastflags_active_config_path
from features.fastflags import launcher, protocol
from features.fastflags.manager import (
    PRESETS, delete_custom_preset, detect_active_preset, detect_value_type,
    export_flags_file, get_known_flags, import_flags_file, list_custom_presets,
    load_custom_preset, read_current_flags, reset_to_default, save_custom_preset,
)
from ui.animated_button import AnimatedButton
from ui.pages.base_page import BasePage
from ui.scrollbar_style import apply_viewport_scrollbar_gap, style_scrollbar_directly
from ui.status_colors import STATUS_CRITICAL, STATUS_NEUTRAL, STATUS_OK
from ui.styled_message_box import show_confirm, show_info, show_text_prompt, show_warning
from ui.toggle_switch import ToggleSwitch

_PRESET_NAME_KEYS = {
    "hard": "page.fastflags.preset_hard",
    "balanced": "page.fastflags.preset_balanced",
    "quality": "page.fastflags.preset_quality",
}
# Ordre d'affichage : du plus performant au plus qualitatif.
_PRESET_ORDER = ["hard", "balanced", "quality"]

# Rôles de données personnalisés sur les QListWidgetItem de la Bibliothèque :
# UserRole porte déjà l'identifiant (clé de preset prédéfini OU chemin de
# fichier), _ROLE_KIND distingue les deux familles pour savoir si l'élément
# est supprimable ("custom") ou non ("builtin").
_ROLE_KIND = Qt.ItemDataRole.UserRole + 1

# Même menu contextuel stylé que celui du tableau Macro Simple/de la
# Bibliothèque Macro (voir macro_simple_tab.py::_build_styled_menu et
# page_macro.py::_build_styled_menu) : QMenu est une fenêtre top-level
# détachée (comme le popup natif d'un QComboBox), donc fond+bordure posés
# directement sur l'instance avec WA_TranslucentBackground pour que les
# coins soient vraiment découpés par le compositeur plutôt que de rester
# carrés sous un simple border-radius QSS.
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
    # FramelessWindowHint (retire le cadre natif rectangulaire) +
    # WA_TranslucentBackground (laisse le compositeur alpha-blender les
    # coins découpés par le border-radius) : les deux sont nécessaires
    # ensemble, l'un sans l'autre laisse un résidu carré derrière l'arrondi.
    menu.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    # Ombre portée native (DWM) elle aussi rectangulaire, désactivée pour la
    # même raison.
    menu.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
    menu.setStyleSheet(_CONTEXT_MENU_QSS)
    return menu


COL_NAME, COL_VALUE, COL_TYPE, COL_DELETE = range(4)

_LIBRARY_COLUMN_WIDTH = 260
# Ajustements fins (pas de refonte) : Nom du flag récupère un peu de largeur
# (colonne Stretch, absorbe automatiquement ce que libèrent les colonnes
# fixes ci-dessous), Valeur réduite en conséquence, Type/croix de suppression
# légèrement décalées vers la gauche (obtenu en élargissant très légèrement
# CES deux colonnes : comme ce sont les 2 DERNIÈRES colonnes, s'élargir tire
# leur propre position vers la gauche — leur bord droit reste ancré au bord
# du tableau, seul leur bord gauche avance — d'où la réduction supplémentaire
# de Valeur pour compenser cet élargissement et quand même agrandir Nom net).
_VALUE_COL_WIDTH = 118
_TYPE_COL_WIDTH = 70
_DELETE_COL_WIDTH = 46

# Boutons Enregistrer/Réinitialiser : hauteur et padding horizontal laissés
# au défaut standard d'AnimatedButton (voir ui/animated_button.py — même
# taille que partout ailleurs dans l'app, volontairement, pour rester
# cohérent avec les autres pages), seule la taille de police reste forcée
# ici. AnimatedButton peint son texte en 10pt par défaut (~13.3px à 96 DPI
# seulement — un écart fractionnaire qui grandit sous une mise à l'échelle
# DPI non standard) : _ACTION_BTN_FONT_SIZE force un vrai pixel size de 13,
# identique à la police QSS des boutons du haut de page ("Ajouter un
# flag"/"Parcourir les flags", QPushButton.secondaryButton, "font-size:
# 13px" dans theme.qss).
_ACTION_BTN_FONT_SIZE = 13
# Même écart que celui entre "Ajouter un flag"/"Parcourir les flags" (voir
# top_row.setSpacing(8) dans _build_editor_column) : les boutons du bas
# (Enregistrer/Réinitialiser) restent cohérents avec l'écart déjà utilisé
# en haut de page.
_ACTION_GAP = 8

# Même couleur que le fond général de l'app (QMainWindow, QWidget#centralWidget
# dans theme.qss) : réutilisée ici pour le fond du tableau (point 8) et celui
# du panneau "Parcourir les flags" (point 11), pour qu'aucun des deux ne
# tranche avec le reste de l'interface.
_APP_BACKGROUND = "#1A1A1F"
# Séparateurs internes (lignes de ligne/en-tête) : restent discrets, cohérents
# avec le reste de l'app.
_TABLE_BORDER_COLOR = "#2A2A32"
# Contour EXTÉRIEUR du cadre arrondi : identique à celui de la zone d'édition
# de la page Custom Script (QPlainTextEdit, voir assets/styles/theme.qss —
# "border: 1px solid #33333C; border-radius: 8px;") — même couleur, même
# épaisseur, même rayon, pour que les deux pages se lisent comme un seul
# style de cadre cohérent dans toute l'app. (Ancienne valeur, abandonnée :
# contour plus clair/épais #3D3D48/3px choisi pour la visibilité — le
# nouveau réglage reste net sur une VRAIE capture d'écran Windows, voir
# _RoundedTableCard, le seuil de sécurité de _TABLE_CARD_MARGIN ci-dessous
# reste largement respecté à ce rayon plus petit.)
_TABLE_CARD_BORDER_COLOR = "#33333C"
_TABLE_CARD_BORDER_WIDTH = 1.0
_TABLE_CARD_RADIUS = 8
# Marge intérieure entre le cadre et son contenu (tableau) : SANS elle, le
# QTableWidget (carré, fond plat, SANS son propre rayon d'arrondi) peint son
# en-tête/son fond par-dessus le contour arrondi du cadre. Diagnostic précis :
# le coin carré d'un enfant inset de M pixels sort du tracé arrondi (rayon R)
# dès que M < R*(1 - 1/√2) — avec l'ancienne marge (3px) et un rayon de 14px,
# ce seuil (~4.1px) n'était PAS respecté : le coin carré du fond de l'en-tête
# (légèrement plus clair que le fond du cadre) dépassait donc bien au-delà de
# la courbe peinte, exactement comme décrit (bordure arrondie correcte, fond
# carré qui déborde dessous). 6px (>> 4.1px) garantit géométriquement que
# AUCUN coin d'enfant ne peut plus jamais sortir de la courbe, quel que soit
# ce qui est peint dedans — plus fiable qu'un rayon QSS posé sur l'enfant
# (technique déjà tentée plusieurs fois sans succès sur ce projet).
_TABLE_CARD_MARGIN = 6
# Marge de sécurité entre le trait du bas de l'en-tête et le début de la
# scrollbar : sans elle, la scrollbar démarre pile sur ce pixel de séparation
# et l'efface visuellement sur toute la largeur qu'elle occupe.
_SCROLLBAR_HEADER_GAP = 2

_TABLE_STYLE = f"""
QTableWidget#fastFlagsTable {{
    background-color: {_APP_BACKGROUND};
    border: none;
    gridline-color: transparent;
}}
QTableWidget#fastFlagsTable::item {{
    border-bottom: 1px solid {_TABLE_BORDER_COLOR};
    padding: 4px 8px;
}}
/* Filet de sécurité seulement : le vrai correctif contre le fond plein au
   clic est _PreserveForegroundDelegate (voir plus bas), qui empêche l'item
   d'être peint dans son état "sélectionné" en premier lieu — cette règle
   ne devrait donc jamais matcher en pratique. Gardée par précaution, avec
   une couleur OPAQUE explicite (pas "transparent" : vérifié par
   échantillonnage de pixels réel que Qt ignore un fond transparent pour
   ::item:selected et repeint quand même son remplissage natif de
   sélection par-dessus). */
QTableWidget#fastFlagsTable::item:selected {{
    background-color: {_APP_BACKGROUND};
}}
QTableWidget#fastFlagsTable::item:focus {{
    outline: none;
    border-bottom: 1px solid {_TABLE_BORDER_COLOR};
}}
QTableWidget#fastFlagsTable QHeaderView::section {{
    background-color: #1B1B20;
    color: #9BA1AB;
    font-size: 11px;
    font-weight: 700;
    border: none;
    border-bottom: 1px solid {_TABLE_BORDER_COLOR};
    padding: 6px 8px;
}}
/* Éditeur de cellule (le QLineEdit que Qt crée automatiquement quand on
   clique/tape dans une cellule) : la vraie cause du fond vert plein — la
   règle globale de l'app "QLineEdit {{ selection-background-color:
   #17B897 }}" (voir plus haut dans ce fichier QSS) s'applique aussi à CET
   éditeur, donc dès que du texte y est sélectionné (Qt sélectionne tout par
   défaut à l'entrée en édition), le texte sélectionné se retrouve peint sur
   un bloc plein turquoise — visuellement "toute la cellule devient verte"
   si la valeur remplit une bonne partie de la colonne. "::item:selected"
   (ci-dessus) ne concerne QUE l'item hors édition, jamais cet éditeur.
   selection-background-color: transparent retire ce bloc plein sans
   toucher à la règle globale (qui reste utile ailleurs, ex: barres de
   recherche). */
QTableWidget#fastFlagsTable QLineEdit {{
    background-color: {_APP_BACKGROUND};
    color: {STATUS_OK};
    border: none;
    selection-background-color: {_APP_BACKGROUND};
    selection-color: {STATUS_OK};
    /* padding: sans cette valeur explicite, cet éditeur hérite du padding
       généreux du QLineEdit générique de l'app (8px 10px, voir plus haut
       dans ce fichier QSS) — pensé pour un champ autonome à hauteur libre,
       pas pour tenir dans la hauteur de ligne FIXE de ce tableau (mesurée à
       21px pour l'éditeur une fois ouvert : 8px de padding en haut et en
       bas ne laissait plus que 5px pour le texte lui-même, le tronquant
       verticalement à moitié — vérifié par rendu réel). 2px vertical laisse
       une marge confortable au texte sur cette hauteur ; 8px horizontal
       inchangé (aligné sur le padding de QTableWidget#fastFlagsTable::item
       ci-dessus). */
    padding: 2px 8px;
}}
"""


class _RoundedTableCard(QFrame):
    """Cadre à coins arrondis, peint entièrement à la main (QPainter), SANS
    masque (setMask).

    Historique — pourquoi pas de masque : plusieurs techniques de découpe ont
    été essayées (QRegion à partir d'un polygone par défaut, polygone
    sur-échantillonné 8x pour une courbe plus fine, QRegion(QPainterPath)
    direct) et TOUTES laissaient un vrai trou à la pointe de chaque coin sur
    une capture d'écran Windows RÉELLE (le rasterizer logiciel hors-écran
    utilisé pour le développement ne révélait pas le problème — d'où
    plusieurs correctifs déclarés "vérifiés" à tort). Pire, QRegion(QPainterPath)
    plante silencieusement ce build de PyQt6 (crash natif sans trace Python).
    Vérifié ensuite, sur une capture d'écran réelle, que retirer complètement
    le masque et ne garder QUE le remplissage + contour peints (ci-dessous)
    donne une courbe parfaitement propre sur les 4 coins. Le fond du tableau
    interne (voir _APP_BACKGROUND) est volontairement identique au fond peint
    ici : le corps carré du QTableWidget peut donc dépasser légèrement sous la
    courbe sans que ça se voie (même couleur), et l'en-tête (légèrement plus
    clair) reste inset via _TABLE_CARD_MARGIN, loin de la zone de courbure.
    """

    def __init__(
        self, radius: int, background: str, contour_color: str, header_rule_color: str,
        contour_width: float = 1.0, parent=None,
    ):
        super().__init__(parent)
        self._radius = radius
        self._background = QColor(background)
        self._contour_color = QColor(contour_color)
        self._contour_width = contour_width
        # Trait de séparation d'en-tête peint manuellement (voir
        # set_header_bottom_y) : le QHeaderView interne ne s'étend PAS
        # jusqu'au bord droit réel (il s'arrête à la largeur du viewport,
        # avant la gouttière réservée à la scrollbar verticale) — son propre
        # border-bottom QSS s'arrête donc net à cet endroit. Un trait peint
        # ici, sur toute la largeur INTÉRIEURE du cadre, reste continu même
        # sous la scrollbar (point 3 de la demande). Couleur discrète
        # (cohérente avec les séparateurs internes), distincte du contour
        # extérieur (plus clair pour rester visible, voir _contour_color).
        self._header_rule = QWidget(self)
        self._header_rule.setStyleSheet(f"background-color: {header_rule_color};")
        self._header_rule.setFixedHeight(1)
        self._header_rule.hide()
        self._header_bottom_y: int | None = None

    def set_header_bottom_y(self, y: int) -> None:
        self._header_bottom_y = y
        self._reposition_header_rule()
        self._header_rule.show()
        self._header_rule.raise_()

    def _reposition_header_rule(self) -> None:
        if self._header_bottom_y is not None:
            self._header_rule.setGeometry(
                _TABLE_CARD_MARGIN, self._header_bottom_y,
                max(0, self.width() - 2 * _TABLE_CARD_MARGIN), 1,
            )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reposition_header_rule()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setBrush(self._background)
        painter.setPen(QPen(self._contour_color, self._contour_width))
        painter.drawRoundedRect(rect, self._radius, self._radius)


class _PreserveForegroundDelegate(QStyledItemDelegate):
    """Rend une cellule sélectionnée EXACTEMENT comme à l'état normal.

    Plusieurs essais plus ciblés ont échoué avant celui-ci (vérifiés par
    échantillonnage de pixels réel) : (1) "::item:selected { background-color:
    transparent }" — Qt ignore ce cas précis et repeint quand même son
    remplissage natif de sélection ; (2) fournir la couleur du texte via
    "color: palette(text)" dans _TABLE_STYLE, en posant QPalette.Text sur
    l'option de style dans initStyleOption() — sans effet, la fonction QSS
    palette() se résout contre la palette STATIQUE du widget, pas contre la
    copie d'option modifiée pour ce paint précis. Solution retenue, garantie
    par construction : retirer State_Selected de l'option AVANT de déléguer
    à Qt, pour qu'il peigne la cellule sans savoir qu'elle est sélectionnée
    — fond, couleur de texte, tout redevient identique à l'état normal. La
    sélection reste réelle au niveau du modèle (currentItem(), navigation,
    déclenchement de l'édition...), seul le RENDU l'ignore."""

    def paint(self, painter, option, index) -> None:
        option = QStyleOptionViewItem(option)
        option.state &= ~QStyle.StateFlag.State_Selected
        super().paint(painter, option, index)

    def createEditor(self, parent, option, index):
        editor = _GreenCursorLineEdit(parent)
        # Sans ça, l'éditeur reste aligné à gauche (défaut de QLineEdit) même
        # pour une colonne dont l'item est centré (ex: Valeur, voir
        # _append_row) — le texte "sautait" visuellement du centre de la
        # cellule vers la gauche au moment d'entrer en édition, donné
        # vérifié comme la vraie cause du "changement d'apparence" signalé
        # (la couleur, elle, était déjà correcte). On reprend l'alignement
        # RÉEL de l'item plutôt que de le figer en dur pour cette colonne :
        # ça reste correct si l'alignement change un jour.
        alignment = index.data(Qt.ItemDataRole.TextAlignmentRole)
        if alignment is not None:
            editor.setAlignment(Qt.AlignmentFlag(alignment))
        return editor


class _GreenCursorLineEdit(QLineEdit):
    """L'éditeur de cellule (voir _PreserveForegroundDelegate.createEditor),
    avec un curseur de texte peint à la main en vert turquoise.

    Le curseur clignotant natif de QLineEdit ignore aussi bien la couleur
    QSS "color" que QPalette.ColorRole.Text posé à N'IMPORTE QUEL moment
    (création de l'éditeur, juste avant affichage, ou même réappliqué à
    chaque paintEvent juste avant de peindre) — vérifié par échantillonnage
    de pixels réel à chaque essai : le curseur restait rendu en #E7E9EE
    (la couleur de texte générique de theme.qss, "QLineEdit { color:
    #E7E9EE }"), jamais affecté. Cette classe abandonne toute tentative de
    faire changer le curseur NATIF de couleur : elle efface d'abord le
    rectangle où Qt vient de le peindre (avec la couleur de fond normale de
    la cellule), puis peint par-dessus un second curseur, turquoise, à la
    même position (self.cursorRect()) — sans tenter de resynchroniser avec
    le clignotement natif (peu fiable), ce second curseur reste affiché en
    continu tant que l'éditeur a le focus."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.hasFocus() and not self.isReadOnly():
            painter = QPainter(self)
            rect = self.cursorRect()
            # cursorRect() est systématiquement EN RETARD d'un caractère sur
            # la vraie position du curseur clignotant — avec ou sans
            # sélection active (vérifié par comparaison directe avec
            # QFontMetrics.horizontalAdvance() sur deux scénarios réels :
            # sélection totale à l'entrée en édition, ET position après
            # frappe de texte sans sélection ; dans les deux cas
            # cursorRect().left() correspondait exactement à la position
            # PRÉCÉDENTE, jamais à cursorPosition()). On compense en ajoutant
            # la largeur du caractère qui précède immédiatement le curseur.
            pos = self.cursorPosition()
            text = self.text()
            x = rect.left()
            if pos > 0:
                x += self.fontMetrics().horizontalAdvance(text[pos - 1:pos])
            # cursorRect() est aussi plus large (~10px) que le trait
            # réellement dessiné par Qt (1-2px) : n'effacer/redessiner
            # qu'une fine bande à cette position, jamais toute sa largeur —
            # sinon ça efface aussi le caractère adjacent (ex: "1" collé au
            # curseur), vérifié par capture d'écran réelle. Bande légèrement
            # plus large que le trait qu'on dessine (±2px, pas ±1px) : un
            # résidu d'un pixel du curseur natif subsistait sinon en bordure
            # (écart d'arrondi entre QFontMetrics.horizontalAdvance() et le
            # positionnement interne réel de Qt, vérifié par échantillonnage
            # de pixels réel).
            strip = rect.adjusted(0, 0, 0, 0)
            strip.moveLeft(x - 2)
            strip.setWidth(5)
            painter.fillRect(strip, QColor(_APP_BACKGROUND))
            painter.setPen(QColor(STATUS_OK))
            painter.drawLine(x, rect.top() + 1, x, rect.bottom() - 1)


def _build_type_badge() -> QLabel:
    badge = QLabel("STRING")
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    badge.setStyleSheet(
        f"font-size: 10px; font-weight: 700; color: {STATUS_NEUTRAL};"
        " background-color: #26262E; border: 1px solid #33333C;"
        " border-radius: 6px; padding: 2px 6px;"
    )
    return badge


def _build_delete_cross() -> QPushButton:
    """Petite croix rouge cliquable pour supprimer une ligne — remplace
    l'ancienne icône poubelle peinte à la main (TrashIconButton), jugée moins
    "pro" que cette croix compacte, plus proche d'un vrai outil de config."""
    btn = QPushButton("×")
    btn.setFixedSize(20, 20)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(
        f"QPushButton {{ background: transparent; border: none; color: {STATUS_CRITICAL};"
        " font-size: 15px; font-weight: 700; padding: 0px; }}"
        " QPushButton:hover { color: #FF8078; }"
    )
    return btn


def _centered_cell(widget: QWidget, margin_right: int = 0) -> QWidget:
    """Centre un petit widget (badge de type, croix de suppression) dans sa
    cellule de tableau : setCellWidget seul l'étire à toute la cellule sans
    le centrer. `margin_right` : espace supplémentaire à droite — utilisé
    pour la croix de suppression, trop collée à la scrollbar sinon."""
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, margin_right, 0)
    layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignCenter)
    return container


class _KnownFlagsDialog(QDialog):
    """Popup "Parcourir les flags connus" : liste filtrable des flags déjà
    rencontrés dans un vrai fichier (presets fournis + imports précédents de
    l'utilisateur, voir features/fastflags/manager.py:get_known_flags —
    jamais de nom inventé). Fermée par défaut, ouverte uniquement à la
    demande (voir FastFlagsPage._on_browse_known_clicked)."""

    flag_chosen = pyqtSignal(str, str)  # (nom du flag, type détecté)

    def __init__(self, known_flags: dict[str, str], parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("page.fastflags.browse_known_title"))
        self.resize(380, 440)
        # Fond aligné sur le reste de l'app : un QDialog nu utilise la
        # palette Qt par défaut, pas le style QMainWindow/#centralWidget de
        # theme.qss, d'où ce rappel explicite ici.
        self.setStyleSheet(f"background-color: {_APP_BACKGROUND};")
        self._known_flags = dict(sorted(known_flags.items()))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(t("page.fastflags.browse_known_search_placeholder"))
        self.search_input.textChanged.connect(lambda _text: self._populate())
        layout.addWidget(self.search_input)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        # Espace entre le texte et la scrollbar — règle globale, voir
        # CLAUDE.md/ui/scrollbar_style.py.
        apply_viewport_scrollbar_gap(self.list_widget)
        layout.addWidget(self.list_widget, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        add_btn = QPushButton(t("page.fastflags.browse_known_add_btn"))
        add_btn.setProperty("class", "secondaryButton")
        add_btn.clicked.connect(self._on_add_clicked)
        button_row.addWidget(add_btn)
        close_btn = QPushButton(t("page.fastflags.browse_known_close_btn"))
        close_btn.setProperty("class", "secondaryButton")
        close_btn.clicked.connect(self.close)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

        self._populate()

    def _populate(self) -> None:
        self.list_widget.clear()
        query = self.search_input.text().strip().lower()
        for name, flag_type in self._known_flags.items():
            if query and query not in name.lower():
                continue
            item = QListWidgetItem(f"{name}   [{flag_type}]")
            item.setData(Qt.ItemDataRole.UserRole, (name, flag_type))
            self.list_widget.addItem(item)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        name, flag_type = item.data(Qt.ItemDataRole.UserRole)
        self.flag_chosen.emit(name, flag_type)

    def _on_add_clicked(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            return
        name, flag_type = item.data(Qt.ItemDataRole.UserRole)
        self.flag_chosen.emit(name, flag_type)


class FastFlagsPage(BasePage):
    def __init__(self, parent=None):
        super().__init__(t("page.fastflags.title"), "", parent)
        self.add_info_badge(t("page.fastflags.placeholder"))
        self.add_beta_badge(t("app.beta_warning"))

        # Kill switch global, même emplacement/principe que "Macros actives"
        # sur la page Macro (voir MacroPage._build_kill_switch_control) : au
        # même niveau que le titre, aligné à droite.
        self.header_layout().addWidget(self._build_kill_switch_control())

        # Marge droite réduite (32 -> 16), comme la page Macro (référence) :
        # cohérence de largeur de contenu entre toutes les pages (voir aussi
        # page_performance.py/page_cursor.py/page_license.py). L'espace
        # récupéré profite directement au tableau d'édition (colonne
        # étirable, voir _build_editor_column), pas seulement à un vide
        # déplacé ailleurs.
        margins = self.content_layout().contentsMargins()
        self.content_layout().setContentsMargins(margins.left(), margins.top(), 16, margins.bottom())

        # --- Carte de recommandation (alimentée par la page Performance) ---
        self.recommendation_card = QFrame()
        self.recommendation_card.setProperty("class", "card")
        self.recommendation_card.setVisible(False)
        rec_layout = QVBoxLayout(self.recommendation_card)
        rec_layout.setContentsMargins(16, 14, 16, 14)
        rec_layout.setSpacing(6)

        rec_title = QLabel(t("page.fastflags.recommendation_title"))
        rec_title.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {STATUS_OK};")
        rec_layout.addWidget(rec_title)

        self.recommendation_label = QLabel("")
        self.recommendation_label.setWordWrap(True)
        self.recommendation_label.setStyleSheet(f"font-size: 12px; color: {STATUS_NEUTRAL};")
        rec_layout.addWidget(self.recommendation_label)

        # Preset recommandé en attente de chargement (None tant qu'aucune
        # recommandation n'a encore été reçue depuis la page Performance).
        self._recommended_preset_key: str | None = None
        self.recommendation_load_btn = AnimatedButton(t("page.fastflags.load_btn"), variant="neutral")
        self.recommendation_load_btn.clicked.connect(self._on_load_recommended)
        rec_layout.addWidget(self.recommendation_load_btn)

        self.content_layout().addWidget(self.recommendation_card)

        main_row = QHBoxLayout()
        main_row.setSpacing(16)
        main_row.addWidget(self._build_editor_column(), 1)
        main_row.addWidget(self._build_library_column())
        self.content_layout().addLayout(main_row, 1)

        self._populate_table(self._load_initial_flags())
        self._refresh_library()
        self._refresh_status()
        self._verify_protocol_registration()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Le fichier peut avoir changé en dehors de l'app (édition manuelle,
        # autre outil) depuis le dernier affichage : on relit l'état réel à
        # chaque fois. On NE recharge PAS le contenu de l'éditeur ici (pour
        # ne jamais écraser une édition en cours simplement parce que
        # l'utilisateur a changé d'onglet puis est revenu).
        self._refresh_status()
        # Vérifie que l'association roblox-player:// est toujours valide à
        # chaque ouverture de la page — Roblox pourrait l'avoir écrasée (peu
        # probable, voir protocol.py, mais jamais supposé impossible), ou
        # l'utilisateur/un nettoyeur de registre pourrait l'avoir retirée.
        self._verify_protocol_registration()
        # Recalculé à chaque affichage réel (pas seulement à la construction,
        # voir _build_editor_column) : la hauteur RÉELLE de l'en-tête
        # (.height(), pas .sizeHint()) n'est fiable qu'une fois le widget
        # effectivement affiché/mis en page — un léger écart entre les deux
        # est ce qui laissait la scrollbar empiéter un peu sur l'en-tête.
        self._fix_header_and_scrollbar()

    def _fix_header_and_scrollbar(self) -> None:
        header_height = self.table.horizontalHeader().height()
        # Trait de séparation peint sur toute la largeur intérieure du cadre
        # (voir _RoundedTableCard.set_header_bottom_y) : reste continu même
        # sous la scrollbar, là où le QHeaderView natif s'arrête net.
        self._table_frame.set_header_bottom_y(_TABLE_CARD_MARGIN + header_height - 1)
        # +_SCROLLBAR_HEADER_GAP : sans cette petite marge de sécurité, la
        # scrollbar démarre pile sur ce trait et l'efface sur toute sa largeur.
        style_scrollbar_directly(
            self.table.verticalScrollBar(),
            margin=f"{header_height + _SCROLLBAR_HEADER_GAP}px 0px 0px 0px",
        )

    # ------------------------------------------------------------------
    # Interrupteur global "Fast Flags actifs" : un seul contrôle pour deux
    # effets (fusionnés pour libérer de la place, voir demande utilisateur —
    # avant, deux barres séparées) : activer applique les flags du tableau
    # ET enregistre l'interception du protocole roblox-player:// (voir
    # features/fastflags/protocol.py) ; désactiver vide le vrai fichier
    # Roblox ET désinscrit l'interception (retour au lancement natif de
    # Roblox). Même concept que "Macros actives" sur la page Macro pour la
    # partie flags — persisté (voir core/config.py,
    # "fastflags_globally_enabled" / "auto_apply_fastflags_on_launch").
    # ------------------------------------------------------------------
    def _build_kill_switch_control(self) -> QWidget:
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        label = QLabel(t("page.fastflags.kill_switch_label"))
        label.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {STATUS_NEUTRAL};")
        row.addWidget(label)

        # Coché seulement si les DEUX étaient déjà actifs : un utilisateur
        # qui avait seulement les flags actifs (avant la fusion des deux
        # interrupteurs, quand l'interception était un réglage séparé
        # désactivé par défaut) ne doit jamais se retrouver avec
        # l'interception activée silencieusement du jour au lendemain.
        initial_enabled = (
            bool(config.get("fastflags_globally_enabled", True))
            and bool(config.get("auto_apply_fastflags_on_launch", False))
        )
        self.kill_switch = ToggleSwitch(checked=initial_enabled)
        self.kill_switch.toggled.connect(self._on_kill_switch_toggled)
        row.addWidget(self.kill_switch)

        return wrapper

    def _on_kill_switch_toggled(self, checked: bool) -> None:
        # Effet immédiat sur l'interception : si l'écriture/suppression
        # registre échoue, on revient à l'état précédent plutôt que de
        # laisser l'interrupteur mentir sur l'état réel (registre vs config
        # désynchronisés) — jamais d'échec silencieux (voir protocol.py).
        if checked:
            # Avertissement AVANT d'écrire dans le registre (catégorie
            # sensible PROTOCOL_HANDLER, voir core/security_log.py) : ce
            # toggle est un changement de configuration ponctuel et
            # explicite, pas le chemin de lancement du jeu lui-même (celui-ci
            # — protocole roblox-player:// — reste volontairement sans
            # friction, voir la docstring de features/fastflags/launcher.py).
            # Annuler
            # revient au switch décoché SANS ré-émettre "toggled" (voir
            # ToggleSwitch.setChecked), donc sans boucle.
            if not show_confirm(
                self, t("dialog.security_warning_title"),
                t("page.fastflags.kill_switch_confirm_text"),
                confirm_label=t("page.fastflags.kill_switch_confirm_btn"),
            ):
                self.kill_switch.setChecked(False, animate=False)
                return
            if not protocol.register():
                show_warning(self, t("page.fastflags.title"), t("page.fastflags.protocol_register_error"))
                self.kill_switch.setChecked(False, animate=False)
                return
            config.set("auto_apply_fastflags_on_launch", True)
        else:
            if not protocol.unregister():
                show_warning(self, t("page.fastflags.title"), t("page.fastflags.protocol_unregister_error"))
                self.kill_switch.setChecked(True, animate=False)
                return
            config.set("auto_apply_fastflags_on_launch", False)
            # Même principe qu'avant la fusion (stoppe l'existant tout de
            # suite) : vide le vrai fichier Roblox, sans toucher au contenu
            # de l'éditeur (l'utilisateur peut réactiver puis rappliquer la
            # même configuration ensuite).
            reset_to_default()
        config.set("fastflags_globally_enabled", checked)
        self._refresh_status()

    def _verify_protocol_registration(self) -> None:
        # Filet de sécurité silencieux (pas de barre de statut dédiée,
        # retirée pour libérer de la place) : si l'interception est censée
        # être active mais que le registre a dérivé (Roblox, l'utilisateur,
        # ou un nettoyeur de registre a pu le modifier), tente une
        # réparation silencieuse — et seulement si CETTE tentative échoue,
        # prévient clairement l'utilisateur (jamais un échec totalement
        # silencieux, voir protocol.py).
        if not self.kill_switch.isChecked():
            return
        if protocol.health_check() != "ok" and not protocol.register():
            show_warning(self, t("page.fastflags.title"), t("page.fastflags.protocol_register_error"))

    # ------------------------------------------------------------------
    # Zone d'édition (tableau nom/valeur/type + recherche + actions)
    # ------------------------------------------------------------------
    def _build_editor_column(self) -> QWidget:
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(t("page.fastflags.search_placeholder"))
        self.search_input.textChanged.connect(self._apply_filter)
        top_row.addWidget(self.search_input, 1)

        self.add_row_btn = QPushButton(t("page.fastflags.add_row_btn"))
        self.add_row_btn.setProperty("class", "secondaryButton")
        self.add_row_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_row_btn.clicked.connect(self._on_add_row)
        top_row.addWidget(self.add_row_btn)

        self.browse_known_btn = QPushButton(t("page.fastflags.browse_known_btn"))
        self.browse_known_btn.setProperty("class", "secondaryButton")
        self.browse_known_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browse_known_btn.clicked.connect(self._on_browse_known_clicked)
        top_row.addWidget(self.browse_known_btn)
        layout.addLayout(top_row)

        # _TABLE_CARD_MARGIN (3px, pas 0) : laisse le contour peint à la main
        # par _RoundedTableCard (voir sa docstring) réellement visible tout
        # autour, sans recréer un vide notable comme les 14px de l'ancienne
        # tentative (marge-cache-le-coin-carré).
        table_frame = _RoundedTableCard(
            _TABLE_CARD_RADIUS, _APP_BACKGROUND, _TABLE_CARD_BORDER_COLOR, _TABLE_BORDER_COLOR,
            contour_width=_TABLE_CARD_BORDER_WIDTH,
        )
        self._table_frame = table_frame
        table_frame.setStyleSheet(_TABLE_STYLE)
        table_frame_layout = QVBoxLayout(table_frame)
        table_frame_layout.setContentsMargins(
            _TABLE_CARD_MARGIN, _TABLE_CARD_MARGIN, _TABLE_CARD_MARGIN, _TABLE_CARD_MARGIN
        )

        self.table = QTableWidget(0, 4)
        self.table.setObjectName("fastFlagsTable")
        # Voir _PreserveForegroundDelegate : empêche la sélection de faire
        # virer le texte au gris clair générique (theme.qss), notamment la
        # colonne Valeur (normalement verte).
        self.table.setItemDelegate(_PreserveForegroundDelegate(self.table))
        # CurrentChanged (en plus des déclencheurs par défaut) : un simple
        # clic change la cellule "courante", donc ouvre déjà l'éditeur — sans
        # ça, Qt exige un double-clic (ou F2/taper directement) pour entrer
        # en édition.
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.CurrentChanged
            | QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.table.setHorizontalHeaderLabels([
            t("page.fastflags.col_name"), t("page.fastflags.col_value"),
            t("page.fastflags.col_type"), "",
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        # Nom = Stretch (prend tout l'espace restant), Valeur = largeur fixe
        # réduite (les valeurs de flags sont presque toujours courtes :
        # "True"/"False"/un nombre), Type/Suppression = petites largeurs
        # fixes — voir point 5 de la demande : la colonne Nom récupère
        # l'espace que Valeur gaspillait auparavant en Stretch.
        self.table.horizontalHeader().setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(COL_VALUE, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(COL_TYPE, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(COL_DELETE, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(COL_VALUE, _VALUE_COL_WIDTH)
        self.table.setColumnWidth(COL_TYPE, _TYPE_COL_WIDTH)
        self.table.setColumnWidth(COL_DELETE, _DELETE_COL_WIDTH)
        # Espace entre la dernière colonne (Supprimer) et la scrollbar —
        # règle globale, voir CLAUDE.md/ui/scrollbar_style.py.
        apply_viewport_scrollbar_gap(self.table)
        self.table.itemChanged.connect(self._on_item_changed)
        table_frame_layout.addWidget(self.table)
        layout.addWidget(table_frame, 1)

        # La scrollbar verticale ne doit débuter qu'en dessous de la ligne
        # d'en-tête (Nom/Valeur/Type), jamais au niveau de l'en-tête
        # lui-même, et le trait de séparation de l'en-tête doit rester
        # continu même sous la scrollbar (voir _RoundedTableCard). Meilleur
        # effort ici (avant le premier affichage réel) ; recalculé avec la
        # hauteur RÉELLE (pas sizeHint) à chaque showEvent, voir
        # _fix_header_and_scrollbar.
        self._fix_header_and_scrollbar()

        # "Enregistrer" — remplace l'ancien "Appliquer" : sauvegarde un
        # preset nommé dans la Bibliothèque ET écrit la configuration
        # active que le protocole roblox-player:// réappliquera au prochain
        # vrai lancement de Roblox (voir _on_save_preset) — plus de bouton
        # "Lancer Roblox"/"Fermer Roblox" dans cette page (retirés). Les 2
        # boutons restants sont groupés ensemble en bas à droite (stretch en
        # tête, pas entre eux), écart IDENTIQUE à celui du haut de page entre
        # "Ajouter un flag"/"Parcourir les flags" (_ACTION_GAP, via setSpacing).
        action_row = QHBoxLayout()
        action_row.setSpacing(_ACTION_GAP)
        action_row.addStretch(1)
        self.save_preset_btn = AnimatedButton(
            t("page.fastflags.save_preset_btn"), variant="neutral", font_pixel_size=_ACTION_BTN_FONT_SIZE,
        )
        self.save_preset_btn.clicked.connect(self._on_save_preset)
        action_row.addWidget(self.save_preset_btn)
        self.reset_btn = AnimatedButton(
            t("page.fastflags.reset_btn"), variant="neutral", font_pixel_size=_ACTION_BTN_FONT_SIZE,
        )
        self.reset_btn.clicked.connect(self._on_reset)
        action_row.addWidget(self.reset_btn)
        layout.addLayout(action_row)

        return container

    def _load_initial_flags(self) -> dict:
        # Priorité à la configuration "active" du bootstrapper (voir
        # features/fastflags/launcher.py) une fois qu'elle existe : elle
        # reflète l'intention réelle de l'utilisateur, plus fiable que le
        # vrai fichier Roblox (volatil, Roblox peut le modifier entre deux
        # lancements). Tant qu'elle n'existe pas encore (l'utilisateur n'a
        # jamais cliqué "Enregistrer"), comportement historique inchangé :
        # afficher ce qui est RÉELLEMENT dans le fichier Roblox.
        active_path = get_fastflags_active_config_path()
        if os.path.isfile(active_path):
            return load_custom_preset(active_path)
        return read_current_flags()

    def _populate_table(self, flags: dict) -> None:
        # Bloque itemChanged pendant le remplissage programmatique : sinon
        # chaque setItem() déclenche _on_item_changed inutilement (et,
        # pendant la construction ligne par ligne, sur des lignes encore
        # incomplètes).
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for name, value in flags.items():
            self._append_row(name, value)
        self.table.blockSignals(False)
        self._apply_filter()

    def _append_row(self, name: str = "", value: str = "") -> int:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, COL_NAME, QTableWidgetItem(str(name)))

        value_item = QTableWidgetItem(str(value))
        # Texte de la colonne Valeur en turquoise (cohérent avec le thème) :
        # couleur posée sur l'item lui-même (persiste tant que l'utilisateur
        # édite le texte, pas besoin de la reposer). Centrée dans la cellule.
        value_item.setForeground(QColor(STATUS_OK))
        value_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, COL_VALUE, value_item)

        badge = _build_type_badge()
        badge.setText(detect_value_type(str(value)))
        self.table.setCellWidget(row, COL_TYPE, _centered_cell(badge))

        delete_btn = _build_delete_cross()
        delete_btn.clicked.connect(lambda: self._on_delete_row(delete_btn))
        # margin_right=8 : un peu d'air avec la scrollbar verticale, sinon la
        # croix colle directement dessus.
        self.table.setCellWidget(row, COL_DELETE, _centered_cell(delete_btn, margin_right=8))
        return row

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != COL_VALUE:
            return
        badge_container = self.table.cellWidget(item.row(), COL_TYPE)
        if badge_container is not None:
            badge_container.layout().itemAt(0).widget().setText(detect_value_type(item.text()))

    def _on_delete_row(self, delete_btn: QPushButton) -> None:
        # Recherche par identité du widget (pas un index capturé à la
        # création) : les index de ligne changent à chaque suppression, un
        # index figé dans la lambda de connexion pointerait vite sur la
        # mauvaise ligne après une première suppression.
        for row in range(self.table.rowCount()):
            container = self.table.cellWidget(row, COL_DELETE)
            if container is not None and container.layout().itemAt(0).widget() is delete_btn:
                self.table.removeRow(row)
                return

    def _on_add_row(self) -> None:
        row = self._append_row()
        self.table.scrollToBottom()
        self.table.setCurrentCell(row, COL_NAME)
        self.table.editItem(self.table.item(row, COL_NAME))

    def _on_browse_known_clicked(self) -> None:
        dialog = _KnownFlagsDialog(get_known_flags(), self)
        dialog.flag_chosen.connect(self._on_known_flag_chosen)
        dialog.exec()

    def _on_known_flag_chosen(self, name: str, flag_type: str) -> None:
        # Evite les doublons : si le flag est déjà dans le tableau, place le
        # focus dessus plutôt que d'ajouter une ligne en double.
        for row in range(self.table.rowCount()):
            existing = self.table.item(row, COL_NAME)
            if existing is not None and existing.text() == name:
                self.table.setCurrentCell(row, COL_VALUE)
                return
        default_value = {"BOOL": "True", "INT": "0"}.get(flag_type, "")
        row = self._append_row(name, default_value)
        self.table.scrollToItem(self.table.item(row, COL_NAME))

    def _apply_filter(self) -> None:
        query = self.search_input.text().strip().lower()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, COL_NAME)
            name = item.text().lower() if item is not None else ""
            self.table.setRowHidden(row, bool(query) and query not in name)

    def _collect_flags_from_table(self) -> dict:
        # Inclut TOUTES les lignes, y compris celles masquées par le filtre
        # de recherche (le filtre n'est qu'un affichage, jamais une
        # troncature des données réelles).
        flags: dict[str, str] = {}
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, COL_NAME)
            value_item = self.table.item(row, COL_VALUE)
            name = name_item.text().strip() if name_item is not None else ""
            if not name:
                continue
            flags[name] = value_item.text() if value_item is not None else ""
        return flags

    # ------------------------------------------------------------------
    # Colonne Bibliothèque — même principe visuel que la page Macro (voir
    # page_macro.py::_build_library_column) : titre, recherche, bouton
    # Importer, liste (ou message vide), boutons Ouvrir/Supprimer. Cliquer un
    # élément SÉLECTIONNE seulement ; "Ouvrir" charge le contenu sélectionné
    # dans l'éditeur (voir _on_open_clicked).
    # ------------------------------------------------------------------
    def _build_library_column(self) -> QFrame:
        column = QFrame()
        column.setProperty("class", "card")
        column.setFixedWidth(_LIBRARY_COLUMN_WIDTH)

        layout = QVBoxLayout(column)
        layout.setContentsMargins(13, 13, 13, 13)
        layout.setSpacing(6)

        title = QLabel(t("page.fastflags.library_title"))
        title.setStyleSheet("font-size: 14px; font-weight: 700; color: #E7E9EE; padding-bottom: 3px;")
        layout.addWidget(title)

        layout.addSpacing(4)

        self.library_search_input = QLineEdit()
        self.library_search_input.setPlaceholderText(t("page.fastflags.library_search_placeholder"))
        self.library_search_input.textChanged.connect(lambda _text: self._refresh_library())
        layout.addWidget(self.library_search_input)

        self.import_btn = QPushButton(t("page.fastflags.library_import_btn"))
        self.import_btn.setProperty("class", "secondaryButton")
        self.import_btn.clicked.connect(self._on_import_clicked)
        layout.addWidget(self.import_btn)

        # "Exporter" : même principe que sur la Bibliothèque Macro (écrit le
        # preset sélectionné — intégré ou personnalisé — dans un fichier JSON
        # choisi par l'utilisateur). Toujours visible, désactivé tant que
        # rien n'est sélectionné (voir _on_library_item_selected).
        self.export_btn = QPushButton(t("page.fastflags.library_export_btn"))
        self.export_btn.setProperty("class", "secondaryButton")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._on_export_clicked)
        layout.addWidget(self.export_btn)

        layout.addSpacing(6)

        # Liste et message "vide" partagent une même zone (QStackedWidget),
        # exactement comme la Bibliothèque de la page Macro.
        self.library_empty_label = QLabel(t("page.fastflags.library_empty"))
        self.library_empty_label.setWordWrap(True)
        self.library_empty_label.setStyleSheet(f"color: {STATUS_NEUTRAL}; font-size: 12px;")

        self.library_list = QListWidget()
        # Cliquer un élément ne fait plus que le sélectionner (surbrillance) :
        # il faut cliquer explicitement "Ouvrir" pour charger son contenu
        # dans l'éditeur — plus besoin de popup de confirmation avec ce
        # système à deux temps (remplace l'ancienne confirmation au clic).
        self.library_list.itemClicked.connect(self._on_library_item_selected)
        # Plus de bouton "Supprimer" fixe : la suppression se fait désormais
        # via un clic droit sur l'élément (menu contextuel, voir
        # _on_library_context_menu), comme dans la Bibliothèque Macro et le
        # tableau Macro Simple.
        self.library_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.library_list.customContextMenuRequested.connect(self._on_library_context_menu)
        # Espace entre le texte et la scrollbar — règle globale, voir
        # CLAUDE.md/ui/scrollbar_style.py.
        apply_viewport_scrollbar_gap(self.library_list)

        self.library_stack = QStackedWidget()
        self.library_stack.addWidget(self.library_empty_label)
        self.library_stack.addWidget(self.library_list)
        layout.addWidget(self.library_stack, 1)

        # Toujours visible : désactivé (grisé) plutôt que masqué quand rien
        # n'est sélectionné, pour ne jamais décaler le reste de la colonne.
        self.open_btn = QPushButton(t("page.fastflags.library_open_btn"))
        self.open_btn.setProperty("class", "secondaryButton")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._on_open_clicked)
        layout.addWidget(self.open_btn)

        return column

    def _refresh_library(self) -> None:
        self.library_list.clear()
        self.open_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        query = self.library_search_input.text().strip().lower()

        for key in _PRESET_ORDER:
            name = t(_PRESET_NAME_KEYS[key])
            if query and query not in name.lower():
                continue
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setData(_ROLE_KIND, "builtin")
            self.library_list.addItem(item)

        for path, name in list_custom_presets():
            if query and query not in name.lower():
                continue
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setData(_ROLE_KIND, "custom")
            self.library_list.addItem(item)

        has_items = self.library_list.count() > 0
        self.library_stack.setCurrentWidget(self.library_list if has_items else self.library_empty_label)

    def _on_library_item_selected(self, item: QListWidgetItem) -> None:
        # Sélectionne seulement (surbrillance) : ne charge rien dans
        # l'éditeur tant que "Ouvrir" n'est pas cliqué explicitement.
        self.open_btn.setEnabled(True)
        # Exportable dans tous les cas (preset intégré ou personnalisé) —
        # contrairement à "Supprimer" (menu contextuel), jamais restreint
        # aux presets personnalisés.
        self.export_btn.setEnabled(True)

    def _on_library_context_menu(self, pos) -> None:
        """Clic droit sur un élément de la Bibliothèque : menu avec
        "Supprimer" (remplace l'ancien bouton fixe). Le clic droit sélectionne
        aussi l'élément visé (comme un clic gauche). Les 3 presets prédéfinis
        ne sont jamais supprimables : aucun menu ne s'ouvre dessus, exactement
        comme l'ancien bouton restait désactivé pour eux."""
        item = self.library_list.itemAt(pos)
        if item is None:
            return
        self.library_list.setCurrentItem(item)
        self._on_library_item_selected(item)
        if item.data(_ROLE_KIND) != "custom":
            return

        menu = _build_styled_menu(self.library_list)
        delete_action = menu.addAction(t("page.fastflags.library_delete_btn"))
        chosen = menu.exec(self.library_list.viewport().mapToGlobal(pos))
        if chosen is delete_action:
            self._on_delete_clicked()

    def _on_open_clicked(self) -> None:
        item = self.library_list.currentItem()
        if item is None:
            return
        self._populate_table(self._resolve_item_flags(item))

    def _on_export_clicked(self) -> None:
        item = self.library_list.currentItem()
        if item is None:
            return
        dest_path, _ = QFileDialog.getSaveFileName(
            self, t("page.fastflags.library_export_btn"), f"{item.text()}.json", "JSON (*.json)"
        )
        if not dest_path:
            return
        export_flags_file(self._resolve_item_flags(item), dest_path)

    @staticmethod
    def _resolve_item_flags(item: QListWidgetItem) -> dict:
        kind = item.data(_ROLE_KIND)
        identifier = item.data(Qt.ItemDataRole.UserRole)
        if kind == "builtin":
            return PRESETS[identifier]
        return load_custom_preset(identifier)

    def _on_import_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, t("page.fastflags.library_import_btn"), "", "JSON (*.json)"
        )
        if not path:
            return
        if import_flags_file(path) is None:
            show_warning(self, t("page.fastflags.title"), t("page.fastflags.import_error"))
            return
        self._refresh_library()

    def _on_delete_clicked(self) -> None:
        item = self.library_list.currentItem()
        if item is None or item.data(_ROLE_KIND) != "custom":
            return
        delete_custom_preset(item.data(Qt.ItemDataRole.UserRole))
        self._refresh_library()

    def _on_save_preset(self) -> None:
        name = show_text_prompt(
            self, t("page.fastflags.save_preset_prompt_title"), t("page.fastflags.save_preset_prompt_label"),
            t("dialog.ok_btn"),
        )
        if not name:
            return
        flags = self._collect_flags_from_table()
        path = save_custom_preset(name.strip(), flags)
        if path is None:
            show_warning(self, t("page.fastflags.title"), t("page.fastflags.save_preset_error"))
            return
        # Devient aussi la configuration ACTIVE : depuis le retrait de
        # "Lancer Roblox" (qui écrivait ce même fichier auparavant, voir
        # features/fastflags/launcher.py), "Enregistrer" est la seule
        # action restante qui fait que CE tableau est bien ce que le
        # protocole roblox-player:// réappliquera au PROCHAIN vrai
        # lancement de Roblox — décision explicite (lier ça à "Enregistrer"
        # plutôt qu'un auto-apply à chaque frappe).
        export_flags_file(flags, get_fastflags_active_config_path())
        self._refresh_library()
        show_info(
            self, t("page.fastflags.title"),
            t("page.fastflags.save_preset_success").format(name=name.strip()),
        )

    # ------------------------------------------------------------------
    # Recommandation (page Performance) : charge dans l'éditeur, n'écrit
    # jamais directement sur le disque (voir docstring du module).
    # ------------------------------------------------------------------
    def show_recommendation(self, preset_key: str, reason: str) -> None:
        self._recommended_preset_key = preset_key
        preset_name = t(_PRESET_NAME_KEYS.get(preset_key, "page.fastflags.preset_balanced"))
        self.recommendation_label.setText(
            t("page.fastflags.recommendation_text").format(preset=preset_name, reason=reason)
        )
        self.recommendation_card.setVisible(True)

    def _on_load_recommended(self) -> None:
        if self._recommended_preset_key is not None:
            self._populate_table(PRESETS[self._recommended_preset_key])

    def _on_reset(self) -> None:
        if reset_to_default():
            # Vide aussi la configuration active (voir launcher.py) : sans
            # ça, un futur lancement via le protocole (sans cette page
            # ouverte) réappliquerait quand même l'ancienne configuration
            # mémorisée, annulant silencieusement ce "Réinitialiser".
            launcher.clear_active_config()
            self._populate_table({})
            self._refresh_status()
            show_info(self, t("page.fastflags.title"), t("page.fastflags.reset_success"))
        else:
            show_warning(self, t("page.fastflags.title"), t("page.fastflags.apply_error"))

    def _refresh_status(self) -> None:
        # Pas d'affichage visible (retiré à la demande) : ne fait plus que
        # resynchroniser le cache config à partir du fichier réel, gardé pour
        # un futur auto-apply au lancement (voir
        # auto_apply_fastflags_on_launch dans core/config.py).
        config.set("active_fastflags_preset", detect_active_preset())
