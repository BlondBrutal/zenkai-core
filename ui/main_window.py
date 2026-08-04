"""
Fenêtre principale : assemble la sidebar et la zone de contenu (QStackedWidget).
"""
import os

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QStackedWidget

from core.i18n import t
from ui.sidebar import Sidebar
from ui.tray import build_tray_icon, retranslate_tray_icon
from ui.pages.page_license import LicensePage
from ui.pages.page_macro import MacroPage
from ui.pages.page_cursor import CursorPage
from ui.pages.page_performance import PerformancePage
from ui.pages.page_fastflags import FastFlagsPage
from ui.pages.page_settings import SettingsPage

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
            "cursor": CursorPage(),
            "fastflags": FastFlagsPage(),
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

    def show_page(self, key: str) -> None:
        index = self._page_index.get(key)
        if index is not None:
            self.stack.setCurrentIndex(index)
            self.sidebar.select(key)

    def reload_language(self) -> None:
        """Applique le changement de langue à toute l'UI sans fermer/relancer
        le processus : chaque page ne traduit son texte qu'à sa construction
        (t() appelé une fois), donc on les reconstruit à neuf plutôt que de
        retraduire chaque widget un par un (ce qui demanderait un mécanisme
        de retranslate() dédié sur absolument tout, bien plus lourd)."""
        current_key = next((k for k, i in self._page_index.items() if i == self.stack.currentIndex()), "license")

        for widget in list(self.pages.values()):
            # hide() déclenche hideEvent (ex: PerformancePage y arrête son
            # thread de monitoring en direct) avant la destruction.
            widget.hide()
            self.stack.removeWidget(widget)
            widget.deleteLater()
        self.pages.clear()
        self._page_index.clear()

        self.setWindowTitle(t("app_name"))
        self.sidebar.retranslate()
        retranslate_tray_icon(self.tray_icon)

        self._build_pages()
        self.show_page(current_key)
