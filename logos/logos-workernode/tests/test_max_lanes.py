"""Tests for the MAX_LANES feature (Feature 1).

Validates that the LaneManager respects the max_lanes limit in add_lane(),
apply_lanes(), and _add_lane_unlocked().
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from logos_worker_node.lane_manager import LaneManager, PortAllocator
from logos_worker_node.models import LaneConfig, OllamaConfig, ProcessState, ProcessStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeHandle:
    """Minimal process handle stub that pretends to spawn successfully."""

    def __init__(self, lane_id: str, port: int) -> None:
        self.lane_id = lane_id
        self.port = port
        self.lane_config: LaneConfig | None = None
        self.closed = False
        self.destroyed = False
        self.hf_home_override: str | None = None

    async def init(self) -> None:
        return None

    async def spawn(self, lane_config: LaneConfig) -> ProcessStatus:
        self.lane_config = lane_config
        return ProcessStatus(state=ProcessState.RUNNING, pid=12345)

    async def destroy(self) -> None:
        self.destroyed = True

    async def close(self) -> None:
        self.closed = True

    async def get_loaded_models(self):
        return []

    def status(self) -> ProcessStatus:
        return ProcessStatus(state=ProcessState.RUNNING, pid=12345)


def _patch_create_handle(monkeypatch):
    """Patch _create_handle to return FakeHandle instances."""
    created = []

    def _fake(lid, port, _gc, _vec, _lc):
        h = FakeHandle(lid, port)
        created.append(h)
        return h

    monkeypatch.setattr("logos_worker_node.lane_manager._create_handle", _fake)
    monkeypatch.setattr(PortAllocator, "_is_port_available", staticmethod(lambda _port: True))
    return created


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_lane_respects_max_lanes(monkeypatch) -> None:
    """add_lane() should raise ValueError when MAX_LANES limit is reached."""
    created = _patch_create_handle(monkeypatch)
    manager = LaneManager(
        OllamaConfig(),
        lane_port_start=15000,
        lane_port_end=15010,
        max_lanes=1,
    )

    lane1 = LaneConfig(model="org/model-a", vllm=True)
    await manager.add_lane(lane1)
    assert len(manager.lane_ids) == 1

    lane2 = LaneConfig(model="org/model-b", vllm=True)
    with pytest.raises(ValueError, match="MAX_LANES limit reached"):
        await manager.add_lane(lane2)


@pytest.mark.asyncio
async def test_add_lane_unlimited_when_max_lanes_zero(monkeypatch) -> None:
    """max_lanes=0 means unlimited — should not block additions."""
    _patch_create_handle(monkeypatch)
    manager = LaneManager(
        OllamaConfig(),
        lane_port_start=15000,
        lane_port_end=15010,
        max_lanes=0,
    )

    for i in range(5):
        await manager.add_lane(LaneConfig(model=f"org/model-{i}", vllm=True))
    assert len(manager.lane_ids) == 5


@pytest.mark.asyncio
async def test_apply_lanes_rejects_exceeding_max_lanes(monkeypatch) -> None:
    """apply_lanes() should raise ValueError when desired count > MAX_LANES."""
    _patch_create_handle(monkeypatch)
    manager = LaneManager(
        OllamaConfig(),
        lane_port_start=15000,
        lane_port_end=15010,
        max_lanes=2,
    )

    desired = [
        LaneConfig(model="org/model-a", vllm=True),
        LaneConfig(model="org/model-b", vllm=True),
        LaneConfig(model="org/model-c", vllm=True),
    ]
    with pytest.raises(ValueError, match="exceeds MAX_LANES"):
        await manager.apply_lanes(desired)


@pytest.mark.asyncio
async def test_apply_lanes_within_max_lanes(monkeypatch) -> None:
    """apply_lanes() should succeed when count <= MAX_LANES."""
    _patch_create_handle(monkeypatch)
    manager = LaneManager(
        OllamaConfig(),
        lane_port_start=15000,
        lane_port_end=15010,
        max_lanes=3,
    )

    desired = [
        LaneConfig(model="org/model-a", vllm=True),
        LaneConfig(model="org/model-b", vllm=True),
    ]
    result = await manager.apply_lanes(desired)
    assert result.success


@pytest.mark.asyncio
async def test_max_lanes_default_zero() -> None:
    """Default max_lanes should be 0 (unlimited)."""
    manager = LaneManager(OllamaConfig(), lane_port_start=15000, lane_port_end=15010)
    assert manager._max_lanes == 0
