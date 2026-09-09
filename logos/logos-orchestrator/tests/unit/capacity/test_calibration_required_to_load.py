"""No model may be loaded before it has been calibrated here.

Except on Metal/MLX providers, where calibration is impossible by
design — they run on operator-provided override profiles instead.
"""

from __future__ import annotations

from types import SimpleNamespace

from logos.capacity.capacity_planner import CapacityPlanner
from logos.sdi.models import ModelProfile


def _planner(*, metal: bool = False) -> CapacityPlanner:
    planner = CapacityPlanner.__new__(CapacityPlanner)
    snapshot = {"runtime": {"devices": {"mode": "metal"}}} if metal else None
    planner._registry = SimpleNamespace(peek_runtime_snapshot=lambda provider_id: snapshot)
    return planner


def _profile(residency_source: str, base_residency_mb: float = 4000.0) -> ModelProfile:
    return ModelProfile(
        model_name="org/model-a",
        engine="vllm",
        residency_source=residency_source,
        base_residency_mb=base_residency_mb,
    )


class TestProviderIsMetal:
    def test_no_registry_means_not_metal(self):
        planner = CapacityPlanner.__new__(CapacityPlanner)
        planner._registry = None
        assert planner._provider_is_metal(1) is False

    def test_no_snapshot_means_not_metal(self):
        assert _planner(metal=False)._provider_is_metal(1) is False

    def test_metal_device_mode_is_detected(self):
        assert _planner(metal=True)._provider_is_metal(1) is True

    def test_none_provider_id_is_not_metal(self):
        assert _planner(metal=True)._provider_is_metal(None) is False


class TestLoadRequiresCalibration:
    def test_calibrated_never_requires_it(self):
        assert _planner()._load_requires_calibration(_profile("calibrated"), 1) is False

    def test_measured_never_requires_it(self):
        assert _planner()._load_requires_calibration(_profile("measured"), 1) is False

    def test_override_requires_it_on_cuda(self):
        assert _planner()._load_requires_calibration(_profile("override"), 1) is True

    def test_override_is_exempt_on_metal(self):
        planner = _planner(metal=True)
        assert planner._load_requires_calibration(_profile("override"), 1) is False

    def test_hf_precheck_requires_it_on_cuda(self):
        """A compatibility-precheck estimate is not a calibration run."""
        assert _planner()._load_requires_calibration(_profile("hf"), 1) is True

    def test_cached_requires_it_on_cuda(self):
        """A profile reloaded from disk with no recorded source is unproven."""
        assert _planner()._load_requires_calibration(_profile("cached"), 1) is True

    def test_no_profile_requires_it_on_cuda(self):
        assert _planner()._load_requires_calibration(None, 1) is True

    def test_no_profile_is_exempt_on_metal(self):
        planner = _planner(metal=True)
        assert planner._load_requires_calibration(None, 1) is False


class TestFeasibilityGateRequiresCalibration:
    """``_passes_minimum_load_feasibility`` refuses a never-calibrated load."""

    def _capacity(self):
        return SimpleNamespace(available_vram_mb=80_000.0)

    def test_rejects_hf_precheck_profile_on_cuda(self):
        planner = _planner(metal=False)
        planner.get_pending_vram_mb = lambda pid: 0.0
        ok = planner._passes_minimum_load_feasibility("org/model-a", _profile("hf"), self._capacity(), provider_id=1)
        assert ok is False

    def test_rejects_model_with_no_profile_on_cuda(self):
        planner = _planner(metal=False)
        planner.get_pending_vram_mb = lambda pid: 0.0
        ok = planner._passes_minimum_load_feasibility("org/model-a", None, self._capacity(), provider_id=1)
        assert ok is False

    def test_accepts_override_profile_on_metal(self):
        planner = _planner(metal=True)
        planner.get_pending_vram_mb = lambda pid: 0.0
        ok = planner._passes_minimum_load_feasibility(
            "org/model-a", _profile("override", base_residency_mb=2000.0), self._capacity(), provider_id=1
        )
        assert ok is True

    def test_rejects_model_with_no_profile_even_on_metal(self):
        """Metal is exempt from calibration, not from having a profile at
        all — a missing override is refused, not guessed from the name."""
        planner = _planner(metal=True)
        planner.get_pending_vram_mb = lambda pid: 0.0
        # "70B" would match the disk-size-from-name heuristic if it were
        # still consulted here — it must not be.
        ok = planner._passes_minimum_load_feasibility("org/model-70B", None, self._capacity(), provider_id=1)
        assert ok is False
