"""
Récupération des informations système statiques (specs, réglages Windows,
espace disque, version Roblox détectée). Ne lève jamais d'exception : un
champ qui échoue à se remplir retombe sur None/"Inconnu" et log l'erreur,
plutôt que de faire planter le scan.
"""
import logging
import os
import re
import subprocess
import sys
import winreg
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import psutil

logger = logging.getLogger("zenkaiontop.performance")


def _run_hidden(args: list[str], timeout: float = 5) -> "subprocess.CompletedProcess[str]":
    """subprocess.run sans jamais afficher de fenêtre de console : creationflags
    CREATE_NO_WINDOW seul suffit généralement, mais on ajoute aussi le
    STARTUPINFO (STARTF_USESHOWWINDOW + SW_HIDE) pour plus de fiabilité (même
    technique que features/performance/live_monitor.py, voir sa docstring
    pour le bug — fenêtre de console visible — que ça corrige)."""
    creationflags = 0
    startupinfo = None
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, errors="replace",
        creationflags=creationflags, startupinfo=startupinfo,
    )


@dataclass
class SystemSpecs:
    cpu_name: Optional[str] = None
    cpu_cores: Optional[int] = None
    gpu_name: Optional[str] = None
    gpu_driver_version: Optional[str] = None
    gpu_driver_date: Optional[str] = None
    ram_total_gb: Optional[float] = None
    os_caption: Optional[str] = None
    screen_resolution: Optional[str] = None
    power_plan_guid: Optional[str] = None
    power_plan_name: Optional[str] = None
    game_mode_enabled: Optional[bool] = None
    game_dvr_enabled: Optional[bool] = None
    sysmain_running: Optional[bool] = None
    disk_free_gb: Optional[float] = None
    disk_total_gb: Optional[float] = None
    disk_free_percent: Optional[float] = None
    roblox_version_folder: Optional[str] = None
    roblox_install_dir: Optional[str] = None


def _safe(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        logger.warning("Échec %s: %s", getattr(fn, "__name__", fn), exc)
        return None


def _get_cpu_info() -> tuple[Optional[str], Optional[int]]:
    name = None
    try:
        import wmi
        c = wmi.WMI()
        processors = c.Win32_Processor()
        if processors:
            name = processors[0].Name.strip()
    except Exception as exc:
        logger.warning("WMI CPU indisponible (%s)", exc)
    return name, psutil.cpu_count(logical=True)


def _get_gpu_info() -> tuple[Optional[str], Optional[str], Optional[str]]:
    try:
        import wmi
        c = wmi.WMI()
        controllers = [g for g in c.Win32_VideoController() if g.Name]
        if not controllers:
            return None, None, None
        gpu = controllers[0]
        driver_date = None
        if gpu.DriverDate:
            try:
                driver_date = datetime.strptime(gpu.DriverDate[:8], "%Y%m%d").strftime("%d/%m/%Y")
            except ValueError:
                driver_date = None
        return gpu.Name.strip(), gpu.DriverVersion, driver_date
    except Exception as exc:
        logger.warning("WMI GPU indisponible (%s)", exc)
        return None, None, None


def _get_os_caption() -> Optional[str]:
    try:
        import wmi
        c = wmi.WMI()
        systems = c.Win32_OperatingSystem()
        return systems[0].Caption.strip() if systems else None
    except Exception as exc:
        logger.warning("WMI OS indisponible (%s)", exc)
        return None


def _get_screen_resolution() -> Optional[str]:
    try:
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen is None:
            return None
        size = screen.size()
        return f"{size.width()} x {size.height()}"
    except Exception as exc:
        logger.warning("Résolution écran indisponible (%s)", exc)
        return None


def _get_power_plan() -> tuple[Optional[str], Optional[str]]:
    """Retourne (GUID, nom localisé). Le GUID est stable quelle que soit la
    langue de Windows, contrairement au nom ("Haute performance" / "High
    performance" / ...) : c'est lui qu'on compare pour juger du statut."""
    try:
        result = _run_hidden(["powercfg", "/getactivescheme"])
        output = result.stdout.strip()
        guid_match = re.search(r"([0-9a-fA-F-]{36})", output)
        name_match = re.search(r"\(([^)]+)\)\s*$", output)
        return (
            guid_match.group(1).lower() if guid_match else None,
            name_match.group(1) if name_match else None,
        )
    except Exception as exc:
        logger.warning("powercfg indisponible (%s)", exc)
        return None, None


def _get_game_mode_enabled() -> Optional[bool]:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\GameBar") as key:
            value, _ = winreg.QueryValueEx(key, "AllowAutoGameMode")
            return bool(value)
    except FileNotFoundError:
        return True  # valeur absente = comportement par défaut de Windows (activé)
    except Exception as exc:
        logger.warning("Registre Mode Jeu indisponible (%s)", exc)
        return None


def _get_game_dvr_enabled() -> Optional[bool]:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"System\GameConfigStore") as key:
            value, _ = winreg.QueryValueEx(key, "GameDVR_Enabled")
            return bool(value)
    except FileNotFoundError:
        return True
    except Exception as exc:
        logger.warning("Registre Game DVR indisponible (%s)", exc)
        return None


def _get_sysmain_running() -> Optional[bool]:
    try:
        return psutil.win_service_get("SysMain").status() == "running"
    except Exception as exc:
        logger.warning("Service SysMain indisponible (%s)", exc)
        return None


def _get_disk_info(path: str) -> tuple[Optional[float], Optional[float], Optional[float]]:
    try:
        usage = psutil.disk_usage(path)
        free_gb = usage.free / 1024**3
        total_gb = usage.total / 1024**3
        free_percent = (usage.free / usage.total) * 100 if usage.total else None
        return round(free_gb, 1), round(total_gb, 1), round(free_percent, 1) if free_percent is not None else None
    except Exception as exc:
        logger.warning("Espace disque indisponible pour %s (%s)", path, exc)
        return None, None, None


def find_roblox_install() -> tuple[Optional[str], Optional[str]]:
    """Retourne (dossier version-xxxx le plus récent, chemin complet) ou (None, None)."""
    versions_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Roblox", "Versions")
    if not os.path.isdir(versions_dir):
        return None, None
    try:
        candidates = [
            entry for entry in os.listdir(versions_dir)
            if entry.startswith("version-") and os.path.isdir(os.path.join(versions_dir, entry))
        ]
        if not candidates:
            return None, None
        latest = max(candidates, key=lambda e: os.path.getmtime(os.path.join(versions_dir, e)))
        return latest, os.path.join(versions_dir, latest)
    except Exception as exc:
        logger.warning("Lecture du dossier Roblox impossible (%s)", exc)
        return None, None


def gather_system_specs() -> SystemSpecs:
    """Rassemble toutes les infos statiques. Peut prendre quelques centaines
    de ms (appels WMI/subprocess) : à exécuter dans un thread séparé."""
    cpu_name, cpu_cores = _get_cpu_info()
    gpu_name, gpu_driver_version, gpu_driver_date = _get_gpu_info()

    vm = _safe(psutil.virtual_memory)
    ram_total_gb = round(vm.total / 1024**3, 1) if vm else None

    roblox_folder, roblox_dir = find_roblox_install()
    disk_path = os.environ.get("LOCALAPPDATA", "C:/") if roblox_dir is None else roblox_dir
    disk_free_gb, disk_total_gb, disk_free_percent = _get_disk_info(disk_path[:3] if len(disk_path) >= 3 else "C:/")
    power_plan_guid, power_plan_name = _get_power_plan()

    return SystemSpecs(
        cpu_name=cpu_name,
        cpu_cores=cpu_cores,
        gpu_name=gpu_name,
        gpu_driver_version=gpu_driver_version,
        gpu_driver_date=gpu_driver_date,
        ram_total_gb=ram_total_gb,
        os_caption=_get_os_caption(),
        screen_resolution=_get_screen_resolution(),
        power_plan_guid=power_plan_guid,
        power_plan_name=power_plan_name,
        game_mode_enabled=_get_game_mode_enabled(),
        game_dvr_enabled=_get_game_dvr_enabled(),
        sysmain_running=_get_sysmain_running(),
        disk_free_gb=disk_free_gb,
        disk_total_gb=disk_total_gb,
        disk_free_percent=disk_free_percent,
        roblox_version_folder=roblox_folder,
        roblox_install_dir=roblox_dir,
    )
