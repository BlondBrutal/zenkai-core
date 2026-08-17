"""
Fenêtre principale : assemble la sidebar et la zone de contenu (QStackedWidget).
"""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QStackedWidget

from core.config import config
from core.i18n import t
from ui.sidebar import Sidebar
from ui.tray import build_tray_icon, retranslate_tray_icon
from ui.pages.page_license import LicensePage
from ui.pages.page_macro import MacroPage
from ui.pages.page_cursor import CursorPage
from ui.pages.page_performance import PerformancePage
from ui.pages.page_fastflags import FastFlagsPage
from ui.pages.page_settings import SettingsPage
from ui.pages.page_custom_script import CustomScriptPage
from ui.pages.page_fleasion import FleasionPage

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(t("app_name"))
        # Largeur réduite de 13px : la colonne Bibliothèque de la page Macro
        # est ancrée au bord droit (largeur fixe + colonne de gauche extensible),
        # donc réduire la largeur de la fenêtre la rapproche d'autant des
        # onglets, sans laisser de vide en trop à droite (mesuré : l'écart
        # d'origine était de 44px, on vise -30% soit ~13px de moins).
        #
        # setFixedSize (pas resize) : toute la mise en page est pensée pour
        # cette taille exacte (colonnes/cadres à largeur fixe un peu partout,
        # voir macro_simple_tab.py/macro_pixel_tab.py) — maximiser ou
        # redimensionner la fenêtre laisserait juste du vide autour, sans que
        # rien ne se réadapte. minimumSize == maximumSize désactive
        # automatiquement le bouton natif "Agrandir"/"Maximiser" (Windows le
        # grise tout seul dès qu'une fenêtre n'a plus de marge de
        # redimensionnement) et bloque aussi le glissement des bords.
        self.setFixedSize(987, 640)

        # Restaure le réglage "Toujours au premier plan" (page Paramètres) :
        # posé ici, avant le tout premier show() (voir main.py), pas besoin
        # de re-show() pour l'appliquer contrairement à _set_always_on_top
        # (appelé lui APRÈS que la fenêtre soit déjà affichée).
        if bool(config.get("always_on_top", False)):
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        icon_path = os.path.join(ASSETS_DIR, "logo", "logo.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.tray_icon = build_tray_icon(self)  # référence gardée : sinon Qt le détruit aussitôt

        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.sidebar = Sidebar()
        root_layout.addWidget(self.sidebar)

        content_wrapper = QWidget()
        content_wrapper.setObjectName("contentArea")
        content_layout = QHBoxLayout(content_wrapper)
        content_layout.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack)
        root_layout.addWidget(content_wrapper, 1)

        self.pages: dict[str, QWidget] = {}
        self._page_index: dict[str, int] = {}
        self._build_pages()

        self.sidebar.page_requested.connect(self.show_page)
        self.show_page("license")

    def _build_pages(self) -> None:
        """Construit (ou reconstruit, cf. reload_language) l'ensemble des
        pages et branche leurs signaux inter-pages."""
        self.pages.update({
            "license": LicensePage(),
            "performance": PerformancePage(),
            "macro": MacroPage(),
            "fastflags": FastFlagsPage(),
            "custom_script": CustomScriptPage(),
            "fleasion": FleasionPage(),
            "cursor": CursorPage(),
            "settings": SettingsPage(),
        })
        for key, widget in self.pages.items():
            self._page_index[key] = self.stack.addWidget(widget)

        # Verrouillé par défaut tant que la licence n'a pas été vérifiée.
        self.sidebar.set_locked(True)
        license_page = self.pages["license"]
        license_page.license_validated.connect(lambda valid: self.sidebar.set_locked(not valid))
        license_page.run_startup_check()

        # La page Performance recommande un preset Fast Flags (Partie 2.1) sans
        # dupliquer la logique de sélection : elle passe juste la recommandation
        # à la page Fast Flags, prête à afficher dès que l'utilisateur y va lui-
        # même (le clic sur "Optimiser pour Roblox" affiche déjà un résumé sur
        # place, pas de navigation forcée qui le ferait disparaître aussitôt).
        performance_page = self.pages["performance"]
        fastflags_page = self.pages["fastflags"]
        performance_page.boost_requested.connect(fastflags_page.show_recommendation)

        self.pages["settings"].language_changed.connect(lambda _code: self.reload_language())
        self.pages["settings"].always_on_top_changed.connect(self._set_always_on_top)

    def show_page(self, key: str) -> None:
        index = self._page_index.get(key)
        if index is not None:
            self.stack.setCurrentIndex(index)
            self.sidebar.select(key)

    def _set_always_on_top(self, enabled: bool) -> None:
        # setWindowFlags masque la fenêtre (comportement Qt) : contrairement
        # au réglage initial dans __init__ (posé avant le tout premier
        # show()), un re-show() est ici indispensable pour que le nouveau
        # flag s'applique réellement.
        flags = self.windowFlags()
        if enabled:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()

    def reload_language(self) -> None:
        """Applique le changement de langue à toute l'UI sans fermer/relancer
        le processus : chaque page ne traduit son texte qu'à sa construction
        (t() appelé une fois), donc on les reconstruit à neuf plutôt que de
        retraduire chaque widget un par un (ce qui demanderait un mécanisme
        de retranslate() dédié sur absolument tout, bien plus lourd).

        Cause réelle d'un plantage systématique ici, diagnostiquée via une
        trace (logger.exception temporaire + traceback.print_stack() dans
        PerformancePage._start_live_thread) : QStackedWidget.removeWidget()
        sur le widget COURANT fait automatiquement basculer currentIndex()
        sur le widget suivant, ce qui déclenche un vrai showEvent sur lui —
        dans cette boucle, "license" (courant au départ) est retiré en
        premier, ce qui promeut PerformancePage (2e page ajoutée) comme
        nouveau widget courant et déclenche SON showEvent, qui démarre
        LiveMonitorThread (le monitoring en direct est activé par défaut,
        voir config "performance_live_monitoring_enabled" dans
        page_performance.py). Ce thread frais tourne encore quand
        PerformancePage elle-même est ensuite hide()/removeWidget()/
        deleteLater() plus loin dans la MÊME boucle — hideEvent ne l'arrête
        PAS (volontaire : il doit continuer pendant qu'on quitte la page
        pour aller jouer, voir _stop_live_thread_if_unneeded) — et Qt
        plante avec un qFatal("QThread: Destroyed while thread is still
        running") dès que la suppression différée du widget est traitée :
        aucune exception Python, juste un arrêt natif immédiat du process
        (Qt6Core.dll, confirmé via le journal d'erreurs applicatives
        Windows), ce qui explique pourquoi l'app semblait "se fermer" sans
        aucune trace exploitable.

        Double correctif :
        1. Un widget PLACEHOLDER jetable devient le widget "courant" avant
           la boucle (setCurrentIndex(-1) ne suffit PAS : vérifié, Qt
           re-promeut quand même un widget "courant" dès le premier
           removeWidget() qui suit, -1 n'étant pas traité comme "aucun
           widget" par QStackedWidget contrairement à QStackedLayout) :
           aucune des anciennes pages n'est donc plus jamais "courante"
           pendant leur suppression, donc plus aucune promotion implicite ni
           showEvent parasite entre elles.
        2. shutdown() (si la page le définit) appelé avant hide(), pour
           arrêter de façon SYNCHRONE et INCONDITIONNELLE tout thread/timer
           qui — par conception — pourrait survivre à un simple hide() (ex:
           monitoring/overlay Performance, licence en cours de vérification,
           macros actives) : la reconstruction détruit réellement ces pages,
           contrairement à une simple navigation, où les laisser tourner
           est le comportement voulu."""
        current_key = next((k for k, i in self._page_index.items() if i == self.stack.currentIndex()), "license")

        # Voir point 1 ci-dessus.
        placeholder = QWidget()
        self.stack.addWidget(placeholder)
        self.stack.setCurrentWidget(placeholder)

        for widget in list(self.pages.values()):
            # Voir point 2 ci-dessus.
            shutdown = getattr(widget, "shutdown", None)
            if shutdown is not None:
                shutdown()
            # hide() déclenche hideEvent (best-effort pour tout ce qui n'a
            # pas besoin d'un arrêt inconditionnel, voir shutdown()
            # ci-dessus) avant la destruction.
            widget.hide()
            self.stack.removeWidget(widget)
            widget.deleteLater()
        self.pages.clear()
        self._page_index.clear()

        self.stack.removeWidget(placeholder)
        placeholder.deleteLater()

        self.setWindowTitle(t("app_name"))
        self.sidebar.retranslate()
        retranslate_tray_icon(self.tray_icon)

        self._build_pages()
        self.show_page(current_key)
