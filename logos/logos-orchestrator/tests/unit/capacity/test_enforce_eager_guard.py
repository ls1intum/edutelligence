"""The TP>1 enforce_eager guard must yield to calibration evidence.

CUDA graph capture crashes the Marlin MoE kernel on Turing, so the planner
forces enforce_eager for every tensor-parallel lane. Calibration captures
graphs whenever it runs with enforce_eager=False, so a profile that recorded
that mode is a profile whose capture already succeeded on those GPUs — keeping
the guard there serves a configuration that was never measured, and costs ~45%
of decode throughput on RTX 6000 Ada (measured: 15.2 vs 26.7 output tok/s).
"""

from logos.capacity.capacity_planner import CapacityPlanner
from logos.sdi.models import ModelProfile


def _profile(**kw) -> ModelProfile:
    base = dict(model_name="m", engine="vllm", tensor_parallel_size=2)
    base.update(kw)
    return ModelProfile(**base)


def _vllm_config(planner: CapacityPlanner, profile: ModelProfile) -> dict:
    params = planner._build_load_params("m", "lane-1", profile)
    return params.get("vllm_config") or {}


def test_tp_gt_1_forces_enforce_eager_without_evidence() -> None:
    planner = CapacityPlanner.__new__(CapacityPlanner)
    cfg = _vllm_config(planner, _profile(enforce_eager_at_calibration=None))
    assert cfg.get("enforce_eager") is True


def test_tp_gt_1_forces_enforce_eager_when_calibration_used_eager() -> None:
    """Calibration ran eager, so graph capture was never exercised."""
    planner = CapacityPlanner.__new__(CapacityPlanner)
    cfg = _vllm_config(planner, _profile(enforce_eager_at_calibration=True))
    assert cfg.get("enforce_eager") is True


def test_calibration_with_graphs_at_same_tp_lifts_the_guard() -> None:
    planner = CapacityPlanner.__new__(CapacityPlanner)
    cfg = _vllm_config(planner, _profile(enforce_eager_at_calibration=False))
    assert "enforce_eager" not in cfg


def test_evidence_from_a_different_tp_does_not_count() -> None:
    """The crash is tensor-parallel specific, so tp=1 evidence proves nothing.

    The lane must actually be planned at tp>1 for the guard to apply at all, so
    the profile records tp=1 while the planner infers tp=2. Asserting on a
    profile that is simply tp=1 would only show that the guard skips non-TP
    lanes, and a regression in the same-TP check would pass unnoticed.
    """
    planner = CapacityPlanner.__new__(CapacityPlanner)
    planner._infer_tensor_parallel = lambda *a, **kw: 2  # type: ignore[method-assign]
    profile = _profile(tensor_parallel_size=1, enforce_eager_at_calibration=False)
    params = planner._build_load_params("m", "lane-1", profile, capacity=object(), provider_id=1)
    cfg = params.get("vllm_config") or {}
    assert cfg.get("tensor_parallel_size") == 2, "test is meaningless unless the lane is tp>1"
    assert cfg.get("enforce_eager") is True


def test_tp_1_lane_never_gets_the_guard() -> None:
    """A single-GPU lane is outside the guard regardless of calibration."""
    planner = CapacityPlanner.__new__(CapacityPlanner)
    cfg = _vllm_config(planner, _profile(tensor_parallel_size=1))
    assert cfg.get("enforce_eager") is None
