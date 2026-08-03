"""
Détection du composant limitant (CPU / GPU / RAM / Disque) à partir des
specs statiques et d'un échantillon de mesures en direct, plus
recommandation du preset Fast Flags le plus adapté.

Logique volontairement simple et transparente (pas de boîte noire) :
chaque composant est évalué contre un seuil documenté ; le composant qui
dépasse son seuil le plus sévèrement est désigné comme limitant. Si aucun
seuil n'est dépassé, on l'affirme honnêtement plutôt que d'inventer un
coupable.
"""
from dataclasses import dataclass
from typing import Optional

from features.performance.live_monitor import LiveSample
from features.performance.system_info import SystemSpecs

LOW_RAM_GB = 8.0
HIGH_CPU_PERCENT = 80.0
HIGH_GPU_PERCENT = 85.0
HIGH_RAM_PERCENT = 85.0
LOW_CORE_COUNT = 4


@dataclass
class BottleneckResult:
    component: Optional[str]  # "cpu" | "gpu" | "ram" | "disk" | None
    reason_key: str
    reason_kwargs: dict


def detect_bottleneck(specs: SystemSpecs, live: Optional[LiveSample]) -> BottleneckResult:
    candidates: list[tuple[str, float, str, dict]] = []  # (component, severity, reason_key, kwargs)

    if specs.ram_total_gb is not None and specs.ram_total_gb < LOW_RAM_GB:
        severity = LOW_RAM_GB - specs.ram_total_gb + 10  # priorité forte : limite matérielle, pas juste un pic
        candidates.append(("ram", severity, "performance.bottleneck.ram_low_total", {"total": specs.ram_total_gb}))
    elif live is not None and live.ram_percent > HIGH_RAM_PERCENT:
        candidates.append(("ram", live.ram_percent - HIGH_RAM_PERCENT, "performance.bottleneck.ram_high_usage", {"percent": live.ram_percent}))

    if live is not None and live.cpu_percent > HIGH_CPU_PERCENT:
        candidates.append(("cpu", live.cpu_percent - HIGH_CPU_PERCENT, "performance.bottleneck.cpu_high_usage", {"percent": live.cpu_percent}))
    elif specs.cpu_cores is not None and specs.cpu_cores < LOW_CORE_COUNT:
        candidates.append(("cpu", (LOW_CORE_COUNT - specs.cpu_cores) * 5, "performance.bottleneck.cpu_low_cores", {"cores": specs.cpu_cores}))

    if live is not None and live.gpu_available and live.gpu_percent is not None and live.gpu_percent > HIGH_GPU_PERCENT:
        candidates.append(("gpu", live.gpu_percent - HIGH_GPU_PERCENT, "performance.bottleneck.gpu_high_usage", {"percent": live.gpu_percent}))

    if specs.disk_free_percent is not None and specs.disk_free_percent < 5:
        candidates.append(("disk", 5 - specs.disk_free_percent + 10, "performance.bottleneck.disk_critical_space", {"free_gb": specs.disk_free_gb}))
    elif specs.disk_free_percent is not None and specs.disk_free_percent < 15:
        candidates.append(("disk", 15 - specs.disk_free_percent, "performance.bottleneck.disk_low_space", {"free_gb": specs.disk_free_gb}))

    if not candidates:
        return BottleneckResult(component=None, reason_key="performance.bottleneck.none", reason_kwargs={})

    component, _, reason_key, reason_kwargs = max(candidates, key=lambda c: c[1])
    return BottleneckResult(component=component, reason_key=reason_key, reason_kwargs=reason_kwargs)


def recommend_fastflags_preset(specs: SystemSpecs, bottleneck: BottleneckResult) -> str:
    """Retourne "hard" ou "balanced". Le preset "Hard" (optimisation max) est
    recommandé si le PC a un point faible clair (CPU/GPU limitant, ou RAM
    sous 8 Go) ; sinon "Balanced" suffit."""
    if bottleneck.component in ("cpu", "gpu"):
        return "hard"
    if specs.ram_total_gb is not None and specs.ram_total_gb < LOW_RAM_GB:
        return "hard"
    return "balanced"
