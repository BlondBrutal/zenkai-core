"""
Page Fleasion : bibliothèque de presets de remplacement d'assets Roblox
(textures/sons/meshes/skybox — voir https://github.com/fleasion/Fleasion,
GPL-3.0), calquée sur la mécanique de la page Custom Script (AutoHotkey,
voir ui/pages/page_custom_script.py) mais SANS analyse heuristique : un
preset Fleasion est une liste structurée de règles de remplacement (Asset
ID -> ID/URL/fichier local/suppression), jamais du code arbitraire — pas de
risque équivalent à un script AHK à scanner avant lancement.

Différence importante avec Custom Script (voir CLAUDE.md, section
"Architecture : Fleasion") : Fleasion n'a pas de mode CLI — c'est une appli
tray UNIQUE qui charge elle-même tous les fichiers présents dans son propre
dossier de configs. Cette page ne lance donc jamais "un preset" comme un
script ; elle DÉPLOIE les règles du preset actif dans le dossier de configs
de Fleasion (features/fleasion/config_writer.py) et lance/arrête le process
Fleasion PARTAGÉ (features/fleasion/process_manager.py) via le toggle
"Actif" de chaque preset en Bibliothèque — le coupe-circuit global, lui, ne
fait que désactiver nos règles sans jamais toucher au process (voir
_on_kill_switch_toggled, décision explicite de l'utilisateur : Fleasion
peut aussi lui servir pour des presets créés hors de cette page).
"""
import json
import logging
import os
import shutil
import uuid
from datetime import datetime

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMenu, QTableWidget,
    QVBoxLayout, QWidget,
)

from core.config import config
from core.i18n import t
from features.fleasion import config_writer, fleasion_detect
from features.fleasion.preset_store import (
    ALL_MODES, MODE_ID, MODE_LOCAL, MODE_REMOVE, FleasionPresetEntry, FleasionRule,
    delete_preset, export_preset, import_preset, list_presets, preset_assets_dir, save_preset,
)
from features.fleasion.process_manager import RunningFleasion, start_fleasion, stop_fleasion
from ui.animated_button import AnimatedButton
from ui.pages.base_page import BasePage
from ui.scrollbar_style import apply_viewport_scrollbar_gap, style_scrollbar_directly
from ui.status_colors import STATUS_NEUTRAL
from ui.styled_dropdown import StyledDropdown
from ui.styled_message_box import show_warning
from ui.toggle_switch import ToggleSwitch

logger = logging.getLogger("zenkaiontop.fleasion")

COL_ASSET_IDS, COL_MODE, COL_TARGET, COL_ACTIVE = range(4)

_MODE_OPTIONS = [
    (MODE_ID, "page.fleasion.mode_id"),
    ("url", "page.fleasion.mode_url"),
    (MODE_LOCAL, "page.fleasion.mode_local"),
    (MODE_REMOVE, "page.fleasion.mode_remove"),
]

_ROW_HEIGHT = 34

# Même menu contextuel stylé que celui des tableaux d'étapes Macro (voir
# ui/pages/macro_simple_tab.py::_build_styled_menu) — copie locale
# volontaire, cohérente avec la convention déjà en place de légère
# duplication de ce petit helper plutôt que de le factoriser prématurément.
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
    menu.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    menu.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
    menu.setStyleSheet(_CONTEXT_MENU_QSS)
    return menu


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class _RulesTable(QTableWidget):
    """QTableWidget qui garde l'événement wheel pour lui tout seul — même
    pattern que _StepsTable dans ui/pages/macro_simple_tab.py (voir sa
    docstring pour le pourquoi : sans ça, un survol du tableau en butée
    ferait défiler la page entière en plus/à la place du tableau)."""

    def wheelEvent(self, event) -> None:
        super().wheelEvent(event)
        event.accept()


class _TargetCell(QWidget):
    """Champ "Remplacer par" + bouton "Parcourir…" (visible seulement en
    mode Local) : composite car son comportement dépend du Mode choisi sur
    la même ligne (voir set_mode, branché sur le StyledDropdown voisin)."""

    def __init__(self, target: str, mode: str, on_browse, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.line_edit = QLineEdit(target)
        layout.addWidget(self.line_edit, 1)

        self.browse_btn = AnimatedButton(
            t("page.fleasion.browse_btn"), variant="neutral", height=26, horizontal_padding=10, font_pixel_size=11,
        )
        self.browse_btn.clicked.connect(lambda: on_browse(self))
        layout.addWidget(self.browse_btn)

        self.set_mode(mode)

    def set_mode(self, mode: str) -> None:
        is_remove = mode == MODE_REMOVE
        is_local = mode == MODE_LOCAL
        self.line_edit.setEnabled(not is_remove)
        # En mode Local, le champ n'est rempli QUE via "Parcourir…" (jamais
        # tapé à la main) : le texte affiché est un chemin relatif au
        # dossier d'assets du preset ("/nom_fichier.ext"), sans rapport avec
        # un chemin réel sur le disque de l'utilisateur.
        self.line_edit.setReadOnly(is_local)
        self.browse_btn.setVisible(is_local)

    def target(self) -> str:
        return self.line_edit.text().strip()

    def set_target(self, value: str) -> None:
        self.line_edit.setText(value)


class _PresetRowWidget(QWidget):
    """Ligne de la bibliothèque : nom (extensible) + interrupteur "Actif" —
    même technique que _ScriptRowWidget (ui/pages/page_custom_script.py),
    sans badge de sévérité (pas d'analyse de risque pour un preset Fleasion,
    voir docstring du module)."""

    def __init__(self, name: str, checked: bool, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 4, 2)
        layout.setSpacing(4)

        name_label = QLabel(name)
        name_label.setStyleSheet("color: #E7E9EE; font-size: 12px;")
        name_label.setMinimumWidth(0)
        layout.addWidget(name_label, 1, Qt.AlignmentFlag.AlignVCenter)

        self.toggle = ToggleSwitch(checked=checked)
        layout.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignVCenter)


def _wrap_centered(widget: QWidget) -> QWidget:
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignCenter)
    return container


class FleasionPage(BasePage):
    def __init__(self, parent=None):
        super().__init__(t("page.fleasion.title"), "", parent)
        self.add_info_badge(t("page.fleasion.subtitle"))
        self.add_beta_badge(t("app.beta_warning"))

        self._current_path: str | None = None
        self._current_entry: FleasionPresetEntry | None = None
        self._entries: dict[str, tuple[str, FleasionPresetEntry]] = {}
        # Ids des presets dont le toggle "Actif" (Bibliothèque) est ON —
        # indépendant du coupe-circuit global, voir _on_kill_switch_toggled.
        self._active_entry_ids: set[str] = set()
        self._shared_process: RunningFleasion | None = None

        self.header_layout().addWidget(self._build_kill_switch_control())

        margins = self.content_layout().contentsMargins()
        self.content_layout().setContentsMargins(margins.left(), margins.top(), 16, margins.bottom())

        main_row = QHBoxLayout()
        main_row.setSpacing(16)
        main_row.addWidget(self._build_editor_column(), 1)
        main_row.addWidget(self._build_library_column())
        self.content_layout().addLayout(main_row, 1)

        self._refresh_library()

        QApplication.instance().aboutToQuit.connect(self._stop_shared_process_if_running)

    # ------------------------------------------------------------------
    # Coupe-circuit global : désactive nos règles (Statut=Off réécrit dans
    # les fichiers déployés) mais NE TOUCHE PAS au process Fleasion lui-même
    # — décision explicite (contrairement à MacroPage/CustomScriptPage, où
    # le coupe-circuit arrête aussi tout ce qui tourne) : l'utilisateur peut
    # aussi se servir de Fleasion pour des presets créés hors de cette page.
    # ------------------------------------------------------------------
    def _build_kill_switch_control(self) -> QWidget:
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        label = QLabel(t("page.fleasion.kill_switch_label"))
        label.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {STATUS_NEUTRAL};")
        row.addWidget(label)

        initial_enabled = bool(config.get("fleasion_globally_enabled", True))
        self.kill_switch = ToggleSwitch(checked=initial_enabled)
        self.kill_switch.toggled.connect(self._on_kill_switch_toggled)
        row.addWidget(self.kill_switch)
        return wrapper

    def _on_kill_switch_toggled(self, checked: bool) -> None:
        config.set("fleasion_globally_enabled", checked)
        for entry_id in list(self._active_entry_ids):
            result = self._entries.get(entry_id)
            if result is None:
                continue
            _, entry = result
            if checked:
                config_writer.deploy_preset(entry, active=True)
            else:
                config_writer.undeploy_preset(entry)

    # ------------------------------------------------------------------
    # Colonne éditeur
    # ------------------------------------------------------------------
    def _build_editor_column(self) -> QWidget:
        wrapper = QWidget()
        wrapper.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(t("page.fleasion.name_placeholder"))
        top_row.addWidget(self.name_input, 1)

        self.import_btn = AnimatedButton(t("page.fleasion.import_btn"), variant="neutral", font_pixel_size=13)
        self.import_btn.clicked.connect(self._on_import_clicked)
        top_row.addWidget(self.import_btn)

        self.export_btn = AnimatedButton(t("page.fleasion.export_btn"), variant="neutral", font_pixel_size=13)
        self.export_btn.clicked.connect(self._on_export_clicked)
        top_row.addWidget(self.export_btn)
        layout.addLayout(top_row)

        self.rules_table = self._build_rules_table()
        layout.addWidget(self.rules_table, 1)

        bottom_button_row = QHBoxLayout()
        bottom_button_row.setSpacing(10)
        bottom_button_row.addStretch(1)
        self.save_btn = AnimatedButton(t("page.fleasion.save_btn"), variant="neutral")
        self.save_btn.clicked.connect(self._on_save_clicked)
        bottom_button_row.addWidget(self.save_btn)
        self.reset_btn = AnimatedButton(t("page.fleasion.reset_btn"), variant="neutral")
        self.reset_btn.clicked.connect(self._on_reset_clicked)
        bottom_button_row.addWidget(self.reset_btn)
        layout.addLayout(bottom_button_row)

        return wrapper

    def _build_rules_table(self) -> QTableWidget:
        table = _RulesTable(0, 4)
        table.setObjectName("stepsTable")
        table.setHorizontalHeaderLabels([
            t("page.fleasion.col_asset_ids"), t("page.fleasion.col_mode"),
            t("page.fleasion.col_target"), t("page.fleasion.col_enabled"),
        ])
        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(False)
        table.setShowGrid(False)
        table.setFrameShape(QFrame.Shape.NoFrame)

        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(COL_ASSET_IDS, 150)
        table.setColumnWidth(COL_MODE, 100)
        table.setColumnWidth(COL_ACTIVE, 50)
        # "Remplacer par" absorbe l'espace restant (largeur très variable :
        # ID court, URL longue, ou nom de fichier local) — seule colonne en
        # Stretch, les 3 autres restent Fixed (non redimensionnables à la
        # souris, cohérent avec les tableaux Macro).
        table.horizontalHeader().setSectionResizeMode(COL_TARGET, QHeaderView.ResizeMode.Stretch)

        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self._on_table_context_menu)

        apply_viewport_scrollbar_gap(table)
        style_scrollbar_directly(table.verticalScrollBar())
        return table

    def _on_table_context_menu(self, pos) -> None:
        row = self.rules_table.rowAt(pos.y())
        menu = _build_styled_menu(self.rules_table)
        add_action = menu.addAction(t("page.fleasion.ctx_add_rule"))
        delete_action = menu.addAction(t("page.fleasion.ctx_delete_rule")) if row >= 0 else None

        chosen = menu.exec(self.rules_table.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is add_action:
            insert_at = row + 1 if row >= 0 else self.rules_table.rowCount()
            self._add_rule_row(FleasionRule(), at_row=insert_at)
        elif delete_action is not None and chosen is delete_action:
            self.rules_table.removeRow(row)

    def _add_rule_row(self, rule: FleasionRule, at_row: int | None = None) -> int:
        row = self.rules_table.rowCount() if at_row is None else at_row
        self.rules_table.insertRow(row)
        self.rules_table.setRowHeight(row, _ROW_HEIGHT)

        asset_ids_edit = QLineEdit(rule.asset_ids)
        asset_ids_edit.setPlaceholderText(t("page.fleasion.asset_ids_placeholder"))
        self.rules_table.setCellWidget(row, COL_ASSET_IDS, asset_ids_edit)

        mode_combo = StyledDropdown()
        for _, label_key in _MODE_OPTIONS:
            mode_combo.addItem(t(label_key))
        mode_index = [m for m, _ in _MODE_OPTIONS].index(rule.mode) if rule.mode in ALL_MODES else 0
        mode_combo.setCurrentIndex(mode_index)
        self.rules_table.setCellWidget(row, COL_MODE, mode_combo)

        target_cell = _TargetCell(rule.target, rule.mode, self._on_browse_target_clicked)
        self.rules_table.setCellWidget(row, COL_TARGET, target_cell)
        mode_combo.currentIndexChanged.connect(
            lambda idx, cell=target_cell: cell.set_mode(_MODE_OPTIONS[idx][0])
        )

        active_toggle = ToggleSwitch(checked=rule.enabled)
        self.rules_table.setCellWidget(row, COL_ACTIVE, _wrap_centered(active_toggle))

        return row

    def _on_browse_target_clicked(self, target_cell: "_TargetCell") -> None:
        path, _ = QFileDialog.getOpenFileName(self, t("page.fleasion.browse_btn"), "", "Tous les fichiers (*.*)")
        if not path:
            return
        # Un preset tout juste créé (jamais encore Enregistrer) n'a pas
        # encore d'id stable : on lui en attribue un dès ce premier import
        # local, pour que le dossier d'assets (nommé d'après cet id, voir
        # preset_store.preset_assets_dir) reste le même après "Enregistrer".
        if self._current_entry is None:
            self._current_entry = FleasionPresetEntry(id=uuid.uuid4().hex, name="", rules=[])
        assets_dir = preset_assets_dir(self._current_entry)
        filename = os.path.basename(path)
        try:
            shutil.copyfile(path, os.path.join(assets_dir, filename))
        except OSError:
            logger.exception("Copie du fichier local Fleasion impossible (%s)", path)
            return
        target_cell.set_target(f"/{filename}")

    def _read_rules(self) -> list[FleasionRule]:
        rules = []
        for row in range(self.rules_table.rowCount()):
            asset_ids_edit = self.rules_table.cellWidget(row, COL_ASSET_IDS)
            mode_combo = self.rules_table.cellWidget(row, COL_MODE)
            target_cell = self.rules_table.cellWidget(row, COL_TARGET)
            active_container = self.rules_table.cellWidget(row, COL_ACTIVE)
            active_toggle = active_container.layout().itemAt(0).widget()

            asset_ids = asset_ids_edit.text().strip()
            if not asset_ids:
                continue  # ligne vide ignorée silencieusement, pas d'erreur bloquante
            mode = _MODE_OPTIONS[mode_combo.currentIndex()][0]
            rules.append(FleasionRule(
                asset_ids=asset_ids, mode=mode, target=target_cell.target(), enabled=active_toggle.isChecked(),
            ))
        return rules

    def _populate_table(self, rules: list[FleasionRule]) -> None:
        self.rules_table.setRowCount(0)
        for rule in rules:
            self._add_rule_row(rule)

    # ------------------------------------------------------------------
    # Enregistrer / Réinitialiser / Importer / Exporter
    # ------------------------------------------------------------------
    def _on_save_clicked(self) -> None:
        name = self.name_input.text().strip()
        rules = self._read_rules()
        if not name or not rules:
            show_warning(self, t("page.fleasion.title"), t("page.fleasion.save_empty_error"))
            return

        entry = self._current_entry or FleasionPresetEntry(
            id=uuid.uuid4().hex, name=name, rules=rules, created_at=_now_iso(), updated_at="",
        )
        entry.name = name
        entry.rules = rules

        self._current_path = save_preset(entry, existing_path=self._current_path)
        self._current_entry = entry
        self._refresh_library()

        # Redéploie immédiatement si ce preset est actif : les modifications
        # doivent s'appliquer sans avoir à refaire OFF/ON.
        if entry.id in self._active_entry_ids and bool(config.get("fleasion_globally_enabled", True)):
            config_writer.deploy_preset(entry, active=True)

    def _on_reset_clicked(self) -> None:
        # Vide juste le tableau de l'éditeur, sans toucher au nom ni au
        # preset actuellement chargé — même comportement que "Réinitialiser"
        # sur la page Custom Script.
        self.rules_table.setRowCount(0)

    def _on_new_clicked(self) -> None:
        self._current_path = None
        self._current_entry = None
        self.name_input.clear()
        self.rules_table.setRowCount(0)

    def _on_import_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, t("page.fleasion.import_btn"), "",
            "Preset Zenkai (*.zip);;Config Fleasion (*.json)",
        )
        if not path:
            return

        if path.lower().endswith(".zip"):
            try:
                entry = import_preset(path)
            except Exception:
                logger.exception("Import de preset Fleasion (.zip) impossible (%s)", path)
                show_warning(self, t("page.fleasion.import_btn"), t("page.fleasion.import_error"))
                return
            self._current_path = None  # sera recalculé au prochain Enregistrer si l'utilisateur modifie
            self._current_entry = entry
            self.name_input.setText(entry.name)
            self._populate_table(entry.rules)
            self._refresh_library()
            return

        # Config Fleasion native isolée (une seule règle, exportée depuis le
        # Dashboard Fleasion lui-même) : ajoute une ligne au tableau courant
        # plutôt que de remplacer tout le preset — même esprit que l'import
        # ".ahk" brut de la page Custom Script.
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                data = data[0] if data else {}
            mode = str(data.get("mode", MODE_ID))
            rule = FleasionRule(
                asset_ids=str(data.get("assetIds", data.get("asset_ids", ""))),
                mode=mode if mode in ALL_MODES else MODE_ID,
                target=str(data.get("replaceWith", data.get("target", ""))),
                enabled=bool(data.get("status", data.get("enabled", True))),
            )
        except Exception:
            logger.exception("Import de config Fleasion (.json) impossible (%s)", path)
            show_warning(self, t("page.fleasion.import_btn"), t("page.fleasion.import_error"))
            return
        self._add_rule_row(rule)

    def _on_export_clicked(self) -> None:
        """Exporte l'élément actuellement SÉLECTIONNÉ dans la Bibliothèque
        (pas le contenu de l'éditeur) — même convention que Custom Script/
        Macro/Fast Flags (voir ui/pages/page_custom_script.py::_on_export_clicked)."""
        item = self.library_list.currentItem()
        if item is None:
            return
        entry_id = item.data(Qt.ItemDataRole.UserRole)
        result = self._entries.get(entry_id)
        if result is None:
            return
        _, entry = result
        dest_path, _ = QFileDialog.getSaveFileName(
            self, t("page.fleasion.export_btn"), f"{entry.name}.zip", "Preset Zenkai (*.zip)",
        )
        if not dest_path:
            return
        export_preset(entry, dest_path)

    # ------------------------------------------------------------------
    # Bibliothèque
    # ------------------------------------------------------------------
    def _build_library_column(self) -> QFrame:
        column = QFrame()
        column.setProperty("class", "card")
        column.setFixedWidth(260)

        layout = QVBoxLayout(column)
        layout.setContentsMargins(13, 13, 13, 13)
        layout.setSpacing(6)

        title = QLabel(t("page.fleasion.library_title"))
        title.setStyleSheet("font-size: 14px; font-weight: 700; color: #E7E9EE; padding-bottom: 3px;")
        layout.addWidget(title)

        self.library_list = QListWidget()
        self.library_list.setStyleSheet(
            "QListWidget::item { padding: 0px; }"
            "QListWidget::item:hover { background-color: transparent; }"
            "QListWidget::item:selected { background-color: transparent; }"
        )
        self.library_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        apply_viewport_scrollbar_gap(self.library_list)
        self.library_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.library_list.customContextMenuRequested.connect(self._on_library_context_menu)
        self.library_list.itemClicked.connect(self._on_library_item_clicked)
        layout.addWidget(self.library_list, 1)

        return column

    def _refresh_library(self) -> None:
        self.library_list.clear()
        self._entries = {}
        for path, entry in list_presets():
            self._entries[entry.id] = (path, entry)
            checked = entry.id in self._active_entry_ids
            row_widget = _PresetRowWidget(entry.name, checked)
            row_widget.toggle.toggled.connect(
                lambda checked, entry_id=entry.id, row=row_widget: self._on_preset_toggled(entry_id, checked, row)
            )
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            item.setSizeHint(QSize(0, 34))
            self.library_list.addItem(item)
            self.library_list.setItemWidget(item, row_widget)

    def _on_library_item_clicked(self, item: QListWidgetItem) -> None:
        entry_id = item.data(Qt.ItemDataRole.UserRole)
        result = self._entries.get(entry_id)
        if result is None:
            return
        path, entry = result
        self._current_path = path
        self._current_entry = entry
        self.name_input.setText(entry.name)
        self._populate_table(entry.rules)

    def _on_library_context_menu(self, pos) -> None:
        item = self.library_list.itemAt(pos)
        if item is None:
            return
        self.library_list.setCurrentItem(item)
        entry_id = item.data(Qt.ItemDataRole.UserRole)

        menu = _build_styled_menu(self.library_list)
        delete_action = menu.addAction(t("page.fleasion.library_delete_btn"))
        chosen = menu.exec(self.library_list.viewport().mapToGlobal(pos))
        if chosen is delete_action:
            self._on_delete_entry(entry_id)

    def _on_delete_entry(self, entry_id: str) -> None:
        result = self._entries.get(entry_id)
        if result is None:
            return
        path, entry = result
        if entry_id in self._active_entry_ids:
            self._deactivate_preset(entry_id, entry)
        config_writer.remove_deployed_preset(entry)
        delete_preset(path, entry)
        if self._current_path == path:
            self._on_new_clicked()
        self._refresh_library()

    # ------------------------------------------------------------------
    # Toggle "Actif" par preset — lance/arrête le process Fleasion PARTAGÉ
    # (comptage de références : le process ne démarre qu'au premier preset
    # actif, ne s'arrête qu'au dernier qui repasse OFF). Même garde-fous que
    # CustomScriptPage._on_script_toggled (coupe-circuit global, exécutable
    # introuvable) mais sans étape d'analyse de risque (voir docstring du
    # module).
    # ------------------------------------------------------------------
    def _on_preset_toggled(self, entry_id: str, checked: bool, row_widget: _PresetRowWidget) -> None:
        result = self._entries.get(entry_id)
        if result is None:
            row_widget.toggle.setChecked(False, animate=False)
            return
        _, entry = result

        if checked:
            if not bool(config.get("fleasion_globally_enabled", True)):
                row_widget.toggle.setChecked(False, animate=False)
                return
            if fleasion_detect.health_check() != "ok":
                row_widget.toggle.setChecked(False, animate=False)
                show_warning(
                    self, t("page.fleasion.fleasion_missing_title"), t("page.fleasion.fleasion_missing_text"),
                )
                return

            if not self._active_entry_ids:
                running, error_detail = start_fleasion()
                if running is None:
                    row_widget.toggle.setChecked(False, animate=False)
                    if error_detail:
                        show_warning(
                            self, t("page.fleasion.title"),
                            t("page.fleasion.launch_failed_detail").format(detail=error_detail),
                        )
                    else:
                        show_warning(self, t("page.fleasion.title"), t("page.fleasion.launch_failed"))
                    return
                self._shared_process = running

            config_writer.deploy_preset(entry, active=True)
            self._active_entry_ids.add(entry_id)
        else:
            self._deactivate_preset(entry_id, entry)

    def _deactivate_preset(self, entry_id: str, entry: FleasionPresetEntry) -> None:
        config_writer.undeploy_preset(entry)
        self._active_entry_ids.discard(entry_id)
        if not self._active_entry_ids and self._shared_process is not None:
            if not stop_fleasion(self._shared_process):
                show_warning(self, t("page.fleasion.title"), t("page.fleasion.stop_failed"))
            self._shared_process = None

    def _stop_shared_process_if_running(self) -> None:
        if self._shared_process is not None:
            stop_fleasion(self._shared_process)
            self._shared_process = None
        self._active_entry_ids.clear()

    def shutdown(self) -> None:
        """Arrêt INCONDITIONNEL et SYNCHRONE du process partagé — appelé
        juste avant que cette page soit réellement détruite (voir
        MainWindow.reload_language), pas seulement masquée."""
        self._stop_shared_process_if_running()
