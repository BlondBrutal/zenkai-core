"""
Détection du jeu actuellement au premier plan (fenêtre active de Windows),
parmi une liste de jeux connus — sert au bouton dynamique "Optimiser pour
{jeu détecté}" de la page Performance (voir
ui/pages/page_performance.py::_build_optimize_card).

KNOWN_GAMES est un simple dict "nom d'exécutable -> nom affiché" : pour
reconnaître un nouveau jeu plus tard, il suffit d'ajouter une ligne ici,
aucune autre logique à toucher.
"""
import ctypes
from ctypes import wintypes

import psutil

# Nom d'exécutable Roblox, en minuscules (psutil.Process.name() est comparé
# en minuscules ci-dessous) — clé de référence pour distinguer "c'est
# Roblox" (recommandation Fast Flags pertinente) de "c'est un autre jeu
# connu" (seules les 4 corrections Windows génériques ont du sens).
ROBLOX_EXE_NAME = "robloxplayerbeta.exe"

# Ajouter un jeu ici (nom d'exe en minuscules -> nom affiché) suffit à le
# faire reconnaître par detect_foreground_game(), sans rien changer d'autre.
KNOWN_GAMES: dict[str, str] = {
    ROBLOX_EXE_NAME: "Roblox",
}

# Fonctions Windows nécessaires pour savoir quelle fenêtre est au premier
# plan puis retrouver le processus propriétaire de cette fenêtre (même
# technique que features/cursor/cursor_manager.py::_foreground_process_name).
_user32 = ctypes.windll.user32
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD


def foreground_process_name() -> str:
    """Renvoie le nom (en minuscules) de l'exécutable dont la fenêtre est au
    premier plan, ou une chaîne vide si on n'arrive pas à le déterminer. Ne
    lève jamais d'exception : un souci ici ne doit jamais faire planter la
    page Performance, juste faire retomber sur le libellé neutre."""
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        return psutil.Process(pid.value).name().lower()
    except Exception:
        return ""


def detect_foreground_game() -> tuple[str, str] | None:
    """Si la fenêtre au premier plan appartient à un jeu de KNOWN_GAMES,
    renvoie (nom_exe, nom_affiché). Sinon (autre application, ou aucune
    fenêtre détectable) renvoie None — c'est ce None qui déclenche le
    libellé neutre "Optimiser pour Windows" côté page Performance.

    Comme une seule fenêtre peut être au premier plan à la fois, "plusieurs
    jeux ouverts en même temps" se résout tout seul : on ne regarde jamais
    que celle-ci, jamais la liste des processus en cours d'exécution."""
    process_name = foreground_process_name()
    display_name = KNOWN_GAMES.get(process_name)
    if display_name is None:
        return None
    return process_name, display_name
