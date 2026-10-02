"""Metal/MLX workers must not enter the phantom-VRAM driver wait.

The phantom-VRAM path in _ensure_request_capacity exists for CUDA workers
whose driver has not yet released the context of a recently-killed process:
zero lanes, VRAM still occupied, and the memory is expected to free itself
within seconds.  It polls for up to 60 s before giving up.

On unified-memory hardware the same numbers (zero lanes, total-minus-free
well above the request) are permanent: the "occupied" figure is the
systemwide wired baseline (kernel, window server, ...) that never frees.
There is no driver context to wait for, so a Metal provider must refuse
immediately instead of adding up to 60 s of latency before the same refusal.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from logos.capacity.capacity_planner import CapacityPlanner
from logos.sdi.models import ModelProfile

PROVIDER_ID = 7


def _planner(*, metal: bool):
    """Planner with one lane-less provider whose VRAM is mostly occupied.

    available=3000 / total=28700 (a wired memory budget) means the phantom
    figure (25700 MB) exceeds half of the 20000 MB the request needs, which
    is what arms the phantom-VRAM wait on a CUDA provider.
    """
    facade = MagicMock()
    facade.get_capacity_info.return_value = SimpleNamespace(
        available_vram_mb=3_000.0,
        total_vram_mb=28_700.0,
    )
    facade.get_all_provider_lane_signals.return_value = []
    facade.get_scheduler_queue_depth_by_model_name.return_value = 0
    facade.get_provider_name.return_value = "worker"

    registry = MagicMock()
    registry.peek_runtime_snapshot.return_value = {"runtime": {"devices": {"mode": "metal" if metal else "cuda"}}}

    demand = MagicMock()
    demand.get_score.return_value = 0.0

    return CapacityPlanner(facade, registry, demand)


def _target():
    return SimpleNamespace(
        lane_id="planner-lane",
        model_name="org/big-model",
        runtime_state="cold",
        gpu_devices=None,
        tensor_parallel_size=None,
        active_requests=0,
        queue_waiting=0,
    )


def _profile():
    # Calibrated: passes the calibration gate, and its loaded footprint is
    # the known 20000 MB (min of base 25000 and observed 20000).
    return ModelProfile(
        model_name="org/big-model",
        engine="vllm",
        residency_source="calibrated",
        base_residency_mb=25_000.0,
        loaded_vram_mb=20_000.0,
        tensor_parallel_size=1,
    )


class _SleptInstead(Exception):
    """Raised in place of the first asyncio.sleep so the test ends fast."""


def _patch_sleep(monkeypatch, sleeps: list[float]) -> None:
    async def fake_sleep(seconds):
        sleeps.append(seconds)
        raise _SleptInstead

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)


@pytest.mark.asyncio
async def test_metal_provider_refuses_immediately_without_phantom_wait(monkeypatch):
    sleeps: list[float] = []
    _patch_sleep(monkeypatch, sleeps)

    planner = _planner(metal=True)

    assert (
        await planner._ensure_request_capacity(
            provider_id=PROVIDER_ID,
            target=_target(),
            profile=_profile(),
            timeout_seconds=30.0,
        )
        is False
    )
    # No wait anywhere on the refusal path — in particular no phantom-VRAM
    # driver polling for the permanent wired baseline.
    assert sleeps == []


@pytest.mark.asyncio
async def test_cuda_provider_still_enters_phantom_wait(monkeypatch):
    sleeps: list[float] = []
    _patch_sleep(monkeypatch, sleeps)

    planner = _planner(metal=False)

    with pytest.raises(_SleptInstead):
        await planner._ensure_request_capacity(
            provider_id=PROVIDER_ID,
            target=_target(),
            profile=_profile(),
            timeout_seconds=30.0,
        )
    # The first sleep on this flow is the phantom path's 2 s poll for the
    # driver to release contexts.
    assert sleeps == [2.0]
