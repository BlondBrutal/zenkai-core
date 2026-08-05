"""
Page Macro : regroupe les trois types de macros (Simple / Pixel / Combo)
sous des sous-onglets en haut, avec une colonne Bibliothèque filtrée par
type sur la droite (transversale aux 3 types, Partie 1.4 du brief).

Seul Combo reste au stade squelette pour l'instant (Simple et Pixel ont une
implémentation réelle) — voir _IMPLEMENTED_TYPES et _LIST_FUNCS ci-dessous
pour l'unique endroit à toucher quand un nouveau type sera implémenté.

Ordre des sous-onglets choisi par dépendance croissante : Simple (brique
de base, enregistrement/replay) -> Pixel (ajoute un déclencheur visuel) ->
Combo (compose plusieurs macros déjà enregistrées, donc le plus avancé).
"""
import json

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QStackedWidget,
    QVBoxLayout, QWidget,
)

from core.config import config
from core.i18n import t
from features.macro_pixel.pixel_macro import delete_macro, export_macro, list_pixel_macros
from features.macro_pixel.pixel_macro import import_macro as import_pixel_macro
from features.macro_simple.macro_simple import list_macro_simple_macros
from features.macro_simple.macro_simple import import_macro as import_simple_macro
from ui.info_badge import InfoBadge
from ui.pages.base_page import BasePage
from ui.pages.macro_pixel_tab import PixelMacroTab
from ui.pages.macro_simple_tab import MacroSimpleTab
from ui.scrollbar_style import style_scrollbar_directly
from ui.status_colors import STATUS_CRITICAL, STATUS_NEUTRAL, STATUS_OK
from ui.toggle_switch import ToggleSwitch

# Seuls Simple et Pixel ont une implémentation réelle pour l'instant (Combo
# reste un squelette) : la Bibliothèque ne liste/n'importe/n'exporte donc que
# ces types-là tant que Combo n'est pas construit. `delete_macro`/
# `export_macro` sont génériques (aucune logique propre à un type) et donc
# partagés tels quels entre tous les types, sans dispatch nécessaire.
_IMPLEMENTED_TYPES = {"pixel", "simple"}
_LIST_FUNCS = {"pixel": list_pixel_macros, "simple": list_macro_simple_macros}
_IMPORT_FUNCS = {"pixel": import_pixel_macro, "simple": import_simple_macro}

_TAB_ACTIVE_COLOR = STATUS_OK
_TAB_INACTIVE_COLOR = "#C7CBD3"
_TAB_SUBTITLE_ACTIVE = "#7DE4CF"
_TAB_SUBTITLE_INACTIVE = STATUS_NEUTRAL
_HIGHLIGHT_STYLE = (
    "QFrame#segmentHighlight {"
    f" background-color: rgba(23, 184, 151, 40); border: 1px solid rgba(23, 184, 151, 115);"
    " border-radius: 8px; }"
)

# (clé interne, clé de traduction du titre, clé de traduction du sous-texte)
_TAB_DEFS = [
    ("simple", "page.macro.tab1_title", "page.macro.tab1_subtitle"),
    ("pixel", "page.macro.tab2_title", "page.macro.tab2_subtitle"),
    ("combo", "page.macro.tab3_title", "page.macro.tab3_subtitle"),
]


class _SegmentButton(QFrame):
    """Un segment à deux lignes (titre + petit sous-texte), sans fond propre :
    le fond "actif" est porté par le highlight glissant du parent."""

    clicked = pyqtSignal(str)

    def __init__(self, macro_type: str, title: str, subtitle: str, tooltip_text: str, parent=None):
        super().__init__(parent)
        self.macro_type = macro_type
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        # Marge horizontale réduite (32 -> 18) : avec la colonne gauche
        # maintenant contrainte par une QScrollArea verticale (voir
        # MacroPage.__init__), les 3 segments à 32px de marge dépassaient la
        # largeur du viewport et se retrouvaient tronqués/inatteignables
        # (le défilement horizontal étant volontairement désactivé). Marge
        # verticale (7) et taille de police inchangées.
        layout.setContentsMargins(18, 7, 18, 7)
        layout.setSpacing(2)

        # Titre + badge "?" groupés et centrés ensemble (stretch des deux
        # côtés), pour expliquer spécifiquement ce type de macro au survol.
        title_row = QHBoxLayout()
        title_row.setSpacing(4)
        title_row.addStretch(1)

        self.title_label = QLabel(title)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        title_row.addWidget(self.title_label)

        # Taille réduite (14px) et proportionnelle au texte du titre (15px) :
        # la taille par défaut du badge (20px) le faisait paraître disproportionné
        # à côté d'un texte de cette taille.
        title_row.addWidget(InfoBadge(tooltip_text, size=14))
        title_row.addStretch(1)
        layout.addLayout(title_row)

        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.subtitle_label)

        self.set_active(False)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self.macro_type)
        super().mousePressEvent(event)

    def set_active(self, active: bool) -> None:
        title_color = _TAB_ACTIVE_COLOR if active else _TAB_INACTIVE_COLOR
        subtitle_color = _TAB_SUBTITLE_ACTIVE if active else _TAB_SUBTITLE_INACTIVE
        self.title_label.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {title_color}; border: none;")
        self.subtitle_label.setStyleSheet(f"font-size: 11.5px; color: {subtitle_color}; border: none;")


class _SegmentedTabs(QFrame):
    """Barre d'onglets façon "segmented control" : un fond glisse jusqu'au
    segment actif (QPropertyAnimation sur la géométrie), au lieu d'un simple
    soulignement statique."""

    tab_changed = pyqtSignal(str)

    def __init__(self, tab_defs: list[tuple[str, str, str]], parent=None):
        super().__init__(parent)
        self.setProperty("class", "card")
        self._active_key = tab_defs[0][0]

        outer = QHBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(2)

        self.highlight = QFrame(self)
        self.highlight.setObjectName("segmentHighlight")
        self.highlight.setStyleSheet(_HIGHLIGHT_STYLE)

        self._buttons: dict[str, _SegmentButton] = {}
        for macro_type, title_key, subtitle_key in tab_defs:
            tooltip_key = f"page.macro.{macro_type}_placeholder"
            btn = _SegmentButton(macro_type, t(title_key), t(subtitle_key), t(tooltip_key))
            btn.clicked.connect(self._on_button_clicked)
            outer.addWidget(btn)
            self._buttons[macro_type] = btn

        self.highlight.lower()

        self._animation = QPropertyAnimation(self.highlight, b"geometry")
        self._animation.setDuration(220)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._buttons[self._active_key].set_active(True)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._move_highlight(animate=False)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._move_highlight(animate=False)

    def _on_button_clicked(self, macro_type: str) -> None:
        if macro_type == self._active_key:
            return
        self._active_key = macro_type
        for key, btn in self._buttons.items():
            btn.set_active(key == macro_type)
        self._move_highlight(animate=True)
        self.tab_changed.emit(macro_type)

    def _move_highlight(self, animate: bool) -> None:
        target = self._buttons[self._active_key].geometry()
        if not target.isValid():
            return
        if animate:
            self._animation.stop()
            self._animation.setStartValue(self.highlight.geometry())
            self._animation.setEndValue(target)
            self._animation.start()
        else:
            self.highlight.setGeometry(target)


class MacroPage(BasePage):
    def __init__(self, parent=None):
        super().__init__(t("page.macro.title"), "", parent)
        self.add_info_badge(t("page.macro.info_tooltip"))

        # Marge droite réduite : sinon la colonne Bibliothèque, déjà collée
        # à droite du body_row, laisse un vide trop large avant le bord de
        # la fenêtre en plus de cette marge de page.
        margins = self.content_layout().contentsMargins()
        self.content_layout().setContentsMargins(margins.left(), margins.top(), 16, margins.bottom())

        # Kill switch global, au même niveau que le titre, aligné à droite.
        self.header_layout().addWidget(self._build_kill_switch_control())

        # --- Colonne gauche (onglets + contenu) et colonne Bibliothèque, dans
        # une même rangée : la Bibliothèque démarre ainsi à la même hauteur
        # que les onglets, pas seulement que la zone de contenu en dessous.
        # Chaque sous-onglet (Simple/Pixel/Combo) a SA PROPRE QScrollArea
        # (verticale uniquement, voir _build_tab_scroll_area) — les onglets
        # "Macro type 1/2/3" restent un sibling fixe AU-DESSUS de ces zones de
        # défilement, jamais scrollés avec le contenu. Une seule QScrollArea
        # partagée par les 3 onglets (autour de tout le QStackedWidget) ferait
        # que changer d'onglet garde la MÊME position de défilement d'un
        # onglet à l'autre au lieu de repartir de zéro sur le nouvel onglet
        # (QStackedWidget cache les pages inactives sans les détruire, donc
        # une QScrollArea PAR page garde son propre état de défilement intact
        # pendant qu'elle est cachée). Un onglet Pixel/Simple avec plusieurs
        # emplacements peut dépasser la hauteur visible (jusqu'à 3, chacun
        # avec sa config complète), et sans ces QScrollArea c'est la FENÊTRE
        # PRINCIPALE elle-même qui grandirait pour faire de la place (Qt
        # agrandit une fenêtre pour respecter la taille minimale de son
        # contenu) au lieu de faire défiler ce contenu à taille de fenêtre
        # fixe. La colonne Bibliothèque reste un sibling normal, hors de la
        # zone de défilement.
        main_row = QHBoxLayout()
        main_row.setSpacing(16)

        left_wrapper = QWidget()
        left_wrapper.setStyleSheet("background: transparent;")
        left_wrapper_layout = QVBoxLayout(left_wrapper)
        left_wrapper_layout.setContentsMargins(0, 0, 0, 0)
        left_wrapper_layout.setSpacing(14)

        self.tabs = _SegmentedTabs(_TAB_DEFS)
        self.tabs.tab_changed.connect(self._on_tab_clicked)
        tabs_row = QHBoxLayout()
        tabs_row.addWidget(self.tabs)
        tabs_row.addStretch(1)
        left_wrapper_layout.addLayout(tabs_row)

        self.stack = QStackedWidget()
        self._stack_index: dict[str, int] = {}
        for macro_type, _, _ in _TAB_DEFS:
            if macro_type == "pixel":
                self.pixel_tab = PixelMacroTab()
                self.pixel_tab.macro_saved.connect(self._refresh_library)
                widget = self.pixel_tab
            elif macro_type == "simple":
                self.simple_tab = MacroSimpleTab()
                self.simple_tab.macro_saved.connect(self._refresh_library)
                widget = self.simple_tab
            else:
                widget = self._build_placeholder()
            self._stack_index[macro_type] = self.stack.addWidget(self._build_tab_scroll_area(widget))

        left_wrapper_layout.addWidget(self.stack, 1)

        main_row.addWidget(left_wrapper, 1)

        self.library_column = self._build_library_column()
        main_row.addWidget(self.library_column)

        self.content_layout().addLayout(main_row, 1)

        self._on_tab_clicked("simple")

    # ------------------------------------------------------------------
    def _build_tab_scroll_area(self, content: QWidget) -> QScrollArea:
        """Une QScrollArea dédiée par sous-onglet (voir le commentaire sur
        main_row dans __init__) : chaque onglet garde ainsi son propre état
        de défilement, indépendant des deux autres."""
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.addWidget(content)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # AlwaysOn (pas AsNeeded) : réserve la largeur de la scrollbar de façon
        # CONSTANTE, que le contenu déborde ou non. Avec AsNeeded, un onglet
        # dont le contenu tient dans la fenêtre (ex: Simple avec 1 seul
        # emplacement) récupère toute la largeur du viewport, alors qu'un
        # onglet plus haut (Pixel, plus de sections par emplacement) qui a
        # besoin de défiler perd la largeur de la scrollbar — les boutons
        # Enregistrer/Réinitialiser (alignés sur le bord droit du contenu, voir
        # _build_control_row de chaque onglet) se retrouvaient donc décalés
        # d'un onglet à l'autre (et même d'un emplacement ajouté à l'autre au
        # sein d'un même onglet). Le thumb est ensuite masqué (fondu dans la
        # piste, voir QScrollBar::handle:vertical:disabled dans
        # scrollbar_style.py) quand il n'y a rien à défiler, pour ne pas
        # afficher une barre pleine inutile tout en gardant la largeur fixe.
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        # QScrollArea peint sa propre viewport avec la couleur de palette Qt
        # par défaut tant qu'on ne la force pas transparente (même limitation
        # que pour les résultats de diagnostic sur la page Performance).
        scroll_area.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll_area.setWidget(container)
        scroll_area.viewport().setStyleSheet("background: transparent;")
        # RoundedScrollBarStyle (le QProxyStyle global) ne s'applique pas de
        # façon fiable à cette scrollbar précise (vérifié par échantillonnage
        # de pixels : piste invisible, fond de la page qui transparaissait) —
        # on la stylise donc directement sur l'instance (voir
        # ui/scrollbar_style.py).
        vbar = scroll_area.verticalScrollBar()
        style_scrollbar_directly(vbar)
        vbar.setEnabled(vbar.maximum() > vbar.minimum())
        vbar.rangeChanged.connect(lambda lo, hi: vbar.setEnabled(hi > lo))
        return scroll_area

    # ------------------------------------------------------------------
    # Kill switch global : coupe d'un coup toutes les macros actives.
    # Persisté (core/config.py) — le futur moteur d'exécution des macros
    # (Simple/Pixel/Combo, pas encore implémenté) devra vérifier ce réglage
    # avant de déclencher quoi que ce soit.
    # ------------------------------------------------------------------
    def _build_kill_switch_control(self) -> QWidget:
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)  # -10% (2e passe : 8 -> 7 -> 6)

        label = QLabel(t("page.macro.kill_switch_label"))
        label.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {STATUS_NEUTRAL};")
        row.addWidget(label)

        initial_enabled = bool(config.get("macros_globally_enabled", True))
        self.kill_switch = ToggleSwitch(checked=initial_enabled)
        self.kill_switch.toggled.connect(self._on_kill_switch_toggled)
        row.addWidget(self.kill_switch)

        return wrapper

    def _on_kill_switch_toggled(self, checked: bool) -> None:
        config.set("macros_globally_enabled", checked)
        if not checked:
            self.pixel_tab.stop_if_running()
            self.simple_tab.stop_if_running()

    # ------------------------------------------------------------------
    def _build_placeholder(self) -> QWidget:
        # Le texte descriptif de ce type de macro est déjà donné par le badge
        # "?" du sous-onglet correspondant — le répéter ici ferait doublon.
        # Seule la mention "bientôt disponible" est nouvelle : sans elle, cet
        # onglet paraît cassé/vide plutôt que "pas encore construit".
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 32, 0, 0)

        label = QLabel(t("page.macro.tab3_placeholder"))
        label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        label.setWordWrap(True)
        label.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {STATUS_NEUTRAL};")
        layout.addWidget(label)

        layout.addStretch(1)
        return widget

    def _build_library_column(self) -> QFrame:
        column = QFrame()
        column.setProperty("class", "card")
        column.setFixedWidth(260)

        layout = QVBoxLayout(column)
        layout.setContentsMargins(13, 13, 13, 13)  # -10% (2e passe : 16 -> 14 -> 13)
        layout.setSpacing(6)  # -10% (2e passe : 8 -> 7 -> 6)

        title = QLabel(t("page.macro.library_title"))
        title.setStyleSheet("font-size: 14px; font-weight: 700; color: #E7E9EE;")
        layout.addWidget(title)

        self.library_filter_label = QLabel()
        self.library_filter_label.setStyleSheet("font-size: 11px; color: #9BA1AB;")
        layout.addWidget(self.library_filter_label)

        layout.addSpacing(4)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(t("page.macro.library_search_placeholder"))
        self.search_input.textChanged.connect(lambda _text: self._refresh_library())
        layout.addWidget(self.search_input)

        self.import_btn = QPushButton(t("page.macro.library_import_btn"))
        self.import_btn.setProperty("class", "secondaryButton")
        self.import_btn.clicked.connect(self._on_import_clicked)
        layout.addWidget(self.import_btn)

        self.export_btn = QPushButton(t("page.macro.library_export_btn"))
        self.export_btn.setProperty("class", "secondaryButton")
        self.export_btn.clicked.connect(self._on_export_clicked)
        layout.addWidget(self.export_btn)

        layout.addSpacing(6)  # -10% (2e passe : 8 -> 7 -> 6)

        # Liste et message "vide" partagent une même zone (QStackedWidget) de
        # hauteur constante (stretch=1, comme avant pour la seule liste) :
        # seul le CONTENU de cette zone change selon qu'il y a des macros ou
        # non, jamais l'espacement des éléments autour (titre, sous-titre,
        # recherche, Importer/Exporter, bouton Supprimer).
        self.library_empty_label = QLabel(t("page.macro.library_empty"))
        self.library_empty_label.setWordWrap(True)
        self.library_empty_label.setStyleSheet("color: #6B7280; font-size: 12px;")

        self.library_list = QListWidget()
        self.library_list.itemClicked.connect(self._on_library_item_clicked)

        self.library_stack = QStackedWidget()
        self.library_stack.addWidget(self.library_empty_label)
        self.library_stack.addWidget(self.library_list)
        layout.addWidget(self.library_stack, 1)

        # Toujours visible : désactivé (grisé) plutôt que masqué quand rien
        # n'est sélectionnable, pour ne jamais décaler le reste de la colonne.
        self.delete_btn = QPushButton(t("page.macro.library_delete_btn"))
        self.delete_btn.setProperty("class", "secondaryButton")
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        layout.addWidget(self.delete_btn)

        return column

    def _on_tab_clicked(self, macro_type: str) -> None:
        self.stack.setCurrentIndex(self._stack_index[macro_type])
        self._current_macro_type = macro_type

        subtitle_key = next(s for k, _, s in _TAB_DEFS if k == macro_type)
        self.library_filter_label.setText(
            t("page.macro.library_filter_caption").format(type=t(subtitle_key))
        )
        self._refresh_library()

    # ------------------------------------------------------------------
    # Bibliothèque : ne liste/importe/exporte que les types réellement
    # implémentés (Simple et Pixel) — Combo affiche l'état vide tant que son
    # moteur n'existe pas, plutôt que de brancher des boutons sur une action
    # qui ne ferait rien. `_LIST_FUNCS` fait tout le dispatch par type.
    # ------------------------------------------------------------------
    def _refresh_library(self) -> None:
        supported = self._current_macro_type in _IMPLEMENTED_TYPES
        self.import_btn.setEnabled(supported)
        self.import_btn.setToolTip("" if supported else t("page.macro.library_disabled_tooltip"))

        self.library_list.clear()
        self._library_entries: dict[str, str] = {}  # nom -> chemin fichier

        if not supported:
            self.library_stack.setCurrentWidget(self.library_empty_label)
            self.delete_btn.setEnabled(False)
            self.export_btn.setEnabled(False)
            self.export_btn.setToolTip(t("page.macro.library_disabled_tooltip"))
            return

        list_fn = _LIST_FUNCS[self._current_macro_type]
        query = self.search_input.text().strip().lower()
        macros = [
            (path, macro) for path, macro in list_fn()
            if not query or query in macro.name.lower()
        ]

        has_items = bool(macros)
        self.library_stack.setCurrentWidget(self.library_list if has_items else self.library_empty_label)
        self.delete_btn.setEnabled(has_items)
        self.export_btn.setEnabled(has_items)
        self.export_btn.setToolTip("")

        for path, macro in macros:
            item = QListWidgetItem(macro.name)
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.library_list.addItem(item)
            self._library_entries[macro.name] = path

    def _on_library_item_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        list_fn = _LIST_FUNCS.get(self._current_macro_type)
        matches = [macro for p, macro in (list_fn() if list_fn else []) if p == path]
        if not matches:
            self._refresh_library()
            return
        if self._current_macro_type == "pixel":
            self.pixel_tab.request_load(matches[0])
        elif self._current_macro_type == "simple":
            self.simple_tab.request_load(matches[0])

    def _on_delete_clicked(self) -> None:
        item = self.library_list.currentItem()
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        delete_macro(path)
        self._refresh_library()

    def _on_import_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, t("page.macro.library_import_btn"), "", "Zenkai Macro (*.zkmacro)"
        )
        if not path:
            return
        try:
            # Le dispatch se fait sur le "type" du FICHIER, pas sur l'onglet
            # actif : importer une macro Simple pendant que l'onglet Pixel
            # est ouvert doit fonctionner (elle apparaîtra dans la
            # Bibliothèque en repassant sur l'onglet Simple), pas échouer
            # avec une erreur de type qui n'a pas lieu d'être.
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            macro_type = data.get("type")
            import_fn = _IMPORT_FUNCS.get(macro_type)
            if import_fn is None:
                raise ValueError(f"Type de macro non supporté : {macro_type!r}")
            import_fn(path)
        except Exception as exc:
            QMessageBox.warning(self, t("page.macro.library_import_btn"),
                                 t("page.macro.library_import_error").format(error=str(exc)))
            return
        self._refresh_library()

    def _on_export_clicked(self) -> None:
        item = self.library_list.currentItem()
        if item is None:
            return
        source_path = item.data(Qt.ItemDataRole.UserRole)
        dest_path, _ = QFileDialog.getSaveFileName(
            self, t("page.macro.library_export_btn"), f"{item.text()}.zkmacro", "Zenkai Macro (*.zkmacro)"
        )
        if not dest_path:
            return
        export_macro(source_path, dest_path)
