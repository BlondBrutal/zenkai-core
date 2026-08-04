"""
Monitoring des performances en direct (CPU, RAM, GPU, disque). Tourne dans
un QThread séparé, rafraîchissement ~3x/seconde (CPU/RAM/disque) tant que
la page Performance est affichée et activée.

Le GPU est interrogé moins souvent que le reste : GPUtil relance un vrai
sous-processus nvidia-smi.exe à chaque appel (voir _read_gpu_load), donc le
faire 3x/seconde serait tout sauf léger. On le rafraîchit à ~1x/seconde en
réutilisant la dernière valeur connue entre-temps.
"""
import logging
import time
from dataclasses import dataclass
from typing import Optional

import psutil
from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger("zenkaiontop.performance")

_SAMPLE_INTERVAL_SECONDS = 0.3  # ~3.3 Hz : réactif sans polling agressif
_GPU_QUERY_EVERY_N_TICKS = round(1.0 / _SAMPLE_INTERVAL_SECONDS)  # ~1x/seconde
_ROLLING_WINDOW = round(8 / _SAMPLE_INTERVAL_SECONDS)  # ~8 secondes de moyenne glissante


@dataclass
class LiveSample:
    cpu_percent: float
    ram_percent: float
    ram_used_gb: float
    ram_total_gb: float
    gpu_percent: Optional[float]  # None si aucun GPU compatible (GPUtil = NVIDIA uniquement)
    gpu_available: bool
    disk_read_mbps: float
    disk_write_mbps: float
    net_download_kbps: float
    net_upload_kbps: float
    battery_percent: Optional[float]  # None si aucune batterie détectée (PC de bureau)
    battery_available: bool


class LiveMonitorThread(QThread):
    sample_ready = pyqtSignal(object)  # LiveSample

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._recent_samples: list[LiveSample] = []

    def run(self) -> None:
        self._running = True
        # Premier appel cpu_percent() : toujours 0.0, sert juste à amorcer la mesure suivante.
        psutil.cpu_percent(interval=None)
        last_io = _safe_disk_io_counters()
        last_net = _safe_net_io_counters()
        last_time = time.monotonic()
        gpu_percent, gpu_available = _read_gpu_load()
        tick = 0

        while self._running:
            time.sleep(_SAMPLE_INTERVAL_SECONDS)
            if not self._running:
                break

            now = time.monotonic()
            elapsed = max(now - last_time, 0.001)

            cpu_percent = psutil.cpu_percent(interval=None)
            vm = psutil.virtual_memory()

            current_io = _safe_disk_io_counters()
            read_mbps = write_mbps = 0.0
            if current_io is not None and last_io is not None:
                read_mbps = (current_io.read_bytes - last_io.read_bytes) / elapsed / 1024**2
                write_mbps = (current_io.write_bytes - last_io.write_bytes) / elapsed / 1024**2
            last_io = current_io

            current_net = _safe_net_io_counters()
            download_kbps = upload_kbps = 0.0
            if current_net is not None and last_net is not None:
                download_kbps = (current_net.bytes_recv - last_net.bytes_recv) / elapsed / 1024
                upload_kbps = (current_net.bytes_sent - last_net.bytes_sent) / elapsed / 1024
            last_net = current_net
            last_time = now

            tick += 1
            if tick % _GPU_QUERY_EVERY_N_TICKS == 0:
                gpu_percent, gpu_available = _read_gpu_load()

            # Lecture directe (pas de restriction de fréquence type GPU) :
            # psutil.sensors_battery() est un simple appel WMI/registre quasi
            # instantané, pas un sous-processus relancé à chaque fois.
            battery_percent, battery_available = _read_battery()

            sample = LiveSample(
                cpu_percent=round(cpu_percent, 1),
                ram_percent=round(vm.percent, 1),
                ram_used_gb=round(vm.used / 1024**3, 1),
                ram_total_gb=round(vm.total / 1024**3, 1),
                gpu_percent=gpu_percent,
                gpu_available=gpu_available,
                disk_read_mbps=round(max(read_mbps, 0.0), 1),
                disk_write_mbps=round(max(write_mbps, 0.0), 1),
                net_download_kbps=round(max(download_kbps, 0.0), 1),
                net_upload_kbps=round(max(upload_kbps, 0.0), 1),
                battery_percent=battery_percent,
                battery_available=battery_available,
            )
            self._recent_samples.append(sample)
            if len(self._recent_samples) > _ROLLING_WINDOW:
                self._recent_samples.pop(0)

            self.sample_ready.emit(sample)

    def stop(self) -> None:
        self._running = False

    def average_sample(self) -> Optional[LiveSample]:
        """Moyenne glissante des dernières secondes, utilisée par le scan de
        diagnostic pour évaluer le composant limitant sur une base stable
        plutôt qu'un instantané qui peut être bruité."""
        if not self._recent_samples:
            return None
        n = len(self._recent_samples)
        gpu_values = [s.gpu_percent for s in self._recent_samples if s.gpu_percent is not None]
        return LiveSample(
            cpu_percent=round(sum(s.cpu_percent for s in self._recent_samples) / n, 1),
            ram_percent=round(sum(s.ram_percent for s in self._recent_samples) / n, 1),
            ram_used_gb=self._recent_samples[-1].ram_used_gb,
            ram_total_gb=self._recent_samples[-1].ram_total_gb,
            gpu_percent=round(sum(gpu_values) / len(gpu_values), 1) if gpu_values else None,
            gpu_available=self._recent_samples[-1].gpu_available,
            disk_read_mbps=round(sum(s.disk_read_mbps for s in self._recent_samples) / n, 1),
            disk_write_mbps=round(sum(s.disk_write_mbps for s in self._recent_samples) / n, 1),
            net_download_kbps=round(sum(s.net_download_kbps for s in self._recent_samples) / n, 1),
            net_upload_kbps=round(sum(s.net_upload_kbps for s in self._recent_samples) / n, 1),
            battery_percent=self._recent_samples[-1].battery_percent,
            battery_available=self._recent_samples[-1].battery_available,
        )


def _safe_disk_io_counters():
    try:
        return psutil.disk_io_counters()
    except Exception as exc:
        logger.warning("disk_io_counters indisponible (%s)", exc)
        return None


def _safe_net_io_counters():
    try:
        return psutil.net_io_counters()
    except Exception as exc:
        logger.warning("net_io_counters indisponible (%s)", exc)
        return None


def _read_battery() -> tuple[Optional[float], bool]:
    try:
        battery = psutil.sensors_battery()
        if battery is None:
            return None, False
        return round(battery.percent, 1), True
    except Exception as exc:
        logger.warning("sensors_battery indisponible (%s)", exc)
        return None, False


def _read_gpu_load() -> tuple[Optional[float], bool]:
    try:
        import GPUtil
        gpus = GPUtil.getGPUs()
        if not gpus:
            return None, False
        return round(gpus[0].load * 100, 1), True
    except Exception as exc:
        logger.warning("GPUtil indisponible (%s)", exc)
        return None, False
