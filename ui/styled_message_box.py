"""
Boîte de dialogue d'information/avertissement stylée, cohérente avec le
thème sombre de l'app — remplace la QMessageBox.information/warning par
défaut de Windows (fond blanc, icône bleue ronde "i") qui détonnait
complètement avec le reste de l'interface. Icône peinte à la main (cercle +
lettre), même principe que InfoBadge/TrashIconButton : jamais d'emoji dans
ce projet.
"""
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from core.i18n import t
from ui.status_colors import STATUS_CRITICAL, STATUS_OK, STATUS_WARNING

_BACKGROUND = "#1A1A1F"
_ICON_SIZE = 22


class _StatusIcon(QWidget):
    """Cercle + lettre ("i" ou "!"), coloré selon la variante — remplace
    l'icône bleue ronde par défaut de Windows par quelque chose de cohérent
    avec le reste de l'app (voir InfoBadge, même technique de dessin)."""

    def __init__(self, color: QColor, glyph: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(_ICON_SIZE, _ICON_SIZE)
        self._color = color
        self._glyph = glyph

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        margin = max(1.0, self.width() * 0.06)
        circle_rect = self.rect().toRectF().adjusted(margin, margin, -margin, -margin)

        painter.setPen(QPen(self._color, max(1.0, self.width() * 0.08)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(circle_rect)

        painter.setPen(self._color)
        font = painter.font()
        font.setPixelSize(max(9, round(self.width() * 0.55)))
        font.setWeight(font.Weight.Bold)
        painter.setFont(font)
        painter.drawText(circle_rect, Qt.AlignmentFlag.AlignCenter, self._glyph)


class StyledMessageBox(QDialog):
    def __init__(self, title: str, text: str, variant: str = "info", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(360)
        # Fond aligné sur le reste de l'app : un QDialog nu utilise la
        # palette Qt par défaut (fond blanc), pas le style
        # QMainWindow/#centralWidget de theme.qss.
        self.setStyleSheet(f"background-color: {_BACKGROUND};")

        accent = STATUS_CRITICAL if variant == "warning" else STATUS_OK
        glyph = "!" if variant == "warning" else "i"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        header_row.addWidget(_StatusIcon(QColor(accent), glyph))
        title_label = QLabel(title)
        title_label.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {accent}; padding-bottom: 3px;")
        header_row.addWidget(title_label)
        header_row.addStretch(1)
        layout.addLayout(header_row)

        message_label = QLabel(text)
        message_label.setWordWrap(True)
        message_label.setStyleSheet("font-size: 12.5px; color: #E7E9EE;")
        layout.addWidget(message_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        ok_btn = QPushButton(t("dialog.ok_btn"))
        ok_btn.setProperty("class", "secondaryButton")
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn.clicked.connect(self.accept)
        button_row.addWidget(ok_btn)
        layout.addLayout(button_row)


def show_info(parent, title: str, text: str) -> None:
    StyledMessageBox(title, text, variant="info", parent=parent).exec()


def show_warning(parent, title: str, text: str) -> None:
    StyledMessageBox(title, text, variant="warning", parent=parent).exec()


class _ConfirmDialog(QDialog):
    """Popup Confirmer/Annuler pour les actions "sensibles" (voir
    core/security_log.py::SENSITIVE_CATEGORIES) déclenchées par un clic
    explicite (toggle, bouton "Corriger"/"Optimiser"...) — jamais utilisée
    sur le chemin de lancement de Roblox (bouton "Lancer Roblox" ou
    protocole roblox-player://), qui doit toujours rester sans friction.

    Accent ambre (STATUS_WARNING, "avertissement") plutôt que rouge
    (STATUS_CRITICAL, réservé à show_warning() pour signaler un échec déjà
    survenu) : cette popup prévient AVANT l'action, elle ne rapporte pas
    une erreur."""

    def __init__(self, title: str, text: str, confirm_label: str, cancel_label: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(380)
        self.setStyleSheet(f"background-color: {_BACKGROUND};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        header_row.addWidget(_StatusIcon(QColor(STATUS_WARNING), "!"))
        title_label = QLabel(title)
        title_label.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {STATUS_WARNING}; padding-bottom: 3px;")
        header_row.addWidget(title_label)
        header_row.addStretch(1)
        layout.addLayout(header_row)

        message_label = QLabel(text)
        message_label.setWordWrap(True)
        message_label.setStyleSheet("font-size: 12.5px; color: #E7E9EE;")
        layout.addWidget(message_label)

        button_row = QHBoxLayout()
        # setSpacing(10) : même écart que les autres paires de boutons de
        # l'app (ex: Enregistrer/Réinitialiser, page_custom_script.py) — un
        # QHBoxLayout nu sans setSpacing() explicite retombe sur l'espacement
        # par défaut de Qt (~6px), plus resserré que la convention établie.
        button_row.setSpacing(10)
        button_row.addStretch(1)
        # Confirmer/Activer en premier (donc à gauche) : même ordre que les
        # autres paires de boutons de l'app (action principale à gauche,
        # ex: Enregistrer avant Réinitialiser) — Annuler ensuite (à droite).
        confirm_btn = QPushButton(confirm_label)
        confirm_btn.setProperty("class", "secondaryButton")
        confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        confirm_btn.clicked.connect(self.accept)
        button_row.addWidget(confirm_btn)
        cancel_btn = QPushButton(cancel_label)
        cancel_btn.setProperty("class", "secondaryButton")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(cancel_btn)
        layout.addLayout(button_row)


def show_confirm(parent, title: str, text: str, confirm_label: str, cancel_label: str | None = None) -> bool:
    """Affiche un avertissement Confirmer/Annuler et attend la réponse de
    l'utilisateur (modal). Renvoie True seulement si "Confirmer" a été
    cliqué — fermer la fenêtre ou cliquer "Annuler" renvoie False, jamais
    d'exception dans un cas comme dans l'autre."""
    dialog = _ConfirmDialog(
        title, text, confirm_label, cancel_label or t("dialog.cancel_btn"), parent=parent,
    )
    return dialog.exec() == QDialog.DialogCode.Accepted


class _CheckIndicator(QWidget):
    """Carré de case à cocher peint à la main (pas QCheckBox::indicator en
    QSS) : Qt masque le glyphe de coche natif dès qu'on stylise
    QCheckBox::indicator sans fournir de bitmap "image:" — un simple
    background-color plein au clic ne se distingue pas visuellement d'un
    carré décoché sans coche. Même principe que AnimatedButton (voir sa
    docstring) : peindre nous-mêmes élimine cette limitation de rendu QSS."""

    _SIZE = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self._SIZE, self._SIZE)
        self._checked = False

    def setChecked(self, checked: bool) -> None:
        self._checked = checked
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(0.75, 0.75, self._SIZE - 1.5, self._SIZE - 1.5)
        if self._checked:
            painter.setBrush(QColor(STATUS_OK))
            painter.setPen(QPen(QColor(STATUS_OK), 1.2))
        else:
            painter.setBrush(QColor("#202027"))
            painter.setPen(QPen(QColor("#33333C"), 1.2))
        painter.drawRoundedRect(rect, 3, 3)

        if self._checked:
            # Coche peinte en trait sombre (même contraste que le texte
            # foncé d'AnimatedButton variant="primary" sur fond turquoise).
            pen = QPen(QColor("#0E1C19"), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawLine(QPointF(3.3, 7.3), QPointF(6.0, 10.2))
            painter.drawLine(QPointF(6.0, 10.2), QPointF(10.7, 4.0))


class _CheckBoxRow(QWidget):
    """Ligne "case à cocher + texte" cliquable dans son ensemble (pas
    seulement le petit carré) — plus facile à cocher, cohérent avec
    _CheckIndicator peint à la main plutôt qu'un QCheckBox stylé en QSS."""

    toggled = pyqtSignal(bool)

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._checked = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # AlignVCenter (pas AlignTop) : le texte de cette ligne tient
        # toujours sur une seule ligne (voir dialog.high_risk_ack_checkbox),
        # donc centrer verticalement la case sur la hauteur du QLabel
        # l'aligne réellement sur SA ligne de texte — AlignTop la calait sur
        # le haut du layout, au-dessus du centre optique du texte (vérifié
        # par capture d'écran réelle).
        self._indicator = _CheckIndicator()
        layout.addWidget(self._indicator, 0, Qt.AlignmentFlag.AlignVCenter)

        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet("font-size: 12px; color: #E7E9EE;")
        layout.addWidget(label, 1)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        self._checked = checked
        self._indicator.setChecked(checked)

    def mousePressEvent(self, event) -> None:
        self.setChecked(not self._checked)
        self.toggled.emit(self._checked)
        super().mousePressEvent(event)


class _HighRiskConfirmDialog(QDialog):
    """Variante DISTINCTE de _ConfirmDialog pour un verdict classé "severe"
    (voir features/custom_script/heuristics.py) : accent rouge
    (STATUS_CRITICAL, pas ambre) ET une case à cocher obligatoire qui doit
    être cochée avant que "Confirmer" ne s'active — rend un clic accidentel
    structurellement impossible, contrairement à _ConfirmDialog (deux
    boutons symétriques, n'importe lequel cliquable immédiatement)."""

    def __init__(self, title: str, text: str, confirm_label: str, cancel_label: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(400)
        self.setStyleSheet(f"background-color: {_BACKGROUND};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        header_row.addWidget(_StatusIcon(QColor(STATUS_CRITICAL), "!"))
        title_label = QLabel(title)
        title_label.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {STATUS_CRITICAL}; padding-bottom: 3px;")
        header_row.addWidget(title_label)
        header_row.addStretch(1)
        layout.addLayout(header_row)

        message_label = QLabel(text)
        message_label.setWordWrap(True)
        message_label.setStyleSheet("font-size: 12.5px; color: #E7E9EE;")
        layout.addWidget(message_label)

        self.ack_checkbox = _CheckBoxRow(t("dialog.high_risk_ack_checkbox"))
        self.ack_checkbox.toggled.connect(self._update_confirm_enabled)
        layout.addWidget(self.ack_checkbox)

        button_row = QHBoxLayout()
        # Même écart (10px) et même ordre (confirmer à gauche, annuler à
        # droite) que _ConfirmDialog ci-dessus — voir son commentaire.
        button_row.setSpacing(10)
        button_row.addStretch(1)

        self.confirm_btn = QPushButton(confirm_label)
        self.confirm_btn.setProperty("class", "secondaryButton")
        self.confirm_btn.setObjectName("highRiskConfirmBtn")
        self.confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_btn.setEnabled(False)
        # Contour gris #33333C identique aux autres boutons (variante
        # "neutral" d'AnimatedButton, voir CLAUDE.md) ET texte en couleur
        # d'accent standard de l'app (STATUS_OK turquoise, pas rouge) une
        # fois activé — ce bouton confirme une action que l'utilisateur
        # vient d'accepter explicitement (case cochée), plus un signal de
        # danger à ce stade.
        self.confirm_btn.setStyleSheet(
            "QPushButton#highRiskConfirmBtn { border: 1px solid #33333C; }"
            f"QPushButton#highRiskConfirmBtn:enabled {{ color: {STATUS_OK}; }}"
            "QPushButton#highRiskConfirmBtn:disabled { color: #4A4E56; }"
        )
        self.confirm_btn.clicked.connect(self.accept)
        button_row.addWidget(self.confirm_btn)
        cancel_btn = QPushButton(cancel_label)
        cancel_btn.setProperty("class", "secondaryButton")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(cancel_btn)
        layout.addLayout(button_row)

    def _update_confirm_enabled(self, _state) -> None:
        self.confirm_btn.setEnabled(self.ack_checkbox.isChecked())


def show_high_risk_confirm(parent, title: str, text: str, confirm_label: str, cancel_label: str | None = None) -> bool:
    """Comme show_confirm(), mais réservée aux actions classées "severe"
    (voir features/custom_script/heuristics.py) : exige en plus une case à
    cocher explicite avant de pouvoir confirmer. Renvoie True seulement si
    la case a été cochée ET "Confirmer" cliqué."""
    dialog = _HighRiskConfirmDialog(
        title, text, confirm_label, cancel_label or t("dialog.cancel_btn"), parent=parent,
    )
    return dialog.exec() == QDialog.DialogCode.Accepted


class _TextPromptDialog(QDialog):
    """Demande une simple saisie texte (ex: nom d'un preset Fast Flags à
    enregistrer) — remplace QInputDialog.getText(), une boîte de dialogue Qt
    générique (fond blanc, boutons non stylés) qui détonnait complètement
    avec le reste de l'app. Même famille que _ConfirmDialog/
    _HighRiskConfirmDialog ci-dessus (fond sombre explicite, icône peinte à
    la main, boutons "secondaryButton") — PAS de fenêtre sans bordure : comme
    tous les autres QDialog custom de ce fichier, la barre de titre reste
    celle, native, de l'OS (elle hérite déjà de l'icône ZK posée sur
    QApplication dans main.py, voir app.setWindowIcon), seul le CONTENU est
    stylé."""

    def __init__(self, title: str, label_text: str, placeholder: str, confirm_label: str, cancel_label: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(380)
        self.setStyleSheet(f"background-color: {_BACKGROUND};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        header_row.addWidget(_StatusIcon(QColor(STATUS_OK), "i"))
        title_label = QLabel(title)
        title_label.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {STATUS_OK}; padding-bottom: 3px;")
        header_row.addWidget(title_label)
        header_row.addStretch(1)
        layout.addLayout(header_row)

        label = QLabel(label_text)
        label.setWordWrap(True)
        label.setStyleSheet("font-size: 12.5px; color: #E7E9EE;")
        layout.addWidget(label)

        self.input = QLineEdit()
        self.input.setPlaceholderText(placeholder)
        self.input.textChanged.connect(self._update_confirm_enabled)
        layout.addWidget(self.input)

        button_row = QHBoxLayout()
        # Même écart (10px) et même ordre (confirmer à gauche, annuler à
        # droite) que _ConfirmDialog plus haut — voir son commentaire.
        button_row.setSpacing(10)
        button_row.addStretch(1)

        self.confirm_btn = QPushButton(confirm_label)
        self.confirm_btn.setProperty("class", "secondaryButton")
        self.confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.clicked.connect(self.accept)
        button_row.addWidget(self.confirm_btn)
        cancel_btn = QPushButton(cancel_label)
        cancel_btn.setProperty("class", "secondaryButton")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(cancel_btn)
        layout.addLayout(button_row)

        self.input.setFocus()

    def _update_confirm_enabled(self, text: str) -> None:
        self.confirm_btn.setEnabled(bool(text.strip()))

    def text(self) -> str:
        return self.input.text().strip()


def show_text_prompt(
    parent, title: str, label_text: str, confirm_label: str,
    placeholder: str = "", cancel_label: str | None = None,
) -> str | None:
    """Affiche une popup de saisie texte stylée et attend la réponse
    (modal). Renvoie le texte saisi (déjà .strip()) si "Confirmer" a été
    cliqué, None si la fenêtre a été fermée ou "Annuler" cliqué — jamais une
    chaîne vide (le bouton de confirmation reste désactivé tant que le champ
    est vide)."""
    dialog = _TextPromptDialog(
        title, label_text, placeholder, confirm_label, cancel_label or t("dialog.cancel_btn"), parent=parent,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.text()
