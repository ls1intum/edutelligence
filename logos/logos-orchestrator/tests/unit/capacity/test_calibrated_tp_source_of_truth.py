"""The calibrated tensor_parallel_size is the single source of truth (issue #616).

The size-vs-VRAM inference reads ``base_residency_mb`` against one GPU's 85%
threshold. For a calibrated profile that value is the FULL awake footprint
(weights + KV), often most of a GPU, so the inference escalates a calibrated
TP=1 to a higher TP — and the worker then re-persists that escalated TP over
the calibrated profile, leaving a split-brain (TP=1 KV data under a TP=2
tensor_parallel_size). The planner must never re-infer TP for a calibrated
profile; the calibrator's verdict wins.
"""

from __future__ import annotations

from types import SimpleNamespace

from logos.capacity.capacity_planner import CapacityPlanner
from logos.sdi.models import ModelProfile


def _planner() -> CapacityPlanner:
    return CapacityPlanner.__new__(CapacityPlanner)


class _FakeRegistry:
    def __init__(self, device_count: int) -> None:
        self._devices = [{"index": i} for i in range(device_count)]

    def peek_runtime_snapshot(self, provider_id: int) -> dict:
        return {"runtime": {"devices": {"devices": self._devices}}}


# 2 x 50 GB GPU node, as in the issue's Phi-4-reasoning setup.
def _capacity() -> SimpleNamespace:
    return SimpleNamespace(total_vram_mb=100_000.0)


def _calibrated_profile(tp: int) -> ModelProfile:
    # Full-footprint base residency (weights + KV) — large enough that the
    # size heuristic would escalate to tp=2 on this node.
    return ModelProfile(
        model_name="ms/Phi-4-reasoning",
        engine="vllm",
        tensor_parallel_size=tp,
        residency_source="calibrated",
        base_residency_mb=46_000.0,
        kv_cache_to_max_model_len_pairs=[{"kv_mb": 2048.0, "max_model_len": 5232}],
    )


def test_infer_never_escalates_a_calibrated_tp1() -> None:
    """A calibrated TP=1 is proven by a real probe — no re-inference."""
    planner = _planner()
    assert planner._infer_tensor_parallel(_calibrated_profile(tp=1), _capacity(), 1) == 1


def test_infer_returns_the_calibrated_tp() -> None:
    planner = _planner()
    assert planner._infer_tensor_parallel(_calibrated_profile(tp=2), _capacity(), 1) == 2


def test_infer_still_infers_for_uncalibrated_profiles() -> None:
    """The guard only suppresses inference for calibrated profiles."""
    planner = _planner()
    planner._registry = _FakeRegistry(device_count=2)  # noqa: SLF001
    profile = ModelProfile(
        model_name="big-model/70B",
        engine="vllm",
        base_residency_mb=46_000.0,
    )
    assert planner._infer_tensor_parallel(profile, _capacity(), 1) == 2


def test_load_params_keep_a_calibrated_tp1_on_one_gpu() -> None:
    """The lane request must not carry an inferred TP for a calibrated TP=1.

    This is the upstream half of issue #616: the orchestrator sent tp=2 for
    Phi-4-reasoning because it re-inferred off the full-footprint base
    residency, and the worker then persisted tp=2 over the calibrated profile.
    """
    planner = _planner()
    planner._registry = _FakeRegistry(device_count=2)  # noqa: SLF001
    planner._estimate_available_for_kv_mb = lambda p, c, pid, tp: 4000.0
    params = planner._build_load_params(
        "ms/Phi-4-reasoning", "lane-1", _calibrated_profile(tp=1), capacity=_capacity(), provider_id=1
    )
    cfg = params.get("vllm_config") or {}
    assert cfg.get("tensor_parallel_size") is None  # tp stays 1
    # The calibrated KV pair is still what the lane gets.
    assert cfg.get("max_model_len") == 5232


def test_load_params_send_a_calibrated_tp2() -> None:
    """A calibrated TP>1 keeps being sent as before."""
    planner = _planner()
    planner._estimate_available_for_kv_mb = lambda p, c, pid, tp: 4000.0
    params = planner._build_load_params(
        "ms/Phi-4-reasoning", "lane-1", _calibrated_profile(tp=2), capacity=_capacity(), provider_id=1
    )
    cfg = params.get("vllm_config") or {}
    assert cfg.get("tensor_parallel_size") == 2
