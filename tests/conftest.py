"""
Configuration partagée par toute la suite de tests (pytest) : force Qt en
mode "offscreen" AVANT que quoi que ce soit n'importe PyQt6 — plusieurs
modules testés ici (features/cursor/cursor_image.py, features/macro_pixel/
key_names.py, features/performance/live_monitor.py...) importent PyQt6 pour
ses enums/types (QImage, Qt.Key...), même sans jamais ouvrir de vraie
fenêtre. Sans QT_QPA_PLATFORM=offscreen, PyQt6 tente de se connecter à un
serveur d'affichage réel (ou natif Windows) au premier import, ce qui plante
sur une machine sans session graphique (CI headless) et n'a de toute façon
aucune utilité pour des tests qui ne dessinent jamais rien à l'écran.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
