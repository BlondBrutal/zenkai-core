"""
Page Paramètres : langue de l'application (Partie 3.2 du brief), journal
de sécurité (actions sensibles journalisées par l'app — voir
core/security_log.py), signalement de bug (carte "Support") et liens
Discord/TikTok (carte "Communauté", voir _build_support_section/
_build_community_section) — la carte "Support" est placée AVANT
"Communauté" (signaler un problème est l'action la plus "utilitaire", à
côté de Général/Sécurité, plutôt que noyée avec les réseaux sociaux).

Le changement de langue est appliqué à chaud, sans redémarrage : cette page
se contente de persister le choix et d'émettre language_changed, et c'est
MainWindow.reload_language() qui reconstruit toutes les pages dans la
nouvelle langue (voir ui/main_window.py) — pas de fermeture de l'app ni
d'action manuelle demandée à l'utilisateur.
"""
import logging
import os
from datetime import datetime

from PyQt6.QtCore import QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from core.changelog import load_changelog, current_version
from core.config import config
from core.i18n import get_language, set_language, t
from core.paths import get_logs_dir
from core.security_log import read_events
from ui.animated_button import AnimatedButton
from ui.pages.base_page import BasePage
from ui.scrollbar_style import apply_viewport_scrollbar_gap, style_scrollbar_directly
from ui.segmented_toggle import SegmentedToggle
from ui.status_colors import STATUS_CRITICAL, STATUS_NEUTRAL, STATUS_OK, STATUS_WARNING
from ui.styled_message_box import show_info, show_warning
from ui.toggle_switch import ToggleSwitch

logger = logging.getLogger("zenkaiontop.settings")

_LANGUAGES = [("fr", "FR"), ("en", "EN")]

# Liens externes de la section "Réseaux & Support" — jamais générés/devinés,
# ce sont exactement les URLs fournies dans la demande.
_DISCORD_URL = "https://discord.gg/G4jeHQ6k47"
_TIKTOK_URL = "https://tiktok.com/@zenkai.on.top"
_GITHUB_NEW_ISSUE_URL = "https://github.com/BlondBrutal/zenkai-core/issues/new"


def _open_url(url: str) -> None:
    """Ouvre un lien externe dans le navigateur par défaut de l'utilisateur
    — QDesktopServices.openUrl ne lève jamais (retourne juste False en cas
    d'échec, ex: aucun navigateur associé), rien à envelopper dans un
    try/except ici."""
    QDesktopServices.openUrl(QUrl(url))

# Même fond que le reste de l'app (voir CLAUDE.md, design system) : un
# QDialog nu utilise sinon la palette Qt par défaut (fond blanc).
_APP_BACKGROUND = "#1A1A1F"
# Texte principal (voir CLAUDE.md, design system) : couleur explicite des
# lignes NON sensibles du journal, pour ne jamais dépendre d'un héritage
# QSS implicite une fois qu'on peint aussi des lignes en STATUS_CRITICAL sur
# la même liste (voir _SecurityLogDialog).
_NORMAL_TEXT_COLOR = "#E7E9EE"

# Même menu contextuel stylé que celui de la Bibliothèque de macros/Custom
# Script (voir page_macro.py::_build_styled_menu,
# page_custom_script.py::_build_styled_menu) — copie locale volontaire,
# cohérente avec la convention déjà en place de légère duplication de ce
# petit helper plutôt que de le factoriser prématurément.
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

# Largeurs fixes des colonnes Horodatage/Action/Résultat d'une ligne du
# journal (voir _LogRowWidget) — seule la colonne Cible est extensible
# (stretch=1). Fixer les 3 autres colonnes garantit que le Résultat
# ("Succès"/"Échec") reste TOUJOURS visible, quelle que soit la longueur du
# libellé d'action ou de la cible — contrairement à une simple concaténation
# en un seul texte, où Qt pouvait tronquer la ligne ENTIÈRE (résultat
# inclus) quand elle dépassait la largeur du QListWidget.
_ROW_TIMESTAMP_WIDTH = 112
_ROW_ACTION_WIDTH = 220
_ROW_RESULT_WIDTH = 60

# Troncature en NOMBRE DE CARACTÈRES (pas en pixels via QFontMetrics) pour
# Action/Cible : plus approximatif qu'une élision au pixel près, mais
# entièrement indépendant de la police réellement résolue au moment du
# rendu — une élision par QFontMetrics calculée à la construction (ou même
# dans resizeEvent) s'est avérée donner un résultat FAUX une fois ce widget
# affiché dans un QDialog qui pose sa propre feuille de style (constaté :
# texte tronqué bien plus court que prévu, sans "...", débordant sur la
# colonne suivante — la police mesurée ne correspondait pas à la police
# réellement peinte). Les budgets ci-dessous sont volontairement prudents
# (marge confortable) pour les largeurs de colonnes ci-dessus.
_ROW_ACTION_MAX_CHARS = 32
_ROW_TARGET_MAX_CHARS = 26


def _elide_right(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _elide_middle(text: str, max_chars: int) -> str:
    """Tronque `text` en gardant le DÉBUT et la FIN (plutôt qu'une simple
    coupe à droite) : pour un chemin ou une clé de registre, les deux bouts
    sont ceux qui portent le plus d'information (lecteur/racine d'un côté,
    nom de fichier/sous-clé de l'autre)."""
    if len(text) <= max_chars:
        return text
    keep = max_chars - 3
    head = keep - keep // 2
    tail = keep // 2
    return f"{text[:head]}...{text[-tail:]}"


def _row_font() -> QFont:
    """Police EXPLICITE (pas seulement héritée du QSS global) pour les
    labels de _LogRowWidget — même principe que ui/animated_button.py (voir
    son commentaire sur sizeHint()) : sert uniquement à un rendu cohérent,
    PAS au calcul de troncature (voir _ROW_*_MAX_CHARS ci-dessus, choisis
    indépendamment de toute mesure de police)."""
    font = QFont("Segoe UI Variable Text")
    font.setPixelSize(12)
    return font


def _format_timestamp(iso_timestamp: str) -> str:
    """Convertit l'horodatage ISO stocké dans le journal (voir
    core/security_log.py, ex. "2026-08-12T15:27:40+02:00") en format
    lisible localisé pour l'affichage — seul l'AFFICHAGE change, le fichier
    lui-même garde le format ISO (portable, trié naturellement en l'état)."""
    try:
        dt = datetime.fromisoformat(iso_timestamp)
    except ValueError:
        return iso_timestamp
    pattern = "%d/%m/%Y %H:%M" if get_language() == "fr" else "%m/%d/%Y %H:%M"
    return dt.strftime(pattern)


# Code d'action (voir core/security_log.py::log_event, ex. "protocol_register")
# -> clé de traduction du libellé humain affiché dans le journal. Un code
# absent de ce dict (nouveau type d'action ajouté ailleurs sans mise à jour
# ici) retombe simplement sur son propre code brut, jamais une exception.
_ACTION_LABEL_KEYS = {
    "protocol_register": "page.settings.security_log_action.protocol_register",
    "protocol_unregister": "page.settings.security_log_action.protocol_unregister",
    "fastflags_backup": "page.settings.security_log_action.fastflags_backup",
    "fastflags_restore": "page.settings.security_log_action.fastflags_restore",
    "fastflags_inject": "page.settings.security_log_action.fastflags_inject",
    "uac_elevation": "page.settings.security_log_action.uac_elevation",
    "fix_power_plan": "page.settings.security_log_action.fix_power_plan",
    "fix_game_mode": "page.settings.security_log_action.fix_game_mode",
    "fix_game_dvr": "page.settings.security_log_action.fix_game_dvr",
    "fix_sysmain": "page.settings.security_log_action.fix_sysmain",
    "roblox_launch": "page.settings.security_log_action.roblox_launch",
    "roblox_kill": "page.settings.security_log_action.roblox_kill",
    "presentmon_launch": "page.settings.security_log_action.presentmon_launch",
    "custom_script_launch": "page.settings.security_log_action.custom_script_launch",
    "custom_script_stop": "page.settings.security_log_action.custom_script_stop",
    "custom_script_heuristic_scan": "page.settings.security_log_action.custom_script_heuristic_scan",
    "custom_script_defender_scan": "page.settings.security_log_action.custom_script_defender_scan",
    "custom_script_unlock": "page.settings.security_log_action.custom_script_unlock",
}


class _LogRowWidget(QWidget):
    """Une ligne du journal, en colonnes (voir les largeurs _ROW_* ci-
    dessus) plutôt qu'un unique QListWidgetItem texte : seule la colonne
    Cible est extensible, les 3 autres ont une largeur fixe — garantit que
    le Résultat ("Succès"/"Échec") reste TOUJOURS visible, quelle que soit
    la longueur du libellé d'action ou de la cible.

    Action et Cible sont tronqués en NOMBRE DE CARACTÈRES (voir
    _ROW_ACTION_MAX_CHARS/_ROW_TARGET_MAX_CHARS), pas via
    QFontMetrics.elidedText() : cette dernière approche donnait un résultat
    FAUX une fois ce widget affiché dans un QDialog posant sa propre feuille
    de style (constaté : texte tronqué bien plus court que prévu, sans
    "...", débordant sur la colonne suivante — la police mesurée par
    fontMetrics() ne correspondait pas à celle réellement peinte). La
    troncature par caractères est moins précise au pixel près, mais
    entièrement indépendante de la résolution de police. Valeur complète
    toujours consultable au survol (tooltip stylé globalement, voir
    theme.qss::QToolTip).

    Aucun fond peint explicitement (pas de "background: transparent" en QSS
    sur ce widget) : un QWidget nu sans feuille de style ne peint déjà rien
    par défaut, ce qui suffit à laisser transparaître le surlignage au
    survol/sélection peint par le QListWidget en dessous — ajouter une
    règle QSS ici avait déclenché un bug de rémanence visuelle (redessins
    incomplets, anciens pixels visibles sous le texte) sans nécessité."""

    def __init__(self, timestamp_text: str, action_text: str, target_text: str, result_text: str, color: str, parent=None):
        super().__init__(parent)
        self.setToolTip(target_text)
        font = _row_font()
        style = f"color: {color};"

        layout = QHBoxLayout(self)
        # Marge droite = 4 (marge normale) + CONTENT_SCROLLBAR_GAP (12) :
        # apply_viewport_scrollbar_gap (voir _SecurityLogDialog) réserve déjà
        # cet espace via setViewportMargins, mais cette ligne — contrairement
        # aux autres listes Bibliothèque de l'app, toutes posées dans une
        # carte avec sa propre marge — est le SEUL élément entre le bord du
        # QDialog et la scrollbar ; la porter aussi ici, directement sur le
        # widget de ligne, garantit l'espace même si le seul retrait du
        # viewport ne suffisait pas (vérifié par capture d'écran réelle : le
        # texte "Résultat" touchait toujours la scrollbar sans ce correctif).
        layout.setContentsMargins(4, 2, 4 + 12, 2)
        layout.setSpacing(10)

        ts_label = QLabel(timestamp_text)
        ts_label.setFixedWidth(_ROW_TIMESTAMP_WIDTH)
        ts_label.setFont(font)
        ts_label.setStyleSheet(style)
        layout.addWidget(ts_label)

        action_label = QLabel(_elide_right(action_text, _ROW_ACTION_MAX_CHARS))
        action_label.setFixedWidth(_ROW_ACTION_WIDTH)
        action_label.setFont(font)
        action_label.setStyleSheet(style)
        action_label.setToolTip(action_text)
        layout.addWidget(action_label)

        target_label = QLabel(_elide_middle(target_text, _ROW_TARGET_MAX_CHARS))
        target_label.setFont(font)
        target_label.setStyleSheet(style)
        # Un QLabel n'accepte pas nativement de rétrécir sous la largeur
        # naturelle de SON PROPRE texte (sa taille minimale par défaut =
        # sa taille préférée) : sans ce setMinimumWidth(0) explicite, si le
        # texte déjà tronqué ci-dessus restait malgré tout trop large pour
        # l'espace réellement dispo dans cette rangée (colonnes fixes +
        # marges), le layout — incapable de comprimer cette colonne sous
        # son minimum — laissait la colonne Cible chevaucher la colonne
        # Action plutôt que de simplement rogner l'affichage. Avec un
        # minimum à 0, elle peut toujours se comprimer davantage si besoin :
        # au pire un peu plus de texte caché, jamais de chevauchement.
        target_label.setMinimumWidth(0)
        layout.addWidget(target_label, 1)

        result_label = QLabel(result_text)
        result_label.setFixedWidth(_ROW_RESULT_WIDTH)
        result_label.setFont(font)
        result_label.setStyleSheet(style)
        layout.addWidget(result_label)


class _SecurityLogDialog(QDialog):
    """Popup "Voir les logs" : liste en lecture seule des actions déjà
    journalisées (core/security_log.py), les plus récentes en premier —
    même gabarit qu'une popup existante de la page Fast Flags
    (_KnownFlagsDialog) : simple QDialog + QListWidget stylé par le thème
    global (fond/bordure/coins arrondis 8px déjà définis dans theme.qss,
    aucune feuille de style supplémentaire nécessaire ici). Seules les
    lignes RÉELLEMENT marquées "sensibles" ressortent en STATUS_CRITICAL —
    les autres restent en texte standard (_NORMAL_TEXT_COLOR) ; jamais
    d'icône/emoji sur un statut, voir CLAUDE.md.

    Aucun changement visuel au survol/à la sélection d'une ligne (surcharge
    locale de QListWidget::item:hover/:selected en transparent, même
    principe que la Bibliothèque Custom Script) — le statut se lit
    uniquement à la couleur du texte, jamais à un aplat de fond. Clic droit
    sur une ligne → "Détails" affiche l'horodatage ISO complet et la cible
    non tronquée (voir _on_log_context_menu).

    "Ouvrir le dossier des logs" vit ICI (action secondaire, à côté de
    "Fermer") plutôt que sur la page Paramètres : c'est dans cette fenêtre
    qu'on consulte le journal, donc l'endroit le plus pertinent pour vouloir
    accéder au fichier brut — la page Paramètres n'a plus qu'UN SEUL
    contrôle pour cette section ("Voir les logs"), voir
    SettingsPage._build_security_section."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("page.settings.security_log_dialog_title"))
        self.resize(640, 440)
        self.setStyleSheet(f"background-color: {_APP_BACKGROUND};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        events = read_events()

        if events:
            list_widget = QListWidget()
            # La colonne Cible s'élide toujours à sa largeur réelle (voir
            # _LogRowWidget) : jamais de dépassement horizontal, donc jamais
            # besoin de cette barre de défilement — désactivée explicitement
            # plutôt que de compter implicitement sur ce résultat, pour ne
            # jamais revoir une barre pleine largeur oubliée au-dessus des
            # boutons.
            list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            # Espace entre le texte et la scrollbar verticale — règle
            # globale, voir CLAUDE.md/ui/scrollbar_style.py.
            apply_viewport_scrollbar_gap(list_widget)
            # Aucun changement visuel au survol/à la sélection — le statut
            # se lit uniquement à la couleur du texte de chaque ligne
            # (jamais d'aplat de fond), même surcharge locale que la
            # Bibliothèque Custom Script (page_custom_script.py).
            list_widget.setStyleSheet(
                "QListWidget::item:hover { background-color: transparent; }"
                "QListWidget::item:selected { background-color: transparent; }"
            )
            list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            list_widget.customContextMenuRequested.connect(
                lambda pos, lw=list_widget: self._on_log_context_menu(lw, pos)
            )
            for event in events:
                label = t(_ACTION_LABEL_KEYS.get(event.action, event.action))
                result_label = (
                    t("page.settings.security_log_result_ok") if event.result == "ok"
                    else t("page.settings.security_log_result_error")
                )
                color = STATUS_CRITICAL if event.sensitive else _NORMAL_TEXT_COLOR
                row_widget = _LogRowWidget(
                    _format_timestamp(event.timestamp), label, event.target, result_label, color,
                )
                item = QListWidgetItem()
                item.setSizeHint(QSize(0, 28))
                # Événement complet attaché à l'item (pas seulement les
                # champs déjà tronqués du widget de ligne) : le menu
                # contextuel "Détails" doit pouvoir afficher l'horodatage
                # ISO brut et la cible non tronquée.
                item.setData(Qt.ItemDataRole.UserRole, event)
                list_widget.addItem(item)
                list_widget.setItemWidget(item, row_widget)
            layout.addWidget(list_widget, 1)
        else:
            # Centré (pas juste aligné en haut) : un texte discret au milieu
            # de l'espace disponible plutôt qu'un grand vide sous un message
            # collé en haut de la fenêtre.
            empty_label = QLabel(t("page.settings.security_log_empty"))
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setWordWrap(True)
            empty_label.setStyleSheet(f"font-size: 13px; color: {STATUS_NEUTRAL};")
            layout.addWidget(empty_label, 1)

        button_row = QHBoxLayout()
        open_folder_btn = QPushButton(t("page.settings.open_logs_folder_btn"))
        open_folder_btn.setProperty("class", "secondaryButton")
        open_folder_btn.clicked.connect(self._on_open_logs_folder_clicked)
        button_row.addWidget(open_folder_btn)
        button_row.addStretch(1)
        close_btn = QPushButton(t("page.settings.security_log_close_btn"))
        close_btn.setProperty("class", "secondaryButton")
        close_btn.clicked.connect(self.close)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

    def _on_log_context_menu(self, list_widget: QListWidget, pos) -> None:
        item = list_widget.itemAt(pos)
        if item is None:
            return
        list_widget.setCurrentItem(item)
        event = item.data(Qt.ItemDataRole.UserRole)

        menu = _build_styled_menu(list_widget)
        details_action = menu.addAction(t("page.settings.security_log_details_btn"))
        chosen = menu.exec(list_widget.viewport().mapToGlobal(pos))
        if chosen is details_action:
            self._show_log_details(event)

    def _show_log_details(self, event) -> None:
        label = t(_ACTION_LABEL_KEYS.get(event.action, event.action))
        result_label = (
            t("page.settings.security_log_result_ok") if event.result == "ok"
            else t("page.settings.security_log_result_error")
        )
        sensitive_label = (
            t("page.settings.security_log_details_sensitive_yes") if event.sensitive
            else t("page.settings.security_log_details_sensitive_no")
        )
        text = t("page.settings.security_log_details_text").format(
            timestamp=event.timestamp, action=label, target=event.target,
            result=result_label, sensitive=sensitive_label,
        )
        show_info(self, t("page.settings.security_log_details_title"), text)

    def _on_open_logs_folder_clicked(self) -> None:
        # os.startfile (Windows uniquement, comme le reste de l'app) ouvre
        # l'explorateur directement sur ce dossier — jamais bloquant, jamais
        # fatal si ça échoue (dossier supprimé manuellement, etc.).
        try:
            os.startfile(get_logs_dir())
        except OSError as exc:
            logger.error("Impossible d'ouvrir le dossier des logs (%s)", exc)
            show_warning(
                self,
                t("page.settings.open_logs_folder_error_title"),
                t("page.settings.open_logs_folder_error"),
            )


def _build_bullet_list(items: list[str]) -> QLabel | None:
    """Une puce par ligne ("• texte"), même principe que
    _ScriptAnalysisDialog.findings_label (page_custom_script.py) : un seul
    QLabel wordWrap plutôt qu'un widget par ligne, largement suffisant pour
    une liste courte en lecture seule. None si la liste est vide."""
    if not items:
        return None
    label = QLabel("\n".join(f"• {item}" for item in items))
    label.setWordWrap(True)
    label.setStyleSheet(f"font-size: 12.5px; color: {_NORMAL_TEXT_COLOR};")
    return label


def _build_changelog_block(title_text: str, items: list[str], accent_color: str) -> QWidget | None:
    """Un groupe "Ajouts" ou "Corrections" : titre + puces, écart SERRÉ
    entre les deux (même groupe, voir spacing ci-dessous) — c'est l'écart
    ENTRE deux groupes (posé par l'appelant, _ChangelogDialog._build_entry_widget)
    qui doit rester nettement plus large pour bien les distinguer
    visuellement. Couleur de titre distincte par groupe (accent_color) :
    seul repère de hiérarchie en plus de l'espacement, jamais d'icône/emoji
    (voir CLAUDE.md). None si la liste est vide (pas de titre de section
    sans aucun contenu en dessous)."""
    bullets = _build_bullet_list(items)
    if bullets is None:
        return None
    block = QWidget()
    block.setStyleSheet("background: transparent;")
    layout = QVBoxLayout(block)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)

    title = QLabel(title_text)
    title.setStyleSheet(f"font-size: 11.5px; font-weight: 700; color: {accent_color};")
    layout.addWidget(title)
    layout.addWidget(bullets)
    return block


class _ChangelogDialog(QDialog):
    """Popup "Voir le changelog" : toutes les entrées de CHANGELOG.json
    (voir core/changelog.py), la plus récente en premier, chacune avec ses
    sections "Ajouts"/"Corrections" — même gabarit que _SecurityLogDialog
    (fond/bordure du thème global, boutons secondaryButton en bas)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("page.settings.changelog_dialog_title"))
        self.resize(480, 480)
        self.setStyleSheet(f"background-color: {_APP_BACKGROUND};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        entries = load_changelog()

        if entries:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setStyleSheet("background: transparent; border: none;")
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

            content = QWidget()
            content.setStyleSheet("background: transparent;")
            content_layout = QVBoxLayout(content)
            content_layout.setContentsMargins(0, 0, 0, 0)
            content_layout.setSpacing(16)

            for entry in entries:
                content_layout.addWidget(self._build_entry_widget(entry))
            content_layout.addStretch(1)

            scroll.setWidget(content)
            # Espace entre le texte et la scrollbar — règle globale, voir
            # CLAUDE.md/ui/scrollbar_style.py (une QScrollArea "nue" est,
            # elle aussi, un QAbstractScrollArea).
            apply_viewport_scrollbar_gap(scroll)
            layout.addWidget(scroll, 1)
        else:
            empty_label = QLabel(t("page.settings.changelog_empty"))
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setWordWrap(True)
            empty_label.setStyleSheet(f"font-size: 13px; color: {STATUS_NEUTRAL};")
            layout.addWidget(empty_label, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        close_btn = QPushButton(t("page.settings.security_log_close_btn"))
        close_btn.setProperty("class", "secondaryButton")
        close_btn.clicked.connect(self.close)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

    @staticmethod
    def _build_entry_widget(entry) -> QWidget:
        # Écart NETTEMENT plus large entre le header/le bloc "Ajouts"/le bloc
        # "Corrections" (12, ici) qu'à L'INTÉRIEUR d'un bloc (titre<->puces,
        # 4, voir _build_changelog_block) — c'est ce contraste qui rend les
        # deux catégories visuellement distinctes au lieu d'un mur de texte
        # uniforme. Couleur de titre différente par catégorie en plus
        # (STATUS_OK "Ajouts" / STATUS_WARNING "Corrections") : même logique
        # de repère que le reste de l'app (voir CLAUDE.md, jamais d'icône).
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        header = QLabel(
            t("page.settings.changelog_entry_header").format(version=entry.version, date=entry.date)
        )
        header.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {STATUS_OK};")
        layout.addWidget(header)

        added_block = _build_changelog_block(t("page.settings.changelog_added_title"), entry.added, STATUS_OK)
        if added_block is not None:
            layout.addWidget(added_block)

        fixed_block = _build_changelog_block(
            t("page.settings.changelog_fixed_title"), entry.fixed, STATUS_WARNING,
        )
        if fixed_block is not None:
            layout.addWidget(fixed_block)

        return container


class SettingsPage(BasePage):
    language_changed = pyqtSignal(str)
    always_on_top_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(t("page.settings.title"), "", parent)
        self.add_info_badge(t("page.settings.placeholder"))
        self.add_beta_badge(t("app.beta_warning"))

        # Le corps (les cartes) vit dans une QScrollArea dédiée, pas
        # directement dans content_layout() — même pattern que
        # ui/pages/page_macro.py::_build_tab_scroll_area/page_performance.py::
        # _build_scrollable_tab_container : à la fenêtre fixe (987x640, voir
        # ui/main_window.py), 5 cartes empilées (Général/Sécurité/Support/
        # Communauté/Notes des développeurs) dépassent la hauteur visible —
        # sans QScrollArea, Qt COMPRESSE le contenu pour le faire tenir dans
        # la place fixe restante (repéré ici : plus aucun espace de
        # respiration en bas) plutôt que de le faire défiler.
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        # Cohérent avec le rayon 14px des cartes elles-mêmes (voir CLAUDE.md,
        # design system : "Cartes principales : 14px").
        body_layout.setSpacing(14)
        body_layout.addWidget(self._build_general_section())
        body_layout.addWidget(self._build_security_section())
        body_layout.addWidget(self._build_support_section())
        body_layout.addWidget(self._build_community_section())
        body_layout.addWidget(self._build_devnotes_section())
        body_layout.addStretch(1)

        self.content_layout().addWidget(self._build_scroll_area(body), 1)

    def _build_scroll_area(self, body: QWidget) -> QScrollArea:
        """Même réglages qu'ailleurs dans l'app (voir CLAUDE.md, section
        "Scrollbars") : setViewportMargins via apply_viewport_scrollbar_gap
        (jamais un padding-right QSS sur une QScrollArea nue — rétrécit tout
        le bloc viewport+scrollbar au lieu de créer l'espace attendu entre
        contenu et scrollbar, voir l'historique documenté dans CLAUDE.md),
        AlwaysOn + désactivée/grisée quand rien à défiler (pas AsNeeded :
        évite tout décalage horizontal du contenu selon qu'il déborde ou
        non)."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        scroll_area.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll_area.setWidget(body)
        scroll_area.viewport().setStyleSheet("background: transparent;")
        apply_viewport_scrollbar_gap(scroll_area)
        vbar = scroll_area.verticalScrollBar()
        style_scrollbar_directly(vbar)
        vbar.setEnabled(vbar.maximum() > vbar.minimum())
        vbar.rangeChanged.connect(lambda lo, hi: vbar.setEnabled(hi > lo))
        return scroll_area

    def _build_general_section(self) -> QFrame:
        section = QFrame()
        section.setProperty("class", "card")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        title = QLabel(t("page.settings.section_general"))
        title.setStyleSheet("font-size: 15px; font-weight: 700; color: #E7E9EE; padding-bottom: 3px;")
        layout.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(10)
        label = QLabel(t("page.settings.language"))
        label.setStyleSheet(f"font-size: 13px; color: {STATUS_NEUTRAL};")
        row.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)
        # Stretch AVANT le contrôle (pas après) : pousse le contrôle contre
        # le bord droit de la section plutôt que de le laisser collé au
        # libellé — c'est ce qui garantit que tous les contrôles de settings
        # (ce switch, le toggle "Toujours au premier plan", le bouton "Voir
        # les logs") s'alignent sur la même colonne verticale, quelle que
        # soit la longueur de leur libellé respectif.
        row.addStretch(1)

        self.language_switch = SegmentedToggle(_LANGUAGES, get_language())
        self.language_switch.valueChanged.connect(self._on_language_changed)
        row.addWidget(self.language_switch, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(row)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        top_label = QLabel(t("page.settings.always_on_top"))
        top_label.setStyleSheet(f"font-size: 13px; color: {STATUS_NEUTRAL};")
        top_row.addWidget(top_label, 0, Qt.AlignmentFlag.AlignVCenter)
        top_row.addStretch(1)

        self.always_on_top_toggle = ToggleSwitch(checked=bool(config.get("always_on_top", False)))
        self.always_on_top_toggle.toggled.connect(self._on_always_on_top_toggled)
        top_row.addWidget(self.always_on_top_toggle, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(top_row)

        return section

    def _build_security_section(self) -> QFrame:
        # Même pattern que _build_general_section ci-dessus : libellé à
        # gauche, UN SEUL contrôle aligné à droite (stretch avant le
        # contrôle) — "Ouvrir le dossier des logs" a été déplacé dans la
        # fenêtre "Voir les logs" elle-même (action secondaire à côté de
        # "Fermer", voir _SecurityLogDialog) plutôt que de rester un
        # deuxième bouton de même poids ici. Même carte (classe "card",
        # 14px, mêmes marges internes 16px) que "Général" pour que les
        # deux sections se lisent comme deux blocs visuellement équivalents.
        section = QFrame()
        section.setProperty("class", "card")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        title = QLabel(t("page.settings.section_security"))
        title.setStyleSheet("font-size: 15px; font-weight: 700; color: #E7E9EE; padding-bottom: 3px;")
        layout.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(10)
        label = QLabel(t("page.settings.security_log_row_label"))
        label.setStyleSheet(f"font-size: 13px; color: {STATUS_NEUTRAL};")
        row.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)

        self.view_logs_btn = AnimatedButton(t("page.settings.view_logs_btn"), variant="neutral")
        self.view_logs_btn.clicked.connect(self._on_view_logs_clicked)
        row.addWidget(self.view_logs_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(row)

        return section

    def _build_support_section(self) -> QFrame:
        # Même carte (classe "card", 14px, marges internes 16px) que
        # "Général"/"Sécurité" — un seul bloc : texte + bouton-lien vers le
        # formulaire de signalement GitHub, jamais un lien texte souligné
        # inline (cohérent avec AnimatedButton déjà utilisé partout ailleurs
        # dans l'app pour une action cliquable). Placée AVANT "Communauté" :
        # signaler un problème est l'action la plus "utilitaire", à côté de
        # Général/Sécurité, plutôt que noyée avec les réseaux sociaux.
        section = QFrame()
        section.setProperty("class", "card")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        title = QLabel(t("page.settings.section_support"))
        title.setStyleSheet("font-size: 15px; font-weight: 700; color: #E7E9EE; padding-bottom: 3px;")
        layout.addWidget(title)

        # Texte + bouton sur la MÊME ligne (comme Général/Sécurité), pas
        # empilés : le label prend le stretch (1) — pas un addStretch(1) à
        # part, voir Général/Sécurité — pour qu'il se comprime/s'enroule
        # (setWordWrap) dans l'espace restant à gauche du bouton plutôt que
        # de pousser le bouton hors du rectangle.
        row = QHBoxLayout()
        row.setSpacing(10)
        support_label = QLabel(t("page.settings.support_text"))
        support_label.setWordWrap(True)
        support_label.setStyleSheet(f"font-size: 13px; color: {STATUS_NEUTRAL};")
        row.addWidget(support_label, 1, Qt.AlignmentFlag.AlignVCenter)

        self.github_issue_btn = AnimatedButton(t("page.settings.github_issue_btn"), variant="neutral")
        self.github_issue_btn.clicked.connect(lambda: _open_url(_GITHUB_NEW_ISSUE_URL))
        row.addWidget(self.github_issue_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(row)

        return section

    def _build_community_section(self) -> QFrame:
        # Même carte (classe "card", 14px, marges internes 16px) que les
        # autres sections — un seul bloc désormais (Discord/TikTok, le
        # signalement GitHub a sa propre carte "Support" juste au-dessus,
        # voir _build_support_section).
        section = QFrame()
        section.setProperty("class", "card")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        title = QLabel(t("page.settings.section_community"))
        title.setStyleSheet("font-size: 15px; font-weight: 700; color: #E7E9EE; padding-bottom: 3px;")
        layout.addWidget(title)

        # Même principe que Support ci-dessus : texte + les deux boutons sur
        # UNE SEULE ligne, le label portant le stretch pour s'enrouler dans
        # l'espace restant à gauche des boutons.
        row = QHBoxLayout()
        row.setSpacing(10)
        community_label = QLabel(t("page.settings.community_text"))
        community_label.setWordWrap(True)
        community_label.setStyleSheet(f"font-size: 13px; color: {STATUS_NEUTRAL};")
        row.addWidget(community_label, 1, Qt.AlignmentFlag.AlignVCenter)

        self.discord_btn = AnimatedButton(t("page.settings.discord_btn"), variant="neutral")
        self.discord_btn.clicked.connect(lambda: _open_url(_DISCORD_URL))
        row.addWidget(self.discord_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self.tiktok_btn = AnimatedButton(t("page.settings.tiktok_btn"), variant="neutral")
        self.tiktok_btn.clicked.connect(lambda: _open_url(_TIKTOK_URL))
        row.addWidget(self.tiktok_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(row)

        return section

    def _build_devnotes_section(self) -> QFrame:
        # Même pattern que _build_security_section : libellé à gauche, UN
        # SEUL contrôle aligné à droite (stretch avant le contrôle) — ici
        # la version actuelle en texte (pas éditable) suivie du bouton "Voir
        # le changelog". La version affichée vient TOUJOURS de
        # core.changelog.current_version() (l'entrée la plus récente de
        # CHANGELOG.json) — jamais une chaîne à dupliquer/resynchroniser ici.
        section = QFrame()
        section.setProperty("class", "card")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        title = QLabel(t("page.settings.section_devnotes"))
        title.setStyleSheet("font-size: 15px; font-weight: 700; color: #E7E9EE; padding-bottom: 3px;")
        layout.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(10)
        label = QLabel(t("page.settings.current_version_label").format(version=current_version()))
        label.setStyleSheet(f"font-size: 13px; color: {STATUS_NEUTRAL};")
        row.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)

        self.changelog_btn = AnimatedButton(t("page.settings.changelog_btn"), variant="neutral")
        self.changelog_btn.clicked.connect(self._on_changelog_clicked)
        row.addWidget(self.changelog_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(row)

        return section

    def _on_changelog_clicked(self) -> None:
        # Reconstruite à chaque clic (pas d'instance persistante), même
        # principe que _on_view_logs_clicked : relit CHANGELOG.json à chaque
        # ouverture plutôt que de mettre en cache un contenu qui ne change
        # de toute façon jamais en cours de session, mais reste cohérent
        # avec le reste de la page.
        _ChangelogDialog(self).exec()

    def _on_view_logs_clicked(self) -> None:
        # Reconstruite à chaque clic (pas d'instance persistante) : la
        # liste doit refléter les toutes dernières actions journalisées,
        # même si une action sensible vient de se produire entre deux
        # ouvertures de cette popup.
        _SecurityLogDialog(self).exec()

    def _on_language_changed(self, code: str) -> None:
        if code == get_language():
            return
        set_language(code)
        config.set("language", code)
        self.language_changed.emit(code)

    def _on_always_on_top_toggled(self, checked: bool) -> None:
        config.set("always_on_top", checked)
        self.always_on_top_changed.emit(checked)
