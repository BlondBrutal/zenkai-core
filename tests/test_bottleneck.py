"""
Tests (pytest) de la détection du composant limitant (features/performance/
bottleneck.py) — dataclasses pures, aucun mock nécessaire.
"""
from features.performance.bottleneck import (
    HIGH_CPU_PERCENT, HIGH_GPU_PERCENT, HIGH_RAM_PERCENT, LOW_CORE_COUNT, LOW_RAM_GB,
    detect_bottleneck, recommend_fastflags_preset,
)
from features.performance.live_monitor import LiveSample
from features.performance.system_info import SystemSpecs


def _healthy_live(**overrides) -> LiveSample:
    base = dict(
        cpu_percent=20.0, ram_percent=40.0, ram_used_gb=6.0, ram_total_gb=16.0,
        gpu_percent=10.0, gpu_available=True, disk_read_mbps=1.0, disk_write_mbps=1.0,
        net_download_kbps=100.0, net_upload_kbps=50.0, battery_percent=None, battery_available=False,
    )
    base.update(overrides)
    return LiveSample(**base)


def test_no_bottleneck_when_everything_healthy():
    specs = SystemSpecs(ram_total_gb=16.0, cpu_cores=8, disk_free_percent=50.0, disk_free_gb=200.0)
    result = detect_bottleneck(specs, _healthy_live())
    assert result.component is None
    assert result.reason_key == "performance.bottleneck.none"


def test_no_bottleneck_with_no_live_sample_and_healthy_specs():
    specs = SystemSpecs(ram_total_gb=16.0, cpu_cores=8, disk_free_percent=50.0, disk_free_gb=200.0)
    result = detect_bottleneck(specs, None)
    assert result.component is None


def test_low_total_ram_flagged_even_without_live_sample():
    specs = SystemSpecs(ram_total_gb=4.0)
    result = detect_bottleneck(specs, None)
    assert result.component == "ram"
    assert result.reason_key == "performance.bottleneck.ram_low_total"


def test_high_ram_usage_flagged_when_total_is_fine():
    specs = SystemSpecs(ram_total_gb=16.0)
    live = _healthy_live(ram_percent=HIGH_RAM_PERCENT + 5)
    result = detect_bottleneck(specs, live)
    assert result.component == "ram"
    assert result.reason_key == "performance.bottleneck.ram_high_usage"


def test_high_cpu_usage_flagged():
    specs = SystemSpecs(ram_total_gb=16.0, cpu_cores=8)
    live = _healthy_live(cpu_percent=HIGH_CPU_PERCENT + 10)
    result = detect_bottleneck(specs, live)
    assert result.component == "cpu"
    assert result.reason_key == "performance.bottleneck.cpu_high_usage"


def test_low_core_count_flagged_without_live_cpu_spike():
    specs = SystemSpecs(cpu_cores=LOW_CORE_COUNT - 2)
    result = detect_bottleneck(specs, None)
    assert result.component == "cpu"
    assert result.reason_key == "performance.bottleneck.cpu_low_cores"


def test_high_gpu_usage_flagged_only_when_gpu_available():
    specs = SystemSpecs()
    live_unavailable = _healthy_live(gpu_percent=HIGH_GPU_PERCENT + 10, gpu_available=False)
    assert detect_bottleneck(specs, live_unavailable).component is None

    live_available = _healthy_live(gpu_percent=HIGH_GPU_PERCENT + 10, gpu_available=True)
    result = detect_bottleneck(specs, live_available)
    assert result.component == "gpu"


def test_critical_disk_space_outranks_low_disk_space():
    specs = SystemSpecs(disk_free_percent=2.0, disk_free_gb=5.0)
    result = detect_bottleneck(specs, None)
    assert result.component == "disk"
    assert result.reason_key == "performance.bottleneck.disk_critical_space"


def test_low_disk_space_flagged_below_15_percent():
    specs = SystemSpecs(disk_free_percent=10.0, disk_free_gb=50.0)
    result = detect_bottleneck(specs, None)
    assert result.component == "disk"
    assert result.reason_key == "performance.bottleneck.disk_low_space"


def test_most_severe_candidate_wins():
    # RAM totale très faible (grosse sévérité, +10 offset) doit l'emporter
    # sur un CPU légèrement au-dessus du seuil.
    specs = SystemSpecs(ram_total_gb=2.0, cpu_cores=8)
    live = _healthy_live(cpu_percent=HIGH_CPU_PERCENT + 1)
    result = detect_bottleneck(specs, live)
    assert result.component == "ram"


class TestRecommendFastflagsPreset:
    def test_recommends_hard_when_cpu_bottleneck(self):
        specs = SystemSpecs(ram_total_gb=16.0)
        from features.performance.bottleneck import BottleneckResult
        bottleneck = BottleneckResult(component="cpu", reason_key="x", reason_kwargs={})
        assert recommend_fastflags_preset(specs, bottleneck) == "hard"

    def test_recommends_hard_when_gpu_bottleneck(self):
        specs = SystemSpecs(ram_total_gb=16.0)
        from features.performance.bottleneck import BottleneckResult
        bottleneck = BottleneckResult(component="gpu", reason_key="x", reason_kwargs={})
        assert recommend_fastflags_preset(specs, bottleneck) == "hard"

    def test_recommends_hard_when_low_ram_even_without_cpu_gpu_bottleneck(self):
        specs = SystemSpecs(ram_total_gb=LOW_RAM_GB - 1)
        from features.performance.bottleneck import BottleneckResult
        bottleneck = BottleneckResult(component="disk", reason_key="x", reason_kwargs={})
        assert recommend_fastflags_preset(specs, bottleneck) == "hard"

    def test_recommends_balanced_otherwise(self):
        specs = SystemSpecs(ram_total_gb=16.0)
        from features.performance.bottleneck import BottleneckResult
        bottleneck = BottleneckResult(component=None, reason_key="x", reason_kwargs={})
        assert recommend_fastflags_preset(specs, bottleneck) == "balanced"
