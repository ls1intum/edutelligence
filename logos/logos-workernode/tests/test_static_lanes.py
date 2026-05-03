"""Tests for the static lanes feature.

Static lanes are defined in config.yml with pinned GPU devices and are always
active — the capacity planner can never remove them.
"""

from __future__ import annotations

import pytest

from logos_worker_node.lane_manager import LaneManager, PortAllocator, _lane_id_from_config
from logos_worker_node.models import (
    AppConfig,
    LaneConfig,
    LaneStatus,
    OllamaConfig,
    ProcessState,
    ProcessStatus,
    VllmConfig,
)


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
async def test_static_lanes_survive_apply_lanes(monkeypatch) -> None:
    """Static lane must not be removed when the planner sends apply_lanes without it."""
    _patch_create_handle(monkeypatch)
    manager = LaneManager(
        OllamaConfig(),
        lane_port_start=15000,
        lane_port_end=15020,
        max_lanes=3,
    )

    static_lane = LaneConfig(model="org/static-model", vllm=True)
    static_lid = _lane_id_from_config(static_lane)
    dynamic_lane = LaneConfig(model="org/dynamic-model", vllm=True)
    dynamic_lid = _lane_id_from_config(dynamic_lane)

    # Register and apply the static lane
    manager.register_static_lanes({static_lid})
    result = await manager.apply_lanes([static_lane])
    assert result.success
    assert static_lid in manager.lane_ids

    # Now the planner sends apply_lanes with only a dynamic lane (no static lane)
    result2 = await manager.apply_lanes([dynamic_lane])
    assert result2.success

    # Static lane must still be running
    assert static_lid in manager.lane_ids
    # Dynamic lane must also be running
    assert dynamic_lid in manager.lane_ids


@pytest.mark.asyncio
async def test_static_lane_cannot_be_removed(monkeypatch) -> None:
    """remove_lane() must raise ValueError for a static lane."""
    _patch_create_handle(monkeypatch)
    manager = LaneManager(
        OllamaConfig(),
        lane_port_start=15000,
        lane_port_end=15010,
    )

    static_lane = LaneConfig(model="org/static-model", vllm=True)
    static_lid = _lane_id_from_config(static_lane)
    manager.register_static_lanes({static_lid})
    await manager.add_lane(static_lane)

    with pytest.raises(ValueError, match="Cannot remove static lane"):
        await manager.remove_lane(static_lid)

    # Lane must still exist
    assert static_lid in manager.lane_ids


@pytest.mark.asyncio
async def test_static_lane_status_has_is_static_flag(monkeypatch) -> None:
    """LaneStatus.is_static must be True for static lanes and False for dynamic lanes."""
    manager = LaneManager(
        OllamaConfig(gpu_devices="all"),
        lane_port_start=15001,
        lane_port_end=15010,
    )

    static_lane_config = LaneConfig(
        model="org/static-model",
        vllm=True,
        vllm_config=VllmConfig(),
    )
    static_lid = _lane_id_from_config(static_lane_config)
    manager.register_static_lanes({static_lid})

    dynamic_lane_config = LaneConfig(
        model="org/dynamic-model",
        vllm=True,
        vllm_config=VllmConfig(),
    )
    dynamic_lid = _lane_id_from_config(dynamic_lane_config)

    # Create fake handles for both lanes
    static_handle = FakeHandle(static_lid, 15001)
    static_handle.lane_config = static_lane_config
    dynamic_handle = FakeHandle(dynamic_lid, 15002)
    dynamic_handle.lane_config = dynamic_lane_config

    manager._handles[static_lid] = static_handle  # noqa: SLF001
    manager._handles[dynamic_lid] = dynamic_handle  # noqa: SLF001

    static_status = await manager._build_lane_status(static_handle, pid_vram_map={})  # noqa: SLF001
    dynamic_status = await manager._build_lane_status(dynamic_handle, pid_vram_map={})  # noqa: SLF001

    assert static_status.is_static is True
    assert dynamic_status.is_static is False


def test_static_lanes_config_parsing() -> None:
    """AppConfig should parse static_lanes correctly."""
    raw = {
        "static_lanes": [
            {
                "model": "Qwen/Qwen2.5-Coder-7B-Instruct-AWQ",
                "vllm": True,
                "gpu_devices": "0",
                "vllm_config": {
                    "tensor_parallel_size": 1,
                    "kv_cache_memory_bytes": "4G",
                    "quantization": "awq",
                },
            },
            {
                "model": "meta-llama/Llama-3.1-8B-Instruct",
                "vllm": True,
                "gpu_devices": "1",
            },
        ]
    }
    cfg = AppConfig(**raw)
    assert len(cfg.static_lanes) == 2
    assert cfg.static_lanes[0].model == "Qwen/Qwen2.5-Coder-7B-Instruct-AWQ"
    assert cfg.static_lanes[0].vllm is True
    assert cfg.static_lanes[0].gpu_devices == "0"
    assert cfg.static_lanes[0].vllm_config is not None
    assert cfg.static_lanes[0].vllm_config.quantization == "awq"
    assert cfg.static_lanes[1].model == "meta-llama/Llama-3.1-8B-Instruct"
    assert cfg.static_lanes[1].gpu_devices == "1"


def test_static_lanes_config_default_empty() -> None:
    """AppConfig.static_lanes defaults to an empty list."""
    cfg = AppConfig()
    assert cfg.static_lanes == []


def test_is_static_lane_method() -> None:
    """LaneManager.is_static_lane() returns correct values."""
    manager = LaneManager(OllamaConfig(), lane_port_start=15000, lane_port_end=15010)
    manager.register_static_lanes({"lane-a", "lane-b"})

    assert manager.is_static_lane("lane-a") is True
    assert manager.is_static_lane("lane-b") is True
    assert manager.is_static_lane("lane-c") is False


@pytest.mark.asyncio
async def test_static_lanes_excluded_from_to_remove_in_apply(monkeypatch) -> None:
    """Even without re-injection, static lanes in current set are excluded from to_remove."""
    _patch_create_handle(monkeypatch)
    manager = LaneManager(
        OllamaConfig(),
        lane_port_start=15000,
        lane_port_end=15020,
    )

    static_lane = LaneConfig(model="org/static-model", vllm=True)
    static_lid = _lane_id_from_config(static_lane)

    # Apply static lane first
    manager.register_static_lanes({static_lid})
    result = await manager.apply_lanes([static_lane])
    assert result.success

    # Apply empty desired set — planner wants zero lanes
    result2 = await manager.apply_lanes([])
    assert result2.success

    # Static lane must survive
    assert static_lid in manager.lane_ids


@pytest.mark.asyncio
async def test_max_lanes_accounts_for_static_lanes(monkeypatch) -> None:
    """apply_lanes should reject if desired + static re-injected > MAX_LANES."""
    _patch_create_handle(monkeypatch)
    manager = LaneManager(
        OllamaConfig(),
        lane_port_start=15000,
        lane_port_end=15020,
        max_lanes=2,
    )

    static_lane = LaneConfig(model="org/static-model", vllm=True)
    static_lid = _lane_id_from_config(static_lane)
    manager.register_static_lanes({static_lid})

    # Apply static lane first (1/2 max_lanes)
    result = await manager.apply_lanes([static_lane])
    assert result.success

    # Now planner sends 2 dynamic lanes (omitting static). After re-injection
    # total would be 3 > max_lanes=2, so it should raise.
    dynamic_lanes = [
        LaneConfig(model="org/dyn-a", vllm=True),
        LaneConfig(model="org/dyn-b", vllm=True),
    ]
    with pytest.raises(ValueError, match="exceeds MAX_LANES"):
        await manager.apply_lanes(dynamic_lanes)
