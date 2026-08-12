"""
Élévation Windows au démarrage : demande UAC classique à CHAQUE lancement
tant que le process n'est pas déjà administrateur.

Historique : un mécanisme à base de tâche planifiée Windows (créée une
seule fois, puis relancée sans re-prompt UAC) a été essayé ici, mais
provoquait une boucle d'ouverture/fermeture rapide sur certaines
configurations Windows (is_admin() pouvait rapporter à tort "pas élevé"
dans le process lancé par la tâche, qui redéclenchait alors une nouvelle
relance indéfiniment). Reverti au profit de ce mécanisme plus simple et
fiable, quitte à redemander une confirmation UAC à chaque lancement — un
compromis assumé : mieux vaut une app qui redemande l'autorisation à
chaque fois qu'une app inutilisable. Le mécanisme par tâche planifiée
pourra être retravaillé plus tard, plus prudemment.

PresentMon (features/performance/fps_monitor.py) et le correctif SysMain
(features/performance/fixes.py) consultent is_admin() : une fois l'app
elle-même lancée élevée, ils sautent leur propre demande d'élévation
individuelle.
"""
import ctypes
import os
import sys


def is_admin() -> bool:
    """True si le processus courant tourne déjà avec les droits administrateur."""
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def _dev_mode_executable() -> str:
    """pythonw.exe (variante SANS console, à côté de python.exe dans la même
    installation) plutôt que sys.executable directement : ShellExecuteW
    élevant python.exe (sous-système console) lui alloue une nouvelle
    console visible — la fenêtre par défaut "python.exe" qui restait
    ouverte à côté de l'app tant que le process tournait. pythonw.exe n'en
    alloue aucune. Repli sur python.exe si pythonw.exe est introuvable pour
    une raison quelconque (installation non standard)."""
    candidate = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return candidate if os.path.isfile(candidate) else sys.executable


def relaunch_as_admin() -> bool:
    """Relance l'application (même arguments) avec élévation UAC (invite
    Windows native), à chaque appel. Retourne True si le nouveau processus
    élevé a bien été lancé — l'appelant doit alors fermer le processus non
    élevé actuel. Retourne False si l'utilisateur a refusé le prompt UAC (ou
    en cas d'erreur) : l'appelant doit alors continuer sans droits admin
    plutôt que de fermer l'app silencieusement."""
    if getattr(sys, "frozen", False):
        # Exécutable compilé (PyInstaller) : sys.executable est déjà
        # l'application elle-même, pas besoin d'y ajouter le chemin du script.
        target = sys.executable
        args = sys.argv[1:]
        workdir = os.path.dirname(sys.executable)
    else:
        target = _dev_mode_executable()
        script = os.path.abspath(sys.argv[0])
        args = [script] + sys.argv[1:]
        workdir = os.path.dirname(script)

    params = " ".join(f'"{arg}"' for arg in args)
    # nShowCmd = SW_HIDE (0), pas SW_SHOWNORMAL : en mode développement,
    # `target` est un exécutable console (python.exe, ou pythonw.exe en
    # repli absent) — Windows lui alloue une nouvelle console lors de
    # l'élévation (il ne peut pas hériter de celle du process non élevé
    # d'origine). Nos propres fenêtres Qt (splash/MainWindow) restent
    # affichées normalement : elles ont leur propre show() explicite,
    # indépendant de ce paramètre.
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", target, params, workdir, 0)
    # ShellExecuteW retourne une valeur > 32 en cas de succès ; sinon un code
    # d'erreur (ex. 5 = accès refusé, si l'utilisateur refuse le prompt UAC).
    success = result > 32
    # Import différé (pas en tête de fichier) : core/elevation.py est
    # importé très tôt dans main.py, avant même setup_logging() — on évite
    # ainsi tout risque d'alourdir cet import précoce, alors que
    # core/security_log.py lui-même n'a besoin d'aucune configuration
    # préalable pour écrire sa propre ligne (voir sa docstring).
    from core.security_log import log_event

    log_event("uac_elevation", target, "ok" if success else "error", sensitive=True)
    return success
