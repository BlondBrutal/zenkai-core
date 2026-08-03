"""
Orchestration du scan de diagnostic Performance : rassemble les specs,
construit les cartes de statut, détecte le composant limitant et calcule
le preset Fast Flags recommandé. Tourne dans un QThread séparé (les appels
WMI/subprocess peuvent prendre quelques centaines de ms, jamais dans le
thread UI). N'importe rien du système de traduction : émet des identifiants
d'étape bruts, à traduire côté UI (même convention que features/license).
"""
from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from features.performance.bottleneck import BottleneckResult, detect_bottleneck, recommend_fastflags_preset
from features.performance.live_monitor import LiveSample
from features.performance.status_cards import StatusCard, build_status_cards
from features.performance.system_info import SystemSpecs, gather_system_specs


@dataclass
class ScanResult:
    specs: SystemSpecs
    cards: list[StatusCard]
    bottleneck: BottleneckResult
    recommended_preset: str


class PerformanceScanWorker(QThread):
    progress = pyqtSignal(str)  # "system" | "finalize"
    finished_scan = pyqtSignal(object)  # ScanResult

    def __init__(self, live_snapshot: Optional[LiveSample], parent=None):
        super().__init__(parent)
        self._live_snapshot = live_snapshot

    def run(self) -> None:
        self.progress.emit("system")
        specs = gather_system_specs()

        self.progress.emit("finalize")
        cards = build_status_cards(specs)
        bottleneck = detect_bottleneck(specs, self._live_snapshot)
        preset = recommend_fastflags_preset(specs, bottleneck)

        self.finished_scan.emit(ScanResult(specs=specs, cards=cards, bottleneck=bottleneck, recommended_preset=preset))
