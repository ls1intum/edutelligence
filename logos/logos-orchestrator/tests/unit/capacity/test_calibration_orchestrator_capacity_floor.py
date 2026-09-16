"""CalibrationOrchestrator capacity-floor skip logic (Metal-only).

``_capacity_skip_models`` compares a candidate provider's own working-set
budget (``devices.total_memory_mb``) against the max
``metal_capacity_floor_mb`` recorded for a model anywhere in the cluster,
and skips models the candidate could never fit. It only ever applies to
a Metal candidate (``devices.mode == "metal"``) — a Metal working-set
floor says nothing about CUDA VRAM headroom, and CUDA nodes report their
own nonzero ``total_memory_mb`` too, so the mode check is load-bearing,
not just a case that never occurs in practice.

Same fixture style as the neighbouring GPU-slice tests —
``CalibrationOrchestrator.__new__`` plus fake ``_registry`` / ``_facade``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from logos.capacity.calibration_orchestrator import CalibrationOrchestrator
from logos.sdi.models import ModelProfile


def _snapshot(total_memory_mb: float, mode: str = "metal") -> dict:
    return {"runtime": {"devices": {"total_memory_mb": total_memory_mb, "mode": mode}}}


def _profile(model_name: str, floor_mb: float | None) -> ModelProfile:
    return ModelProfile(model_name=model_name, metal_capacity_floor_mb=floor_mb)


def _orch(*, snapshot, provider_ids, profiles_by_provider):
    orch = CalibrationOrchestrator.__new__(CalibrationOrchestrator)
    registry = MagicMock()
    registry.peek_runtime_snapshot.return_value = snapshot
    facade = MagicMock()
    facade.provider_ids.return_value = provider_ids
    facade.get_model_profiles.side_effect = lambda pid: profiles_by_provider.get(pid, {})
    orch._registry = registry
    orch._facade = facade
    return orch


def test_skips_model_whose_known_floor_meets_this_providers_capacity():
    """Node 1 already failed on model M with an 8000 MB budget — a
    candidate no bigger than that (exactly 8000 MB) must skip M too."""
    orch = _orch(
        snapshot=_snapshot(8_000.0),
        provider_ids=[1, 2],
        profiles_by_provider={1: {"org/model": _profile("org/model", 8_000.0)}},
    )
    assert orch._capacity_skip_models(2) == frozenset({"org/model"})


def test_does_not_skip_model_when_candidate_has_more_capacity():
    orch = _orch(
        snapshot=_snapshot(16_000.0),
        provider_ids=[1, 2],
        profiles_by_provider={1: {"org/model": _profile("org/model", 8_000.0)}},
    )
    assert orch._capacity_skip_models(2) == frozenset()


def test_takes_max_floor_across_every_provider():
    """Escalation: model failed at 8000 MB on node 1 and later also at
    16000 MB on node 2 — the cluster-wide floor is the max, 16000 MB."""
    orch = _orch(
        snapshot=_snapshot(16_000.0),
        provider_ids=[1, 2, 3],
        profiles_by_provider={
            1: {"org/model": _profile("org/model", 8_000.0)},
            2: {"org/model": _profile("org/model", 16_000.0)},
        },
    )
    assert orch._capacity_skip_models(3) == frozenset({"org/model"})


def test_cuda_profiles_never_produce_a_skip():
    """CUDA profiles never set metal_capacity_floor_mb — always empty."""
    orch = _orch(
        snapshot=_snapshot(16_000.0),
        provider_ids=[1, 2],
        profiles_by_provider={1: {"org/model": _profile("org/model", None)}},
    )
    assert orch._capacity_skip_models(2) == frozenset()


def test_empty_when_no_snapshot():
    orch = _orch(snapshot=None, provider_ids=[1], profiles_by_provider={})
    assert orch._capacity_skip_models(2) == frozenset()


def test_empty_when_provider_capacity_unknown():
    orch = _orch(snapshot=_snapshot(0.0), provider_ids=[1], profiles_by_provider={})
    assert orch._capacity_skip_models(2) == frozenset()


def test_ignores_provider_whose_profiles_raise():
    orch = _orch(snapshot=_snapshot(8_000.0), provider_ids=[1, 2], profiles_by_provider={})
    orch._facade.get_model_profiles.side_effect = RuntimeError("offline")
    assert orch._capacity_skip_models(2) == frozenset()


def test_cuda_candidate_is_never_skipped_by_a_metal_floor():
    """Mixed cluster: a Metal node recorded a real floor for a model, and
    the CUDA candidate's own total_memory_mb happens to be smaller than
    it (a Metal working-set number and CUDA VRAM aren't comparable) — the
    CUDA candidate must not be skipped just because it isn't Metal."""
    orch = _orch(
        snapshot=_snapshot(4_000.0, mode="nvidia"),
        provider_ids=[1, 2],
        profiles_by_provider={1: {"org/model": _profile("org/model", 8_000.0)}},
    )
    assert orch._capacity_skip_models(2) == frozenset()


def test_empty_when_candidate_mode_is_unknown():
    orch = _orch(
        snapshot=_snapshot(4_000.0, mode="derived"),
        provider_ids=[1, 2],
        profiles_by_provider={1: {"org/model": _profile("org/model", 8_000.0)}},
    )
    assert orch._capacity_skip_models(2) == frozenset()
