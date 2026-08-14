"""
Curseur "main pointée" (PointingHandCursor) garanti sur TOUS les boutons de
l'app, popups comprises — sans avoir à poser .setCursor(...) sur chaque site
de construction d'un QPushButton (AnimatedButton le fait déjà lui-même, mais
les nombreux QPushButton bruts stylés en QSS — "secondaryButton",
"primaryButton", boutons de dialogues custom, etc. — ne l'avaient pas tous,
plusieurs oubliés au fil des ajouts). Qt Style Sheets ne permet pas de poser
un curseur via QSS (pas de propriété "cursor" supportée) — un filtre
d'évènements central, installé une seule fois sur QApplication, est le seul
moyen fiable de couvrir TOUT bouton présent ET futur, y compris ceux créés
dans des QDialog éphémères (popups) qu'on ne repasse jamais en revue
individuellement.
"""
from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import QAbstractButton, QApplication


class _ButtonCursorPolish(QObject):
    def eventFilter(self, watched, event) -> bool:
        # Polish : émis une seule fois par widget, une fois sa feuille de
        # style/ses propriétés Qt entièrement appliquées — le bon moment pour
        # poser un curseur par défaut sans risquer d'être écrasé ensuite par
        # le style. ArrowCursor (la valeur par défaut d'un widget neuf) évite
        # d'écraser un curseur déjà posé explicitement ailleurs (aucun bouton
        # de cette app n'en a besoin d'un différent aujourd'hui, mais reste
        # défensif si un cas particulier apparaît).
        #
        # ArrowCursor, PAS "ArrowShape" (une erreur d'un tour précédent :
        # cette valeur n'existe pas dans Qt.CursorShape — AttributeError à
        # chaque appel de cette méthode, donc au tout premier bouton
        # construit dans l'app, avant même l'affichage de la fenêtre
        # principale). Une exception Python levée DANS un eventFilter appelé
        # depuis le C++ de Qt n'est PAS catchable par un try/except normal
        # côté appelant (main.py) — vérifié : ni stdout ni stderr n'affichent
        # quoi que ce soit, PyQt6 abandonne le process directement (abort
        # natif, aucune trace nulle part, aucun code de sortie exploitable),
        # ce qui expliquait le plantage totalement silencieux (splash affiché
        # puis retour direct au terminal) constaté au lancement.
        if event.type() == QEvent.Type.Polish and isinstance(watched, QAbstractButton):
            if watched.cursor().shape() == Qt.CursorShape.ArrowCursor:
                watched.setCursor(Qt.CursorShape.PointingHandCursor)
        return super().eventFilter(watched, event)


def install_button_cursor_polish(app: QApplication) -> None:
    """À appeler une seule fois, juste après la création de QApplication
    (voir main.py) — la référence au filtre doit être gardée en vie (posée
    comme attribut de l'app elle-même) sinon Python la détruit aussitôt et
    Qt cesse silencieusement de l'appeler."""
    polish_filter = _ButtonCursorPolish(app)
    app.installEventFilter(polish_filter)
    app._button_cursor_polish = polish_filter
