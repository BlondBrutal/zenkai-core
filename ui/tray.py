"""
Icône dans la zone de notification (system tray) : reste visible tant que
l'app tourne, clic gauche pour réafficher la fenêtre, clic droit pour le
menu Afficher / Quitter.
"""
import os

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMainWindow, QMenu, QSystemTrayIcon

from core.i18n import t

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")


def build_tray_icon(window: QMainWindow) -> QSystemTrayIcon:
    icon_path = os.path.join(ASSETS_DIR, "logo", "logo.ico")
    tray = QSystemTrayIcon(QIcon(icon_path), window)
    tray.setToolTip(t("app_name"))

    menu = QMenu()
    show_action = menu.addAction(t("tray.show"))
    show_action.triggered.connect(lambda: _restore_window(window))
    menu.addSeparator()
    quit_action = menu.addAction(t("tray.quit"))
    quit_action.triggered.connect(QApplication.instance().quit)
    tray.setContextMenu(menu)

    tray.activated.connect(lambda reason: _on_activated(reason, window))
    tray.show()
    return tray


def retranslate_tray_icon(tray: QSystemTrayIcon) -> None:
    """Rafraîchit le tooltip et les entrées de menu après un changement de
    langue (l'icône elle-même n'est pas reconstruite, pour éviter qu'elle
    clignote/disparaisse un instant dans la zone de notification)."""
    tray.setToolTip(t("app_name"))
    actions = tray.contextMenu().actions()
    actions[0].setText(t("tray.show"))
    actions[2].setText(t("tray.quit"))


def _restore_window(window: QMainWindow) -> None:
    window.showNormal()
    window.raise_()
    window.activateWindow()


def _on_activated(reason: QSystemTrayIcon.ActivationReason, window: QMainWindow) -> None:
    if reason == QSystemTrayIcon.ActivationReason.Trigger:
        _restore_window(window)
