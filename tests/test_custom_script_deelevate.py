"""
Tests du lancement dé-élevé via le Planificateur de tâches
(features/custom_script/deelevate.py) — toute la chaîne COM
(win32com.client.Dispatch("Schedule.Service") et les objets qu'elle
renvoie) est mockée avec des MagicMock en cascade : aucune vraie tâche
n'est jamais créée dans le vrai Planificateur pendant ces tests.
"""
import unittest
from unittest.mock import MagicMock, patch

import pywintypes

from features.custom_script import deelevate


def _make_mock_service(registered_task_pid=4242):
    """Construit une chaîne de MagicMock imitant
    Dispatch("Schedule.Service") -> Connect() -> GetFolder("\\") (racine,
    directement — plus de sous-dossier dédié, voir deelevate.py)
    -> NewTask() -> RegisterTaskDefinition() -> Run() -> EnginePID."""
    service = MagicMock()
    folder = MagicMock()
    service.GetFolder.return_value = folder

    task_def = MagicMock()
    service.NewTask.return_value = task_def

    running_task = MagicMock()
    running_task.EnginePID = registered_task_pid
    registered_task = MagicMock()
    registered_task.Run.return_value = running_task
    folder.RegisterTaskDefinition.return_value = registered_task

    return service, folder, task_def, registered_task, running_task


class TestCleanupTask(unittest.TestCase):
    def test_not_found_returns_immediately_without_warning(self):
        folder = MagicMock()
        folder.DeleteTask.side_effect = pywintypes.com_error(
            deelevate._ERROR_FILE_NOT_FOUND_HRESULT, "introuvable", None, None,
        )
        deelevate._cleanup_task(folder, "CustomScript_x")
        folder.DeleteTask.assert_called_once()

    def test_retries_on_transient_failure_then_succeeds(self):
        folder = MagicMock()
        transient = pywintypes.com_error(-2147024891, "Occupé.", None, None)
        folder.DeleteTask.side_effect = [transient, None]
        with patch.object(deelevate.time, "sleep"):
            deelevate._cleanup_task(folder, "CustomScript_x")
        self.assertEqual(folder.DeleteTask.call_count, 2)

    def test_gives_up_and_warns_after_max_attempts(self):
        folder = MagicMock()
        transient = pywintypes.com_error(-2147024891, "Occupé.", None, None)
        folder.DeleteTask.side_effect = transient
        with patch.object(deelevate.time, "sleep"):
            deelevate._cleanup_task(folder, "CustomScript_x")  # ne doit jamais lever
        self.assertEqual(folder.DeleteTask.call_count, deelevate._DELETE_TASK_RETRY_ATTEMPTS)


class TestFormatComError(unittest.TestCase):
    def test_prefers_excepinfo_description(self):
        exc = pywintypes.com_error(
            -2147024891, "RegisterTaskDefinition", None, None,
        )
        exc.excepinfo = (0, "Task Scheduler", "Accès refusé pour cet utilisateur.", None, 0, -2147024891)
        result = deelevate._format_com_error(exc, "Contexte")
        self.assertIn("Accès refusé", result)
        self.assertIn("Contexte", result)

    def test_falls_back_to_strerror_without_excepinfo(self):
        exc = pywintypes.com_error(-2147024891, "Accès refusé.", None, None)
        result = deelevate._format_com_error(exc, "Contexte")
        self.assertIn("Accès refusé", result)

    def test_includes_hresult_in_hex_and_decimal(self):
        exc = pywintypes.com_error(-2147024891, "X", "Y", None)
        result = deelevate._format_com_error(exc, "Contexte")
        self.assertIn("-2147024891", result)
        self.assertIn("0x", result)

    def test_disp_e_exception_falls_back_to_source_and_scode_without_description(self):
        # DISP_E_EXCEPTION (0x80020009) typique : description vide, mais
        # source/scode renseignés — ne doit jamais produire un message vide.
        exc = pywintypes.com_error(-2147352567, None, None, None)  # 0x80020009
        exc.excepinfo = (0, "Schedule.Service", "", None, 0, -2147024891)
        result = deelevate._format_com_error(exc, "Contexte")
        self.assertIn("Schedule.Service", result)
        self.assertIn("-2147024891", result)  # le scode imbriqué, pas seulement le HRESULT externe
        self.assertIn("80020009", result.upper())

    def test_never_produces_empty_message_when_everything_is_blank(self):
        exc = pywintypes.com_error(-2147352567, None, None, None)
        exc.excepinfo = None
        result = deelevate._format_com_error(exc, "Contexte")
        self.assertTrue(result.strip())
        self.assertIn("Contexte", result)

    def test_argerror_surfaces_when_present(self):
        exc = pywintypes.com_error(-2147352567, None, None, None)
        exc.excepinfo = None
        exc.argerror = 2
        result = deelevate._format_com_error(exc, "Contexte")
        self.assertIn("2", result)


class TestLaunchDeelevatedSuccess(unittest.TestCase):
    def test_success_returns_pid_and_no_error(self):
        service, folder, task_def, registered_task, running_task = _make_mock_service(registered_task_pid=4242)
        with patch.object(deelevate.win32com.client, "Dispatch", return_value=service), \
             patch.object(deelevate, "_current_user_sam_name", return_value="DOMAIN\\user"), \
             patch.object(deelevate.pythoncom, "CoInitialize"), \
             patch.object(deelevate.pythoncom, "CoUninitialize"):
            result = deelevate.launch_deelevated("C:\\fake\\AutoHotkey64.exe", ["C:\\script.ahk"], "C:\\fake")

        self.assertEqual(result.pid, 4242)
        self.assertIsNone(result.error_detail)
        # La tâche doit être déclenchée puis supprimée, jamais laissée en place.
        registered_task.Run.assert_called_once()
        # 2 appels attendus : suppression défensive AVANT l'enregistrement
        # (voir _cleanup_task appelé pré-emptivement) + nettoyage final dans
        # le "finally" — toujours le même nom de tâche dans les deux cas.
        used_task_name = folder.RegisterTaskDefinition.call_args.args[0]
        self.assertEqual(folder.DeleteTask.call_count, 2)
        for call in folder.DeleteTask.call_args_list:
            self.assertEqual(call.args[0], used_task_name)

    def test_task_name_is_unique_and_prefixed(self):
        service, folder, task_def, registered_task, running_task = _make_mock_service()
        with patch.object(deelevate.win32com.client, "Dispatch", return_value=service), \
             patch.object(deelevate, "_current_user_sam_name", return_value="DOMAIN\\user"), \
             patch.object(deelevate.pythoncom, "CoInitialize"), \
             patch.object(deelevate.pythoncom, "CoUninitialize"):
            deelevate.launch_deelevated("C:\\fake\\AutoHotkey64.exe", [], "C:\\fake")
            deelevate.launch_deelevated("C:\\fake\\AutoHotkey64.exe", [], "C:\\fake")

        names = [call.args[0] for call in folder.RegisterTaskDefinition.call_args_list]
        self.assertEqual(len(names), 2)
        self.assertNotEqual(names[0], names[1])
        for name in names:
            self.assertTrue(name.startswith(deelevate._TASK_NAME_PREFIX))

    def test_cleanup_happens_even_when_pid_never_populates(self):
        service, folder, task_def, registered_task, running_task = _make_mock_service()
        running_task.EnginePID = 0  # ne se peuple jamais
        with patch.object(deelevate.win32com.client, "Dispatch", return_value=service), \
             patch.object(deelevate, "_current_user_sam_name", return_value="DOMAIN\\user"), \
             patch.object(deelevate.pythoncom, "CoInitialize"), \
             patch.object(deelevate.pythoncom, "CoUninitialize"), \
             patch.object(deelevate.time, "monotonic", side_effect=[0, 0, 10]), \
             patch.object(deelevate.time, "sleep"):
            result = deelevate.launch_deelevated("C:\\fake\\AutoHotkey64.exe", [], "C:\\fake")

        self.assertIsNone(result.pid)
        self.assertIsNotNone(result.error_detail)
        self.assertIn("PID", result.error_detail)
        # 2 appels : suppression défensive avant enregistrement + nettoyage
        # final — nettoyage même en échec de récupération du PID.
        self.assertEqual(folder.DeleteTask.call_count, 2)

    def test_registers_task_directly_at_scheduler_root(self):
        # Plus de sous-dossier dédié (voir deelevate.py, docstring) : la
        # tâche est enregistrée directement à la racine "\\", jamais de
        # GetFolder/CreateFolder sur un sous-dossier.
        service, folder, task_def, registered_task, running_task = _make_mock_service()

        with patch.object(deelevate.win32com.client, "Dispatch", return_value=service), \
             patch.object(deelevate, "_current_user_sam_name", return_value="DOMAIN\\user"), \
             patch.object(deelevate.pythoncom, "CoInitialize"), \
             patch.object(deelevate.pythoncom, "CoUninitialize"):
            deelevate.launch_deelevated("C:\\fake\\AutoHotkey64.exe", [], "C:\\fake")

        service.GetFolder.assert_called_once_with("\\")


class TestLaunchDeelevatedFailure(unittest.TestCase):
    def test_com_error_during_registration_surfaces_detail_and_still_cleans_up(self):
        service, folder, task_def, registered_task, running_task = _make_mock_service()
        exc = pywintypes.com_error(-2147024891, "Accès refusé.", None, None)
        folder.RegisterTaskDefinition.side_effect = exc

        with patch.object(deelevate.win32com.client, "Dispatch", return_value=service), \
             patch.object(deelevate, "_current_user_sam_name", return_value="DOMAIN\\user"), \
             patch.object(deelevate.pythoncom, "CoInitialize"), \
             patch.object(deelevate.pythoncom, "CoUninitialize"):
            result = deelevate.launch_deelevated("C:\\fake\\AutoHotkey64.exe", [], "C:\\fake")

        self.assertIsNone(result.pid)
        self.assertIn("Accès refusé", result.error_detail)
        # RegisterTaskDefinition a échoué (pas ERROR_ALREADY_EXISTS, donc
        # pas de nouvelle tentative) -> rien à déclencher.
        registered_task.Run.assert_not_called()
        folder.RegisterTaskDefinition.assert_called_once()
        # DeleteTask tenté 2 fois (suppression défensive avant + nettoyage
        # final) — avalé dans les deux cas si la tâche n'existe pas.
        self.assertEqual(folder.DeleteTask.call_count, 2)

    def test_already_exists_on_register_deletes_and_retries_once(self):
        # Malgré TASK_CREATE_OR_UPDATE, RegisterTaskDefinition échoue une
        # première fois avec ERROR_ALREADY_EXISTS (voir diagnostic réel) :
        # doit supprimer explicitement puis retenter, et réussir.
        service, folder, task_def, registered_task, running_task = _make_mock_service(registered_task_pid=777)
        already_exists = pywintypes.com_error(
            deelevate._ERROR_ALREADY_EXISTS_HRESULT, "existe déjà", None, None,
        )
        folder.RegisterTaskDefinition.side_effect = [already_exists, registered_task]

        with patch.object(deelevate.win32com.client, "Dispatch", return_value=service), \
             patch.object(deelevate, "_current_user_sam_name", return_value="DOMAIN\\user"), \
             patch.object(deelevate.pythoncom, "CoInitialize"), \
             patch.object(deelevate.pythoncom, "CoUninitialize"):
            result = deelevate.launch_deelevated("C:\\fake\\AutoHotkey64.exe", [], "C:\\fake")

        self.assertEqual(result.pid, 777)
        self.assertIsNone(result.error_detail)
        self.assertEqual(folder.RegisterTaskDefinition.call_count, 2)
        # Suppression défensive avant + suppression explicite après l'échec
        # ALREADY_EXISTS + nettoyage final = 3 appels.
        self.assertEqual(folder.DeleteTask.call_count, 3)

    def test_unexpected_exception_never_propagates(self):
        service, folder, task_def, registered_task, running_task = _make_mock_service()
        folder.RegisterTaskDefinition.side_effect = RuntimeError("boom")

        with patch.object(deelevate.win32com.client, "Dispatch", return_value=service), \
             patch.object(deelevate, "_current_user_sam_name", return_value="DOMAIN\\user"), \
             patch.object(deelevate.pythoncom, "CoInitialize"), \
             patch.object(deelevate.pythoncom, "CoUninitialize"):
            result = deelevate.launch_deelevated("C:\\fake\\AutoHotkey64.exe", [], "C:\\fake")

        self.assertIsNone(result.pid)
        self.assertIn("boom", result.error_detail)

    def test_delete_task_failure_is_swallowed(self):
        service, folder, task_def, registered_task, running_task = _make_mock_service(registered_task_pid=99)
        folder.DeleteTask.side_effect = pywintypes.com_error(-1, "DeleteTask", "introuvable", None)

        with patch.object(deelevate.win32com.client, "Dispatch", return_value=service), \
             patch.object(deelevate, "_current_user_sam_name", return_value="DOMAIN\\user"), \
             patch.object(deelevate.pythoncom, "CoInitialize"), \
             patch.object(deelevate.pythoncom, "CoUninitialize"):
            result = deelevate.launch_deelevated("C:\\fake\\AutoHotkey64.exe", [], "C:\\fake")

        # L'échec de nettoyage ne doit jamais masquer un lancement réussi.
        self.assertEqual(result.pid, 99)
        self.assertIsNone(result.error_detail)


if __name__ == "__main__":
    unittest.main()
