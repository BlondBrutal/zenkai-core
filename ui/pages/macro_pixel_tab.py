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
    QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from core.config import config
from core.i18n import t
from features.macro_pixel.key_swap_listener import KeySwapListener
from features.macro_pixel.pixel_macro import PixelMacroConfig, save_pixel_macro
from features.macro_pixel.pixel_watcher import PixelWatcherThread
from ui.animated_button import AnimatedButton
from ui.key_capture_widget import KeyCaptureWidget, display_label
from ui.pixel_picker_overlay import PixelPickerOverlay
from ui.status_colors import STATUS_CRITICAL, STATUS_NEUTRAL, STATUS_OK
from ui.toggle_switch import ToggleSwitch
from ui.trash_icon_button import TrashIconButton

_SWATCH_SIZE = 28
_FIELD_HEIGHT = 32
# Largeurs ajustées au contenu attendu (6 caractères hexa, jusqu'à
# "-99999" pour les coordonnées) plutôt qu'un espace vide inutile.
_HEX_FIELD_WIDTH = 68
_COORD_FIELD_WIDTH = 64
# Espacement label -> élément associé (x1.2 par rapport aux 6px d'origine).
_LABEL_GAP = 6  # -10%
_HEX_RE = re.compile(r"[^0-9A-Fa-f]")

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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)  # -10%

        control_row = self._build_control_row()

        layout.addLayout(self._build_header_row())
        layout.addLayout(self._build_name_row())
        layout.addLayout(self._build_pixel_section())
        layout.addLayout(self._build_reaction_keys_row())
        layout.addLayout(self._build_cooldown_section())

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
        row.setSpacing(7)  # -10%

        self.slot_title_label = QLabel()
        self.slot_title_label.setStyleSheet("font-size: 14px; font-weight: 700; color: #E7E9EE;")
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
        self.name_input.setFixedWidth(240)
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
        column.addWidget(label)
        column.addWidget(widget)
        return column

    def _build_pixel_section(self) -> QVBoxLayout:
        """Sélection du pixel : pas de cadre/carte autour (affiché à même la
        page, comme le reste des champs). Bouton "Sélectionner un pixel" au
        dessus, puis sur une même ligne : aperçu, couleur, Pixel X, Pixel Y —
        chacun avec son label au-dessus, dans l'esprit de l'AHK d'origine."""
        section = QVBoxLayout()
        section.setSpacing(6)

        self.pick_btn = AnimatedButton(t("page.macro.pixel.pick_btn"), variant="neutral", text_color=STATUS_NEUTRAL)
        self.pick_btn.clicked.connect(self._start_picking)
        pick_row = QHBoxLayout()
        pick_row.addWidget(self.pick_btn)
        pick_row.addStretch(1)
        section.addLayout(pick_row)

        self.color_swatch = QFrame()
        self.color_swatch.setFixedSize(_SWATCH_SIZE, _SWATCH_SIZE)
        self.color_swatch.setStyleSheet(_swatch_style(None))

        # Le carré (28px) est plus petit que la hauteur des champs voisins
        # (_FIELD_HEIGHT=32px) : un conteneur de hauteur fixe identique avec
        # un stretch égal au-dessus et en dessous le centre verticalement
        # par rapport à eux, au lieu de le laisser plaqué en haut.
        swatch_container = QWidget()
        swatch_container.setFixedHeight(_FIELD_HEIGHT)
        swatch_layout = QVBoxLayout(swatch_container)
        swatch_layout.setContentsMargins(0, 0, 0, 0)
        swatch_layout.addStretch(1)
        swatch_layout.addWidget(self.color_swatch)
        swatch_layout.addStretch(1)

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

        columns_row = QHBoxLayout()
        columns_row.setSpacing(10)
        # Pas de texte de label au-dessus du carré de couleur (juste
        # l'aperçu lui-même) : une chaîne vide plutôt qu'un label absent,
        # pour que sa colonne garde la même hauteur de départ que ses
        # voisines (Couleur/Pixel X/Pixel Y) et reste alignée avec elles.
        columns_row.addLayout(self._labeled_column("", swatch_container))
        columns_row.addLayout(self._labeled_column(t("page.macro.pixel.color_label"), self.hex_input))
        columns_row.addLayout(self._labeled_column(t("page.macro.pixel.pixel_x_label"), self.x_input))
        columns_row.addLayout(self._labeled_column(t("page.macro.pixel.pixel_y_label"), self.y_input))
        columns_row.addStretch(1)
        section.addLayout(columns_row)

        return section

    def _build_reaction_keys_row(self) -> QHBoxLayout:
        """Touche réaction 1 (déclenchée par le watcher), touche réaction 2
        (celle avec laquelle le "changement rapide de touche" l'échange) et
        la touche de swap elle-même (celle qui déclenche l'échange, écoutée
        globalement — voir key_swap_listener.py), toutes les trois sur la
        même ligne. Le swap est toujours actif dès qu'une touche de swap est
        définie — pas de toggle séparé (repris de ChangementToucheHandler
        dans l'AHK d'origine, sans le on/off de g_ChangementToucheEnabled)."""
        self.key_capture = KeyCaptureWidget()
        self.key_capture.setFixedHeight(_FIELD_HEIGHT)

        self.swap_target_capture = KeyCaptureWidget()
        self.swap_target_capture.setFixedHeight(_FIELD_HEIGHT)

        # exclude_click_buttons=True : touche de DÉCLENCHEMENT du swap (voir
        # docstring ci-dessus) — clic gauche/droit réservés à l'usage normal
        # de l'interface, voir key_capture_widget.py. Sans effet sur
        # key_capture/swap_target_capture ci-dessus (touches de RÉACTION :
        # le clic simulé PAR la macro, n'importe quel bouton est légitime).
        self.swap_key_capture = KeyCaptureWidget(exclude_click_buttons=True)
        self.swap_key_capture.setFixedHeight(_FIELD_HEIGHT)
        self.swap_key_capture.keyChanged.connect(lambda _key: self._sync_swap_listener())

        row = QHBoxLayout()
        row.setSpacing(9)  # -10%
        row.addLayout(self._labeled_column(t("page.macro.pixel.reaction1_label"), self.key_capture))
        row.addLayout(self._labeled_column(t("page.macro.pixel.reaction2_label"), self.swap_target_capture))
        row.addLayout(self._labeled_column(t("page.macro.pixel.swap_key_label"), self.swap_key_capture))
        row.addStretch(1)
        return row

    def _build_cooldown_section(self) -> QHBoxLayout:
        """Temps de recharge (repris de TP_COOLDOWN_MS dans l'AHK d'origine,
        voir pixel_watcher.py) : toujours actif, pas de toggle séparé — un
        champ à 0 (ou vide) équivaut à aucun délai."""
        self.cooldown_seconds_input = QLineEdit()
        self.cooldown_seconds_input.setValidator(QDoubleValidator(0.0, 3600.0, 2, self))
        self.cooldown_seconds_input.setPlaceholderText("0.0")
        self.cooldown_seconds_input.setFixedWidth(_COORD_FIELD_WIDTH + 20)
        self.cooldown_seconds_input.setFixedHeight(_FIELD_HEIGHT)

        row = QHBoxLayout()
        row.addLayout(self._labeled_column(t("page.macro.pixel.cooldown_seconds_label"), self.cooldown_seconds_input))
        row.addStretch(1)
        return row

    def _build_control_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(9)  # -10%

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
        # Petite marge à droite : sans ça, ces boutons touchent directement
        # le bord du viewport (donc la scrollbar) une fois la colonne gauche
        # contrainte à sa largeur exacte par la QScrollArea (voir
        # MacroPage.__init__ dans page_macro.py). 35px (pas 14) : aligne en
        # plus le bord droit de Réinitialiser avec celui du groupe des 3
        # onglets "Macro type" tout en haut de la page (mesuré empiriquement,
        # même correctif que macro_simple_tab.py).
        row.addSpacing(35)
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
        self._overlay.show()

    def _on_pixel_picked(self, x: int, y: int, color: tuple) -> None:
        self.x_input.setText(str(x))
        self.y_input.setText(str(y))
        self.hex_input.setText(f"{color[0]:02X}{color[1]:02X}{color[2]:02X}")

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
        # Espacement réduit de 20% puis 10% (10px -> 8px -> 7px, même valeur
        # que macro_simple_tab.SimpleSlotChooserDialog pour rester cohérent).
        btn_row = QHBoxLayout()
        btn_row.setSpacing(7)
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


def _build_green_separator(width: int) -> QFrame:
    line = QFrame()
    line.setFixedSize(width, 2)
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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        self._slots_layout = QVBoxLayout()
        self._slots_layout.setSpacing(18)
        layout.addLayout(self._slots_layout)

        # Longueur mesurée pour s'arrêter exactement au bord DROIT du bouton
        # "Réinitialiser" (453px = x() + width() du bouton sur le 1er
        # emplacement, mesuré directement, une fois Enregistrer/Réinitialiser
        # eux-mêmes alignés sur les onglets "Macro type" — voir
        # _build_control_row) plutôt que de continuer sur toute la largeur —
        # aligné à gauche pour ne pas être centré/étiré par le layout (mesure
        # empirique fixe, pas recalculée par langue ; voir la même
        # correction dans macro_simple_tab.py).
        layout.addWidget(_build_green_separator(453), 0, Qt.AlignmentFlag.AlignLeft)

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
            separator = _build_green_separator(453)
            self._slots_layout.addWidget(separator, 0, Qt.AlignmentFlag.AlignLeft)

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
