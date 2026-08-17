"""
Tests (pytest) des chemins de données de l'application (core/paths.py) —
%APPDATA% redirigé vers tmp_path (monkeypatch.setenv), jamais le vrai
dossier de l'utilisateur qui lance ces tests.
"""
import os

import core.paths as paths_mod


def _use_fake_appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))


def test_get_app_data_dir_created_and_named_after_app(tmp_path, monkeypatch):
    _use_fake_appdata(tmp_path, monkeypatch)
    app_dir = paths_mod.get_app_data_dir()
    assert os.path.isdir(app_dir)
    assert os.path.basename(app_dir) == paths_mod.APP_NAME
    assert os.path.dirname(app_dir) == str(tmp_path)


def test_all_directory_helpers_are_created_and_nested_under_app_data_dir(tmp_path, monkeypatch):
    _use_fake_appdata(tmp_path, monkeypatch)
    app_dir = paths_mod.get_app_data_dir()

    dir_helpers = [
        paths_mod.get_logs_dir, paths_mod.get_macros_dir, paths_mod.get_cursors_dir,
        paths_mod.get_fastflags_presets_dir, paths_mod.get_custom_scripts_dir,
        paths_mod.get_fleasion_presets_dir,
    ]
    for helper in dir_helpers:
        directory = helper()
        assert os.path.isdir(directory), f"{helper.__name__} n'a pas créé son dossier"
        assert directory.startswith(app_dir), f"{helper.__name__} n'est pas nichée sous get_app_data_dir()"


def test_all_file_path_helpers_are_nested_under_app_data_dir_without_creating_them(tmp_path, monkeypatch):
    _use_fake_appdata(tmp_path, monkeypatch)
    app_dir = paths_mod.get_app_data_dir()

    file_helpers = [
        paths_mod.get_settings_path, paths_mod.get_license_path,
        paths_mod.get_fastflags_known_flags_path, paths_mod.get_fastflags_active_config_path,
        paths_mod.get_fastflags_backup_path, paths_mod.get_security_log_path,
        paths_mod.get_fastflags_backup_marker_path,
    ]
    for helper in file_helpers:
        path = helper()
        assert path.startswith(app_dir), f"{helper.__name__} n'est pas niché sous get_app_data_dir()"
        # Un chemin de FICHIER (pas dossier) ne doit jamais créer quoi que ce
        # soit lui-même — seule une vraie écriture doit le faire exister.
        assert not os.path.exists(path)


def test_security_log_path_lives_inside_logs_dir(tmp_path, monkeypatch):
    _use_fake_appdata(tmp_path, monkeypatch)
    logs_dir = paths_mod.get_logs_dir()
    security_log_path = paths_mod.get_security_log_path()
    assert os.path.dirname(security_log_path) == logs_dir


def test_each_directory_helper_is_distinct(tmp_path, monkeypatch):
    _use_fake_appdata(tmp_path, monkeypatch)
    dirs = {
        paths_mod.get_logs_dir(), paths_mod.get_macros_dir(), paths_mod.get_cursors_dir(),
        paths_mod.get_fastflags_presets_dir(), paths_mod.get_custom_scripts_dir(),
        paths_mod.get_fleasion_presets_dir(),
    }
    assert len(dirs) == 6
