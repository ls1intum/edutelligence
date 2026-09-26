"""Per-lane status TTL cache .

Every request used to pay a full lane status build (three HTTP probes against
the lane) on the hot path. The TTL cache serves steady-state re-acquires from
cache, rebuilds after expiry, and is cleared by any lifecycle event (which is
what calls _mark_status_dirty). A dead process is never masked by a cached
status: the cheap synchronous process check is consulted on every call.
"""

from __future__ import annotations

from typing import Any

import pytest

from logos_worker_node.lane_manager import LaneManager
from logos_worker_node.models import LaneConfig, ProcessState, ProcessStatus, VllmConfig, WorkerConfig


class CountingHandle:
    """Minimal handle whose model probe counts the status builds."""

    def __init__(self, lane_id: str, port: int, lane: LaneConfig, running: bool = True) -> None:
        self.lane_id = lane_id
        self.port = port
        self.lane_config = lane
        self.running = running
        self.model_probe_count = 0

    def status(self) -> ProcessStatus:
        state = ProcessState.RUNNING if self.running else ProcessState.STOPPED
        # pid=None: skips the nvidia-smi VRAM map and the /proc host-RAM walk.
        return ProcessStatus(state=state, pid=None)

    async def get_loaded_models(self) -> list[dict[str, Any]]:
        self.model_probe_count += 1
        return [{"name": self.lane_config.model, "size": 0, "size_vram": 0}]

    async def is_sleeping(self) -> bool | None:
        return False


def _manager() -> LaneManager:
    return LaneManager(WorkerConfig(), lane_port_start=15100, lane_port_end=15110)


def _inject(manager: LaneManager, running: bool = True) -> tuple[str, CountingHandle]:
    lane_id = "bench-model"
    lane = LaneConfig(model="bench-model", vllm=True, vllm_config=VllmConfig(enable_sleep_mode=True))
    handle = CountingHandle(lane_id, 15100, lane, running=running)
    manager._handles[lane_id] = handle  # noqa: SLF001
    return lane_id, handle


@pytest.mark.asyncio
async def test_second_acquire_within_ttl_skips_the_probe_build() -> None:
    manager = _manager()
    lane_id, handle = _inject(manager)

    first = await manager._get_status_unlocked(lane_id)  # noqa: SLF001
    second = await manager._get_status_unlocked(lane_id)  # noqa: SLF001

    assert handle.model_probe_count == 1
    assert second is first  # the cached object itself, not a rebuild


@pytest.mark.asyncio
async def test_expired_entry_is_rebuilt() -> None:
    manager = _manager()
    lane_id, handle = _inject(manager)

    first = await manager._get_status_unlocked(lane_id)  # noqa: SLF001
    built_at, _ = manager._lane_status_cache[lane_id]  # noqa: SLF001
    manager._lane_status_cache[lane_id] = (  # noqa: SLF001
        built_at - manager._lane_status_ttl_seconds - 1.0,
        first,
    )

    second = await manager._get_status_unlocked(lane_id)  # noqa: SLF001

    assert handle.model_probe_count == 2
    assert second is not first


@pytest.mark.asyncio
async def test_dirty_mark_clears_the_cache() -> None:
    """A lifecycle event (add/sleep/wake/remove/crash) may have changed
    anything a cached status says — the whole cache must go with it."""
    manager = _manager()
    lane_id, handle = _inject(manager)

    await manager._get_status_unlocked(lane_id)  # noqa: SLF001
    manager._mark_status_dirty()
    await manager._get_status_unlocked(lane_id)  # noqa: SLF001

    assert handle.model_probe_count == 2


@pytest.mark.asyncio
async def test_dead_process_is_never_served_from_cache() -> None:
    manager = _manager()
    lane_id, handle = _inject(manager)

    cached = await manager._get_status_unlocked(lane_id)  # noqa: SLF001
    handle.running = False  # process died after the entry was cached

    status = await manager._get_status_unlocked(lane_id)  # noqa: SLF001

    # A fresh build, not the cached RUNNING status (the rebuild of a dead
    # lane legitimately probes nothing — the lane is down).
    assert status is not cached
    assert status.runtime_state == "stopped"


@pytest.mark.asyncio
async def test_zero_ttl_builds_every_call() -> None:
    """LOGOS_LANE_STATUS_TTL_S=0 is the documented legacy behaviour."""
    manager = _manager()
    lane_id, handle = _inject(manager)
    manager._lane_status_ttl_seconds = 0.0  # noqa: SLF001

    await manager._get_status_unlocked(lane_id)  # noqa: SLF001
    await manager._get_status_unlocked(lane_id)  # noqa: SLF001

    assert handle.model_probe_count == 2
    assert manager._lane_status_cache == {}
