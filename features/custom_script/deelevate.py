"""
Lance un process SANS hériter du jeton élevé de cette app, via le
Planificateur de tâches Windows — utilisé uniquement quand
core.elevation.is_admin() est vrai (voir process_manager.py::start_script).

Historique : la première version utilisait CreateProcessAsUser avec un
jeton dupliqué/ré-intégré en Medium — approche abandonnée après diagnostic
(GetLastError == ERROR_NOT_ALL_ASSIGNED) : SeAssignPrimaryTokenPrivilege
n'est PAS présent par défaut sur un jeton Administrateur standard, même
élevé via UAC (seuls SYSTEM et certains comptes de service l'ont) — un
problème structurel de Windows, pas une question de correctif.

Technique retenue : le service Planificateur de tâches tourne en tant que
SYSTEM et POSSÈDE ces privilèges — il construit lui-même, en interne, un
jeton utilisateur au niveau demandé pour notre compte, sans que l'app ait
besoin des privilèges qui lui manquent. On enregistre une tâche PONCTUELLE
et JETABLE, À LA RACINE du Planificateur ("\\", jamais un sous-dossier
dédié — voir plus bas pourquoi), avec un nom unique par lancement, jamais
de déclencheur programmé — seulement un lancement à la demande via .Run(),
configurée en LogonType=TASK_LOGON_INTERACTIVE_TOKEN (jeton de la session
interactive déjà ouverte, pas de mot de passe) et RunLevel=TASK_RUNLEVEL_LUA
(jamais TASK_RUNLEVEL_HIGHEST — c'est ce réglage qui garantit le process
dé-élevé). Le PID réel est lu via IRunningTask.EnginePID juste après le
déclenchement, puis la DÉFINITION de tâche est supprimée immédiatement
(un process déjà lancé devient indépendant de l'engine de tâche une fois
démarré — le supprimer n'arrête pas le process, voir _cleanup_task).

Pas de sous-dossier "ZenkaiCore" dédié (essayé puis abandonné) : sa
création/lecture (GetFolder/CreateFolder) était la source d'un
ERROR_ALREADY_EXISTS récurrent dont la cause exacte est restée
introuvable malgré plusieurs correctifs (repli sur relecture, logging
détaillé de l'échec initial...). La racine du Planificateur ("\\") existe
TOUJOURS nativement, sans jamais nécessiter ni GetFolder ni CreateFolder —
en supprimant cette étape entièrement, on supprime la classe de bug avec.
Le nom de tâche unique (UUID) et le nettoyage immédiat après usage
(_cleanup_task) suffisent déjà à éviter toute collision/résidu, avec ou
sans sous-dossier dédié.

Ceci N'A AUCUN RAPPORT avec l'ancien mécanisme "tâche planifiée avec
privilèges élevés" retiré du projet (bug de fenêtre fantôme/boucle) : celui-
là servait à faire tourner TOUTE L'APP élevée sans reprompt UAC à chaque
démarrage (auto-élévation persistante). Ici, la tâche est un lanceur
ponctuel pour UN SEUL process enfant, au niveau LUA (dé-élevé), supprimée
en quelques secondes — aucun rapport avec la séquence de démarrage de l'app.

Ne journalise RIEN elle-même (voir DeelevationResult.error_detail) : le
diagnostic détaillé est renvoyé à l'appelant, qui décide comment le
présenter/journaliser (process_manager.py::start_script est le seul point
qui appelle log_event pour un lancement, jamais dupliqué ici).
"""
import logging
import time
import uuid
from dataclasses import dataclass

import pythoncom
import pywintypes
import win32api
import win32com.client
import win32con

logger = logging.getLogger("zenkaiontop.custom_script")

_TASK_NAME_PREFIX = "CustomScript_"

# Constantes de l'énumération COM Task Scheduler (taskschd.h) — valeurs
# documentées Microsoft, stables ; utilisées en liaison tardive (pas de
# makepy/gencache nécessaire, voir plan de cette fonctionnalité).
_TASK_CREATE_OR_UPDATE = 6
_TASK_ACTION_EXEC = 0
_TASK_LOGON_INTERACTIVE_TOKEN = 3
_TASK_RUNLEVEL_LUA = 0

_PID_WAIT_TIMEOUT_SECONDS = 5.0
_PID_POLL_INTERVAL_SECONDS = 0.05

# HRESULT_FROM_WIN32(ERROR_ALREADY_EXISTS) = HRESULT_FROM_WIN32(183) =
# 0x800700B7 — vu en pratique sur le scode imbriqué d'un DISP_E_EXCEPTION
# renvoyé par RegisterTaskDefinition/CreateFolder quand une tâche/un
# dossier du même nom existe déjà (résidu d'un essai précédent).
_ERROR_ALREADY_EXISTS_HRESULT = -2147024713
# HRESULT_FROM_WIN32(ERROR_FILE_NOT_FOUND) = 0x80070002 — la tâche/le
# dossier n'existe déjà plus : pas une vraie erreur de nettoyage, jamais à
# journaliser comme un échec.
_ERROR_FILE_NOT_FOUND_HRESULT = -2147024894

_DELETE_TASK_RETRY_ATTEMPTS = 3
_DELETE_TASK_RETRY_DELAY_SECONDS = 0.2


@dataclass
class DeelevationResult:
    pid: int | None
    error_detail: str | None  # None si succès ; message détaillé sinon


def _format_com_error(exc: pywintypes.com_error, context: str) -> str:
    """Extrait le maximum d'info exploitable d'un pywintypes.com_error —
    en particulier pour un DISP_E_EXCEPTION (0x80020009, "une exception
    s'est produite côté serveur COM"), le HRESULT seul ne dit RIEN sur la
    cause réelle : le vrai message vient du champ excepinfo
    (wCode, source, description, helpFile, helpContext, scode), rempli par
    le serveur COM (ici le Planificateur de tâches) au moment de l'échec.
    Construit le message en cumulant TOUTES les infos disponibles plutôt
    que d'en choisir une seule au hasard — si le champ habituellement le
    plus utile (description) est vide, source/scode/strerror peuvent quand
    même révéler la vraie cause."""
    hresult = getattr(exc, "hresult", None)
    strerror = getattr(exc, "strerror", None)
    excepinfo = getattr(exc, "excepinfo", None)
    argerror = getattr(exc, "argerror", None)

    fragments: list[str] = []
    if isinstance(excepinfo, tuple):
        padded = list(excepinfo) + [None] * (6 - len(excepinfo))
        _wcode, source, description, _helpfile, _helpcontext, scode = padded[:6]
        if description:
            fragments.append(str(description).strip())
        if source:
            fragments.append(f"[source: {source}]")
        if scode:
            fragments.append(f"[scode COM: {scode}]")
    if strerror and str(strerror) not in fragments:
        fragments.append(str(strerror))
    if argerror is not None:
        fragments.append(f"[argument en erreur: index {argerror}]")
    if not fragments:
        fragments.append(str(exc) or "(aucun détail fourni par le serveur COM)")

    message = " — ".join(fragments)
    if hresult is not None:
        message = f"{message} (HRESULT 0x{hresult & 0xFFFFFFFF:08X} / {hresult})"
    return f"{context} — {message}"


def _current_user_sam_name() -> str:
    return win32api.GetUserNameEx(win32con.NameSamCompatible)


def _cleanup_task(folder, task_name: str) -> None:
    """Supprime la DÉFINITION de tâche — n'arrête PAS un process déjà
    lancé (documenté : un process devient indépendant de l'engine de tâche
    une fois démarré). Plusieurs tentatives avec un court délai (au lieu
    d'un simple coup unique avalé) : un DeleteTask juste après un .Run()
    peut échouer transitoirement si le Planificateur considère encore la
    tâche "occupée" — jamais silencieusement abandonné après une seule
    tentative, sinon des résidus peuvent s'accumuler (voir le blocage
    ERROR_ALREADY_EXISTS déjà rencontré). "Déjà absente" (ERROR_FILE_NOT_
    FOUND) n'est PAS une erreur, retour immédiat sans retenter ni avertir."""
    for attempt in range(1, _DELETE_TASK_RETRY_ATTEMPTS + 1):
        try:
            folder.DeleteTask(task_name, 0)
            return
        except pywintypes.com_error as exc:
            if getattr(exc, "hresult", None) == _ERROR_FILE_NOT_FOUND_HRESULT:
                return  # déjà absente, rien à faire
            if attempt == _DELETE_TASK_RETRY_ATTEMPTS:
                logger.warning(
                    "Nettoyage de la tâche %s incomplet après %d tentative(s) : %s",
                    task_name, _DELETE_TASK_RETRY_ATTEMPTS, _format_com_error(exc, "Nettoyage tâche"),
                )
                return
            time.sleep(_DELETE_TASK_RETRY_DELAY_SECONDS)


def launch_deelevated(exe_path: str, args: list[str], workdir: str) -> DeelevationResult:
    """Voir docstring du module. error_detail est toujours None en cas de
    succès, jamais None en cas d'échec — jamais de repli élevé silencieux."""
    pythoncom.CoInitialize()
    task_name = f"{_TASK_NAME_PREFIX}{uuid.uuid4().hex}"
    folder = None
    try:
        service = win32com.client.Dispatch("Schedule.Service")
        service.Connect()
        # Racine du Planificateur directement (jamais de sous-dossier dédié,
        # voir docstring du module) : "\\" existe toujours nativement, ni
        # GetFolder ni CreateFolder n'est donc jamais nécessaire ici.
        folder = service.GetFolder("\\")
        # Efface explicitement toute tâche qui porterait déjà ce nom précis
        # avant de créer la nôtre — normalement un no-op vu le nom unique
        # (UUID) par lancement, mais défense en profondeur en plus de
        # TASK_CREATE_OR_UPDATE ci-dessous (voir diagnostic
        # ERROR_ALREADY_EXISTS déjà rencontré).
        _cleanup_task(folder, task_name)

        task_def = service.NewTask(0)
        task_def.RegistrationInfo.Description = (
            "Zenkai Core — lancement temporaire et dé-élevé d'un Custom Script (AutoHotkey)."
        )
        task_def.Principal.LogonType = _TASK_LOGON_INTERACTIVE_TOKEN
        task_def.Principal.RunLevel = _TASK_RUNLEVEL_LUA
        task_def.Settings.Enabled = True
        task_def.Settings.AllowDemandStart = True
        task_def.Settings.DisallowStartIfOnBatteries = False
        task_def.Settings.StopIfGoingOnBatteries = False

        action = task_def.Actions.Create(_TASK_ACTION_EXEC)
        action.Path = exe_path
        action.Arguments = " ".join(f'"{a}"' for a in args)
        action.WorkingDirectory = workdir

        user_id = _current_user_sam_name()
        try:
            registered_task = folder.RegisterTaskDefinition(
                task_name, task_def, _TASK_CREATE_OR_UPDATE, user_id, None, _TASK_LOGON_INTERACTIVE_TOKEN,
            )
        except pywintypes.com_error as exc:
            if getattr(exc, "hresult", None) != _ERROR_ALREADY_EXISTS_HRESULT:
                raise
            # TASK_CREATE_OR_UPDATE devrait déjà couvrir ce cas — repli
            # explicite quand même (dernier rempart, voir diagnostic) :
            # supprime la tâche existante puis retente une seule fois.
            logger.warning(
                "RegisterTaskDefinition a échoué avec ERROR_ALREADY_EXISTS malgré "
                "TASK_CREATE_OR_UPDATE pour %s — suppression explicite puis nouvelle tentative.",
                task_name,
            )
            _cleanup_task(folder, task_name)
            registered_task = folder.RegisterTaskDefinition(
                task_name, task_def, _TASK_CREATE_OR_UPDATE, user_id, None, _TASK_LOGON_INTERACTIVE_TOKEN,
            )
        running_task = registered_task.Run(None)

        pid = 0
        deadline = time.monotonic() + _PID_WAIT_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            running_task.Refresh()
            pid = running_task.EnginePID
            if pid:
                break
            time.sleep(_PID_POLL_INTERVAL_SECONDS)

        if not pid:
            logger.warning("Tâche %s déclenchée mais PID jamais peuplé avant le timeout", task_name)
            return DeelevationResult(
                pid=None,
                error_detail=(
                    "La tâche a été déclenchée mais son PID n'a pas pu être récupéré à temps "
                    f"({_PID_WAIT_TIMEOUT_SECONDS:.0f}s)."
                ),
            )
        return DeelevationResult(pid=int(pid), error_detail=None)
    except pywintypes.com_error as exc:
        # Dump brut systématique AVANT tout formatage : si _format_com_error
        # choisit malgré tout un mauvais champ pour tel ou tel HRESULT
        # (ex. DISP_E_EXCEPTION avec un excepinfo inhabituel), cette ligne
        # garde toute l'info disponible consultable dans le log applicatif,
        # sans dépendre d'un futur aller-retour pour la récupérer.
        logger.error(
            "COM error brute — hresult=%r strerror=%r excepinfo=%r argerror=%r args=%r",
            getattr(exc, "hresult", None), getattr(exc, "strerror", None),
            getattr(exc, "excepinfo", None), getattr(exc, "argerror", None), exc.args,
        )
        detail = _format_com_error(exc, "Lancement dé-élevé (Planificateur de tâches)")
        logger.error("Échec du lancement dé-élevé pour %s : %s", exe_path, detail)
        return DeelevationResult(pid=None, error_detail=detail)
    except Exception as exc:
        detail = f"Lancement dé-élevé (Planificateur de tâches) — {exc}"
        logger.exception("Échec inattendu du lancement dé-élevé pour %s", exe_path)
        return DeelevationResult(pid=None, error_detail=detail)
    finally:
        if folder is not None:
            _cleanup_task(folder, task_name)
        pythoncom.CoUninitialize()
