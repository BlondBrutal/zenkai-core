"""
Zenkai Core — point d'entrée de l'application.
Affiche un splash screen pendant l'initialisation, puis la fenêtre principale.
"""
import os
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QIcon, QPalette, QColor
from PyQt6.QtWidgets import QApplication, QStyleFactory

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.logging_setup import setup_logging
from core.config import config
from core.i18n import set_language


def main() -> int:
    setup_logging()
    set_language(config.get("language", "fr"))

    if sys.platform == "win32":
        # Sans ça, la barre des tâches regroupe l'app sous l'icône de python.exe
        # en mode développement (python main.py) au lieu de l'icône de Zenkai Core.
        import ctypes
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ZenkaiCore.App")
        except OSError:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("Zenkai Core")
    # Le style natif Windows n'honore pas toujours le QSS : Fusion respecte
    # fidèlement toute la feuille de style. RoundedScrollBarStyle l'enrobe
    # pour peindre les scrollbars nous-mêmes (voir ui/scrollbar_style.py).
    from ui.scrollbar_style import RoundedScrollBarStyle

    app.setStyle(RoundedScrollBarStyle(QStyleFactory.create("Fusion")))

    # QPalette.Highlight/HighlightedText (pas seulement le QSS) : ce sont ces
    # rôles que Qt utilise comme couche de FOND pour toute sélection (texte
    # ET lignes de tableau) avant même d'appliquer nos règles QSS par-dessus.
    # Nos règles comme "QTableWidget::item:selected { background-color:
    # rgba(23, 184, 151, 40); ... }" sont volontairement semi-transparentes
    # (léger lavis turquoise) — sans ce correctif, elles se superposaient au
    # bleu système par défaut de la palette au lieu d'un fond neutre, ce qui
    # donnait un bleu-turquoise mêlé au lieu du turquoise pur (vérifié par
    # échantillonnage de pixels : le bleu restait dominant sous le lavis à
    # faible opacité). Posé sur la palette de l'app entière (pas juste sur le
    # tableau) : Highlight/HighlightedText gouvernent la sélection dans tous
    # les widgets standards (champs de texte, listes, tableaux, etc.), et rien
    # dans ce thème ne doit jamais afficher le bleu de sélection Qt par défaut.
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#17B897"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#0E1C19"))
    palette.setColor(QPalette.ColorGroup.Inactive, QPalette.ColorRole.Highlight, QColor("#17B897"))
    palette.setColor(QPalette.ColorGroup.Inactive, QPalette.ColorRole.HighlightedText, QColor("#0E1C19"))
    app.setPalette(palette)

    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "logo", "logo.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    theme_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "styles", "theme.qss")
    if os.path.exists(theme_path):
        with open(theme_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())

    # Import différé (après QApplication) car certains widgets ont besoin
    # d'un contexte Qt déjà initialisé.
    from ui.splash import build_splash
    from ui.main_window import MainWindow

    splash = build_splash()
    splash.show()
    app.processEvents()

    window = MainWindow()

    def _show_main_window():
        window.show()
        splash.finish(window)

    QTimer.singleShot(900, _show_main_window)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
