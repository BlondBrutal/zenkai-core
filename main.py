"""
Zenkai Core — point d'entrée de l'application.
Affiche un splash screen pendant l'initialisation, puis la fenêtre principale.
"""
import os
import sys
import traceback

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QIcon, QPalette, QColor
from PyQt6.QtWidgets import QApplication, QStyleFactory

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.logging_setup import setup_logging
from core.config import config
from core.i18n import set_language


def main() -> int:
    # DIAGNOSTIC TEMPORAIRE (à retirer une fois le problème d'interception
    # roblox-player:// confirmé/résolu) : log de tout premier niveau, écrit
    # dans un fichier FIXE indépendant du logger normal (setup_logging()
    # n'est même pas encore appelé à ce stade de main()) — sert uniquement à
    # vérifier si Windows invoque ne serait-ce que cette app quand on clique
    # "Jouer" sur roblox.com. Si ce fichier n'apparaît/ne grandit JAMAIS
    # après un tel clic : le problème est entièrement en amont du code
    # Python (Windows n'utilise pas notre gestionnaire du tout — voir le
    # piège "UserChoice" documenté dans features/fastflags/protocol.py),
    # jamais dans launch_roblox() lui-même. try/except autour de l'écriture
    # : ce diagnostic ne doit JAMAIS empêcher un vrai lancement de démarrer,
    # même si le fichier est inaccessible pour une raison quelconque.
    try:
        import datetime
        _debug_log_path = os.path.join(
            os.environ.get("TEMP", os.path.expanduser("~")), "zenkai_invoke_debug.log"
        )
        with open(_debug_log_path, "a", encoding="utf-8") as _f:
            _f.write(f"{datetime.datetime.now().isoformat()} invoked, sys.argv={sys.argv!r}\n")
    except Exception:
        pass

    # Lancement intercepté via le protocole roblox-player:// (voir
    # features/fastflags/protocol.py) : Windows invoque cette app avec l'URI
    # d'origine en argument, à chaque clic sur "Jouer" sur le site Roblox ou
    # un raccourci existant. Doit être vérifié AVANT tout le reste (élévation
    # UAC, QApplication, fenêtre principale) — ce chemin doit être quasi
    # instantané et invisible, pas un rappel UAC à chaque lancement de jeu.
    # "roblox-player:" (juste le préfixe, pas "://") : plus tolérant si
    # jamais l'URI est transmise sans les deux slashs.
    if sys.platform == "win32" and len(sys.argv) > 1 and sys.argv[1].startswith("roblox-player:"):
        setup_logging()
        from features.fastflags.launcher import launch_roblox

        launch_roblox(sys.argv[1:])
        return 0

    if sys.platform == "win32":
        # Élévation UAC classique, redemandée à chaque lancement tant que le
        # process n'est pas déjà admin (voir core/elevation.py — le
        # mécanisme à base de tâche planifiée essayé ici a été reverti après
        # avoir provoqué une boucle d'ouverture/fermeture rapide sur
        # certaines configurations Windows). Si l'utilisateur refuse le
        # prompt, on continue quand même sans droits admin : PresentMon/le
        # correctif SysMain redemanderont alors individuellement.
        from core.elevation import is_admin, relaunch_as_admin

        if not is_admin() and relaunch_as_admin():
            return 0

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

    # Filet de sécurité permanent autour de toute l'initialisation : cause
    # réelle d'un plantage totalement silencieux déjà rencontré ici (splash
    # affiché puis retour direct au terminal, sans la moindre trace, ni
    # stdout ni stderr) — voir ui/button_cursor.py, `Qt.CursorShape.
    # ArrowShape` (une valeur qui n'existe pas) levait un AttributeError à
    # chaque construction de bouton ; une exception Python levée DANS un
    # eventFilter appelé depuis le C++ de Qt n'est PAS catchable par un
    # try/except classique, PyQt6 abandonne directement le process (abort
    # natif, aucune trace nulle part) — corrigé à la racine (ArrowCursor).
    # Ce bloc reste posé en permanence : il ne peut rien contre un futur
    # abort natif du même genre, mais capture au moins toute exception
    # Python RÉELLEMENT catchable pendant l'init (bien plus probable
    # qu'un nouveau bug de cette famille précise) au lieu de la laisser
    # remonter jusqu'à un crash silencieux du même type.
    try:
        # Le style natif Windows n'honore pas toujours le QSS : Fusion
        # respecte fidèlement toute la feuille de style. RoundedScrollBarStyle
        # l'enrobe pour peindre les scrollbars nous-mêmes (voir
        # ui/scrollbar_style.py).
        from ui.scrollbar_style import RoundedScrollBarStyle

        app.setStyle(RoundedScrollBarStyle(QStyleFactory.create("Fusion")))

        # Curseur "main pointée" garanti sur tous les boutons de l'app
        # (popups comprises), y compris ceux créés bien après ce point —
        # voir ui/button_cursor.py pour pourquoi un filtre d'évènements
        # central est le seul moyen fiable de couvrir ça (Qt Style Sheets ne
        # supporte pas de propriété "cursor").
        from ui.button_cursor import install_button_cursor_polish

        install_button_cursor_polish(app)

        # QPalette.Highlight/HighlightedText (pas seulement le QSS) : ce sont
        # ces rôles que Qt utilise comme couche de FOND pour toute sélection
        # (texte ET lignes de tableau) avant même d'appliquer nos règles QSS
        # par-dessus. Nos règles comme "QTableWidget::item:selected {
        # background-color: rgba(23, 184, 151, 40); ... }" sont
        # volontairement semi-transparentes (léger lavis turquoise) — sans ce
        # correctif, elles se superposaient au bleu système par défaut de la
        # palette au lieu d'un fond neutre, ce qui donnait un bleu-turquoise
        # mêlé au lieu du turquoise pur (vérifié par échantillonnage de
        # pixels : le bleu restait dominant sous le lavis à faible opacité).
        # Posé sur la palette de l'app entière (pas juste sur le tableau) :
        # Highlight/HighlightedText gouvernent la sélection dans tous les
        # widgets standards (champs de texte, listes, tableaux, etc.), et
        # rien dans ce thème ne doit jamais afficher le bleu de sélection Qt
        # par défaut.
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
    except Exception:
        traceback.print_exc()
        try:
            import logging
            logging.getLogger("zenkaiontop").exception("Échec fatal pendant l'initialisation de l'app")
        except Exception:
            pass
        return 1

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
