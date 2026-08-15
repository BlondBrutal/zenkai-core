"""
Page "Curseur" : personnalise le curseur Windows (système), le curseur en
jeu (overlay Roblox à canal alpha réel, voir features/cursor/roblox_overlay.py)
et le crosshair (overlay fixe au centre de l'écran, voir
features/cursor/crosshair_overlay.py) à partir d'une image fournie par
l'utilisateur — repris de la page CURSOR de "Global Macro v2.ahk"
(features/cursor/cursor_manager.py).
"""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QSlider, QVBoxLayout

from core.i18n import t
from features.cursor.cursor_image import DEFAULT_SIZE, MAX_SIZE, MIN_SIZE
from features.cursor.cursor_manager import get_cursor_manager
from ui.animated_button import AnimatedButton
from ui.pages.base_page import BasePage
from ui.status_colors import STATUS_NEUTRAL, STATUS_OK

_IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.gif *.ico *.cur)"


class _CursorSection(QFrame):
    """Une section (Windows, Roblox ou Crosshair) : image actuelle,
    Importer/Réinitialiser, taille — repris de la structure des sections
    GENERAL/ROBLOX de l'AHK, réutilisée telle quelle pour le Crosshair."""

    def __init__(self, title: str, on_import, on_reset, on_size_changed, parent=None):
        super().__init__(parent)
        self.setProperty("class", "card")
        self._on_import = on_import
        self._on_reset = on_reset
        self._on_size_changed = on_size_changed

        layout = QVBoxLayout(self)
        # Padding réduit (haut/bas 24 -> 16, côtés 24 -> 18) par rapport à la
        # valeur d'origine de cette carte (encore utilisée telle quelle par
        # d'autres cartes de l'app, ex. macro_pixel_tab.py/
        # macro_simple_tab.py::_build_card, qui restent à 24/14 — cette
        # réduction est spécifique à la page Curseur).
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 15px; font-weight: 700; color: #E7E9EE; padding-bottom: 3px;")
        layout.addWidget(title_label)

        current_row = QHBoxLayout()
        current_row.setSpacing(6)
        eyebrow = QLabel(t("page.cursor.current_label"))
        eyebrow.setStyleSheet(f"font-size: 12px; color: {STATUS_NEUTRAL};")
        current_row.addWidget(eyebrow)
        self.current_label = QLabel(t("page.cursor.none"))
        self.current_label.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {STATUS_NEUTRAL};")
        current_row.addWidget(self.current_label)
        current_row.addStretch(1)
        layout.addLayout(current_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.import_btn = AnimatedButton(t("page.cursor.import_btn"), variant="neutral")
        self.import_btn.clicked.connect(lambda: self._on_import())
        btn_row.addWidget(self.import_btn)
        self.reset_btn = AnimatedButton(t("page.cursor.reset_btn"), variant="neutral")
        self.reset_btn.clicked.connect(lambda: self._on_reset())
        btn_row.addWidget(self.reset_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        # Espace additionnel spécifique à CET écart (en plus du spacing()
        # général de 14px du layout) : malgré un écart mesuré identique
        # (14px) des deux côtés du bloc "Taille"/"32 px" via la géométrie
        # réelle, le rendu réel montrait "Taille" au contact visuel de la
        # ligne de boutons au-dessus — 14px seuls ne suffisent pas ici (texte
        # + ligne de boutons juste au-dessus, contrairement à en dessous où
        # rien ne resserre visuellement le slider). Rompt donc la symétrie
        # stricte au profit de l'absence de chevauchement, qui prime.
        layout.addSpacing(10)
        size_header = QHBoxLayout()
        size_label = QLabel(t("page.cursor.size_label"))
        size_label.setStyleSheet(f"font-size: 12px; color: {STATUS_NEUTRAL};")
        size_header.addWidget(size_label)
        size_header.addStretch(1)
        self.size_value_label = QLabel(f"{DEFAULT_SIZE} px")
        self.size_value_label.setStyleSheet(f"font-size: 12px; color: {STATUS_NEUTRAL};")
        size_header.addWidget(self.size_value_label)
        layout.addLayout(size_header)

        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(MIN_SIZE, MAX_SIZE)
        self.size_slider.setTickInterval(16)
        self.size_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.size_slider.setValue(DEFAULT_SIZE)
        self.size_slider.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self.size_slider)

    def _on_slider_changed(self, value: int) -> None:
        self.size_value_label.setText(f"{value} px")
        self._on_size_changed(value)

    def set_current(self, path: str) -> None:
        if path:
            self.current_label.setText(os.path.basename(path))
            self.current_label.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {STATUS_OK};")
        else:
            self.current_label.setText(t("page.cursor.none"))
            self.current_label.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {STATUS_NEUTRAL};")

    def set_size(self, size: int) -> None:
        self.size_slider.blockSignals(True)
        self.size_slider.setValue(size)
        self.size_slider.blockSignals(False)
        self.size_value_label.setText(f"{size} px")


class CursorPage(BasePage):
    def __init__(self, parent=None):
        super().__init__(t("page.cursor.title"), "", parent)
        self.add_info_badge(t("page.cursor.subtitle"))
        self._manager = get_cursor_manager()

        # Marge droite réduite (32 -> 16), comme la page Macro (référence) :
        # sans ça, le contenu de cette page s'arrête plus tôt que celui de
        # Macro et laisse un vide inutile à droite (incohérence visuelle
        # entre pages, voir aussi page_performance.py/page_license.py).
        margins = self.content_layout().contentsMargins()
        self.content_layout().setContentsMargins(margins.left(), margins.top(), 16, margins.bottom())

        body = QVBoxLayout()
        # -35% (16 -> 10) : écart vertical entre les 3 blocs (Curseur
        # Windows/Curseur en jeu/Crosshair).
        body.setSpacing(10)

        self.general_section = _CursorSection(
            t("page.cursor.section_general"),
            self._on_import_general, self._on_reset_general, self._on_general_size_changed,
        )
        body.addWidget(self.general_section)

        self.roblox_section = _CursorSection(
            t("page.cursor.section_roblox"),
            self._on_import_roblox, self._on_reset_roblox, self._on_roblox_size_changed,
        )
        body.addWidget(self.roblox_section)

        self.crosshair_section = _CursorSection(
            t("page.cursor.section_crosshair"),
            self._on_import_crosshair, self._on_reset_crosshair, self._on_crosshair_size_changed,
        )
        body.addWidget(self.crosshair_section)

        # Le stretch final doit vivre au niveau de content_layout() (comme
        # sur les autres pages, ex. page_fastflags.py), pas à l'intérieur de
        # ce layout imbriqué : sans stretch propre au niveau de
        # content_layout(), tout l'espace vertical excédentaire de la page
        # remontait dans la rangée titre elle-même (elle s'étirait sur toute
        # la hauteur disponible), ce qui désalignait le titre par rapport au
        # badge "?" et poussait tout le contenu anormalement bas.
        self.content_layout().addLayout(body)
        self.content_layout().addStretch(1)

        self._refresh()

    def _refresh(self) -> None:
        self.general_section.set_current(self._manager.general_path)
        self.general_section.set_size(self._manager.general_size)
        self.roblox_section.set_current(self._manager.roblox_path)
        self.roblox_section.set_size(self._manager.roblox_size)
        self.crosshair_section.set_current(self._manager.crosshair_path)
        self.crosshair_section.set_size(self._manager.crosshair_size)

    def _on_import_general(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, t("page.cursor.import_btn"), "", _IMAGE_FILTER)
        if not path:
            return
        if not self._manager.apply_general(path):
            self._show_error()
            return
        self._refresh()

    def _on_reset_general(self) -> None:
        self._manager.reset_general()
        self._refresh()

    def _on_general_size_changed(self, value: int) -> None:
        self._manager.set_general_size(value)

    def _on_import_roblox(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, t("page.cursor.import_btn"), "", _IMAGE_FILTER)
        if not path:
            return
        if not self._manager.apply_roblox(path):
            self._show_error()
            return
        self._refresh()

    def _on_reset_roblox(self) -> None:
        self._manager.reset_roblox()
        self._refresh()

    def _on_roblox_size_changed(self, value: int) -> None:
        self._manager.set_roblox_size(value)

    def _on_import_crosshair(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, t("page.cursor.import_btn"), "", _IMAGE_FILTER)
        if not path:
            return
        if not self._manager.apply_crosshair(path):
            self._show_error()
            return
        self._refresh()

    def _on_reset_crosshair(self) -> None:
        self._manager.reset_crosshair()
        self._refresh()

    def _on_crosshair_size_changed(self, value: int) -> None:
        self._manager.set_crosshair_size(value)

    def _show_error(self) -> None:
        QMessageBox.warning(self, t("page.cursor.title"), t("page.cursor.apply_error"))
