from __future__ import annotations

import asyncio
import socket
from typing import Any
from unittest.mock import AsyncMock

import pytest

from logos_worker_node.lane_manager import LaneManager, PortAllocator
from logos_worker_node.models import LaneConfig, OllamaConfig, ProcessState, ProcessStatus, VllmConfig


def test_port_allocator_skips_reserved_and_used_ports(monkeypatch) -> None:
    monkeypatch.setattr(PortAllocator, "_is_port_available", staticmethod(lambda _port: True))
    allocator = PortAllocator(
        start=11435,
        end=11438,
        reserved_ports={11435, 11437},
    )

    # 11435 is reserved, so the first allocation uses 11436.
    assert allocator.allocate("lane_a") == 11436
    # 11437 is reserved, so next free is 11438.
    assert allocator.allocate("lane_b") == 11438
    # Existing lane keeps its original port.
    assert allocator.allocate("lane_a") == 11436

    with pytest.raises(RuntimeError):
        allocator.allocate("lane_c")


def test_port_allocator_skips_ports_already_bound_on_host() -> None:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        pytest.skip("Socket creation is not permitted in this test environment")
    try:
        sock.bind(("127.0.0.1", 0))
    except PermissionError:
        sock.close()
        pytest.skip("Socket bind is not permitted in this test environment")
    occupied = sock.getsockname()[1]
    try:
        allocator = PortAllocator(start=occupied, end=occupied)
        with pytest.raises(RuntimeError):
            allocator.allocate("lane_a")
    finally:
        sock.close()


def test_resolve_owner_pid_maps_descendant_to_root(monkeypatch) -> None:
    parent_map = {
        200: 150,
        150: 100,
    }

    def _fake_read_parent_pid(pid: int, _cache: dict[int, int | None]) -> int | None:
        return parent_map.get(pid)

    monkeypatch.setattr(LaneManager, "_read_parent_pid", staticmethod(_fake_read_parent_pid))
    owner = LaneManager._resolve_owner_pid(200, {100}, {})
    assert owner == 100


def test_resolve_owner_pid_returns_none_when_unrelated(monkeypatch) -> None:
    parent_map = {
        300: 250,
        250: 1,
    }

    def _fake_read_parent_pid(pid: int, _cache: dict[int, int | None]) -> int | None:
        return parent_map.get(pid)

    monkeypatch.setattr(LaneManager, "_read_parent_pid", staticmethod(_fake_read_parent_pid))
    owner = LaneManager._resolve_owner_pid(300, {100}, {})
    assert owner is None


@pytest.mark.asyncio
async def test_add_lane_releases_port_when_spawn_fails(monkeypatch) -> None:
    lane_id = "deepseek-ai_DeepSeek-R1-0528-Qwen3-8B"
    manager = LaneManager(
        OllamaConfig(),
        lane_port_start=15000,
        lane_port_end=15000,
    )
    lane = LaneConfig(
        model="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        vllm=True,
    )

    class FailingHandle:
        def __init__(self, lane_id: str, port: int) -> None:
            self.lane_id = lane_id
            self.port = port
            self.lane_config = None
            self.closed = False
            self.destroyed = False

        async def init(self) -> None:
            return None

        async def spawn(self, _lane_config: LaneConfig):
            raise RuntimeError("spawn boom")

        async def destroy(self) -> None:
            self.destroyed = True

        async def close(self) -> None:
            self.closed = True

    created: dict[str, FailingHandle] = {}

    def _fake_create_handle(
        lid: str,
        port: int,
        _global_config: OllamaConfig,
        _lane_config: LaneConfig,
    ) -> FailingHandle:
        handle = FailingHandle(lid, port)
        created["handle"] = handle
        return handle

    monkeypatch.setattr("logos_worker_node.lane_manager._create_handle", _fake_create_handle)
    monkeypatch.setattr(PortAllocator, "_is_port_available", staticmethod(lambda _port: True))

    with pytest.raises(RuntimeError, match="spawn boom"):
        await manager._add_lane_unlocked(lane_id, lane)

    assert manager._port_alloc.get_port(lane_id) is None
    assert lane_id not in manager.lane_ids
    assert created["handle"].closed is True


@pytest.mark.asyncio
async def test_apply_lanes_rejects_vllm_without_nvidia_smi() -> None:
    manager = LaneManager(
        OllamaConfig(),
        lane_port_start=15000,
        lane_port_end=15010,
        nvidia_smi_available=lambda: False,
    )

    with pytest.raises(RuntimeError, match="nvidia-smi"):
        await manager.apply_lanes(
            [
                LaneConfig(
                    model="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
                    vllm=True,
                    vllm_config=VllmConfig(),
                )
            ]
        )


@pytest.mark.asyncio
async def test_reconfigure_lane_rejects_switch_to_vllm_without_nvidia_smi() -> None:
    manager = LaneManager(
        OllamaConfig(),
        lane_port_start=15010,
        lane_port_end=15020,
        nvidia_smi_available=lambda: False,
    )
    lane = LaneConfig(model="qwen2.5-coder:32b")
    lane_id = "qwen2.5-coder_32b"

    class FakeOllamaHandle:
        def __init__(self) -> None:
            self.lane_id = lane_id
            self.port = 15010
            self.lane_config = lane

    manager._handles[lane_id] = FakeOllamaHandle()  # noqa: SLF001

    with pytest.raises(RuntimeError, match="nvidia-smi"):
        await manager.reconfigure_lane(
            lane_id,
            {"vllm": True, "vllm_config": VllmConfig().model_dump()},
        )


@pytest.mark.asyncio
async def test_build_lane_status_includes_vllm_runtime_fields() -> None:
    manager = LaneManager(OllamaConfig(gpu_devices="all"), lane_port_start=15001, lane_port_end=15010)
    lane = LaneConfig(
        model="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        vllm=True,
        vllm_config=VllmConfig(enable_sleep_mode=True, tensor_parallel_size=2),
    )

    class FakeVllmHandle:
        def __init__(self) -> None:
            self.lane_id = "deepseek-ai_DeepSeek-R1-0528-Qwen3-8B"
            self.port = 15001
            self.lane_config = lane

        def status(self) -> ProcessStatus:
            return ProcessStatus(state=ProcessState.RUNNING, pid=1234)

        async def get_loaded_models(self) -> list[dict[str, Any]]:
            return [{
                "name": lane.model,
                "size": 0,
                "size_vram": 1024 * 1024,
                "details": {"backend": "vllm"},
            }]

        async def is_sleeping(self) -> bool | None:
            return True

    status = await manager._build_lane_status(  # noqa: SLF001
        FakeVllmHandle(),
        pid_vram_map={1234: 7680.0},
    )

    assert status.lane_uid == "vllm:deepseek-ai_DeepSeek-R1-0528-Qwen3-8B"
    assert status.routing_url == "http://127.0.0.1:15001"
    assert status.inference_endpoint == "/v1/chat/completions"
    assert status.effective_gpu_devices == "all"
    assert status.sleep_mode_enabled is True
    assert status.sleep_state == "sleeping"
    assert status.runtime_state == "sleeping"
    assert status.backend_metrics["tensor_parallel_size"] == 2
    assert status.reported_vram_mb == pytest.approx(1.0)
    assert status.pid_vram_mb == pytest.approx(7680.0)
    assert status.vram_source == "pid"
    assert status.effective_vram_mb == pytest.approx(7680.0)


@pytest.mark.asyncio
async def test_build_lane_status_reports_stopped_runtime_state() -> None:
    manager = LaneManager(OllamaConfig(), lane_port_start=15011, lane_port_end=15020)
    lane = LaneConfig(
        model="qwen2.5-coder:32b",
    )

    class FakeOllamaHandle:
        def __init__(self) -> None:
            self.lane_id = "qwen2.5-coder_32b"
            self.port = 15011
            self.lane_config = lane

        def status(self) -> ProcessStatus:
            return ProcessStatus(state=ProcessState.STOPPED, pid=4321, return_code=1)

    status = await manager._build_lane_status(FakeOllamaHandle(), pid_vram_map={})  # noqa: SLF001
    assert status.runtime_state == "stopped"
    assert status.sleep_state == "unsupported"


@pytest.mark.asyncio
async def test_sleep_and_wake_lane_delegate_to_vllm_handle(monkeypatch) -> None:
    manager = LaneManager(OllamaConfig(), lane_port_start=15020, lane_port_end=15030)
    lane = LaneConfig(
        model="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        vllm=True,
        vllm_config=VllmConfig(enable_sleep_mode=True),
    )
    lane_id = "deepseek-ai_DeepSeek-R1-0528-Qwen3-8B"

    class FakeVllmHandle:
        def __init__(self) -> None:
            self.lane_id = lane_id
            self.port = 15020
            self.lane_config = lane
            self.sleep_called_with: tuple[int, str] | None = None
            self.wake_called = False

        async def sleep(self, level: int = 1, mode: str = "wait") -> dict[str, Any]:
            self.sleep_called_with = (level, mode)
            return {"ok": True}

        async def wake_up(self) -> dict[str, Any]:
            self.wake_called = True
            return {"ok": True}

    fake = FakeVllmHandle()
    manager._handles[lane_id] = fake  # noqa: SLF001

    sentinel = object()
    monkeypatch.setattr(manager, "_get_status_unlocked", AsyncMock(return_value=sentinel))

    out_sleep = await manager.sleep_lane(lane_id, level=2, mode="wait")
    out_wake = await manager.wake_lane(lane_id)

    assert out_sleep is sentinel
    assert out_wake is sentinel
    assert fake.sleep_called_with == (2, "wait")
    assert fake.wake_called is True


@pytest.mark.asyncio
async def test_sleep_lane_rejects_non_vllm_lane() -> None:
    manager = LaneManager(OllamaConfig(), lane_port_start=15040, lane_port_end=15050)
    lane = LaneConfig(model="qwen2.5-coder:32b")
    lane_id = "qwen2.5-coder_32b"

    class FakeOllamaHandle:
        def __init__(self) -> None:
            self.lane_id = lane_id
            self.port = 15040
            self.lane_config = lane

    manager._handles[lane_id] = FakeOllamaHandle()  # noqa: SLF001

    with pytest.raises(ValueError, match="not a vLLM lane"):
        await manager.sleep_lane(lane_id)


@pytest.mark.asyncio
async def test_status_revision_advances_on_active_request_change() -> None:
    manager = LaneManager(OllamaConfig(), lane_port_start=15060, lane_port_end=15070)
    lane = LaneConfig(model="qwen2.5-coder:32b")
    lane_id = "qwen2.5-coder_32b"

    class FakeOllamaHandle:
        def __init__(self) -> None:
            self.lane_id = lane_id
            self.port = 15060
            self.lane_config = lane

    manager._handles[lane_id] = FakeOllamaHandle()  # noqa: SLF001

    initial = manager.status_revision
    await manager.increment_active_requests(lane_id)
    after_inc = await manager.wait_for_status_revision(initial, timeout=0.01)
    assert after_inc > initial

    await manager.decrement_active_requests(lane_id)
    after_dec = await manager.wait_for_status_revision(after_inc, timeout=0.01)
    assert after_dec > after_inc



def test_auto_tp_keeps_tp1_by_default() -> None:
    """Auto-TP should NOT escalate to all GPUs — TP=1 is the safe default."""
    manager = LaneManager(
        OllamaConfig(),
        lane_port_start=15100,
        lane_port_end=15110,
        gpu_device_count=lambda: 4,
    )
    lane = LaneConfig(
        model="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        vllm=True,
        vllm_config=VllmConfig(tensor_parallel_size=1),
    )
    result = manager._auto_tensor_parallel(lane)
    assert result.vllm_config.tensor_parallel_size == 1


def test_auto_tp_respects_explicit_tp() -> None:
    """Explicit TP>1 should be respected."""
    manager = LaneManager(
        OllamaConfig(),
        lane_port_start=15100,
        lane_port_end=15110,
        gpu_device_count=lambda: 4,
    )
    lane = LaneConfig(
        model="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        vllm=True,
        vllm_config=VllmConfig(tensor_parallel_size=2),
    )
    result = manager._auto_tensor_parallel(lane)
    assert result.vllm_config.tensor_parallel_size == 2


def test_auto_tp_noop_for_single_gpu() -> None:
    """With 1 GPU, auto-TP should be a no-op regardless of config."""
    manager = LaneManager(
        OllamaConfig(),
        lane_port_start=15100,
        lane_port_end=15110,
        gpu_device_count=lambda: 1,
    )
    lane = LaneConfig(
        model="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        vllm=True,
        vllm_config=VllmConfig(tensor_parallel_size=1),
    )
    result = manager._auto_tensor_parallel(lane)
    assert result.vllm_config.tensor_parallel_size == 1


def test_auto_tp_noop_for_non_vllm() -> None:
    """Ollama lanes should never have TP modified."""
    manager = LaneManager(
        OllamaConfig(),
        lane_port_start=15100,
        lane_port_end=15110,
        gpu_device_count=lambda: 4,
    )
    lane = LaneConfig(model="qwen2.5-coder:32b")
    result = manager._auto_tensor_parallel(lane)
    assert result.vllm_config is None


@pytest.mark.asyncio
async def test_remove_lane_releases_bookkeeping_on_destroy_timeout() -> None:
    manager = LaneManager(OllamaConfig(), lane_port_start=15080, lane_port_end=15090)
    lane = LaneConfig(model="qwen2.5-coder:32b")
    lane_id = "qwen2.5-coder_32b"

    class SlowHandle:
        def __init__(self) -> None:
            self.lane_id = lane_id
            self.port = 15080
            self.lane_config = lane
            self.close_called = False

        async def destroy(self) -> None:
            raise asyncio.TimeoutError

        async def close(self) -> None:
            self.close_called = True

    handle = SlowHandle()
    manager._handles[lane_id] = handle  # noqa: SLF001
    manager._port_alloc._used[lane_id] = 15080  # noqa: SLF001
    manager._active_requests[lane_id] = 1  # noqa: SLF001
    manager._starting_deadlines[lane_id] = 123.0  # noqa: SLF001

    async with manager._lock:  # noqa: SLF001
        await manager._remove_lane_unlocked(lane_id)  # noqa: SLF001

    assert lane_id not in manager._handles  # noqa: SLF001
    assert manager._port_alloc.get_port(lane_id) is None
    assert lane_id not in manager._active_requests  # noqa: SLF001
    assert lane_id not in manager._starting_deadlines  # noqa: SLF001
    assert handle.close_called is True
