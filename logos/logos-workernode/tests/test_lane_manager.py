from __future__ import annotations

import asyncio
import socket
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest

from logos_worker_node.lane_manager import LaneManager, PortAllocator
from logos_worker_node.models import (
    DeviceInfo,
    DeviceSummary,
    LaneConfig,
    LaneStatus,
    OllamaConfig,
    ProcessState,
    ProcessStatus,
    VllmConfig,
)


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
        _vllm_engine_config,
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
async def test_wake_lane_oom_removes_lane_for_cleanup() -> None:
    manager = LaneManager(OllamaConfig(), lane_port_start=15031, lane_port_end=15040)
    lane = LaneConfig(
        model="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        vllm=True,
        vllm_config=VllmConfig(enable_sleep_mode=True),
    )
    lane_id = "deepseek-ai_DeepSeek-R1-0528-Qwen3-8B"

    class FakeVllmHandle:
        def __init__(self) -> None:
            self.lane_id = lane_id
            self.port = 15031
            self.lane_config = lane
            self.persisted_reason: str | None = None
            self.destroy_called = False
            self.close_called = False

        async def wake_up(self) -> dict[str, Any]:
            raise RuntimeError(
                "CUDA Error: out of memory at /workspace/csrc/cumem_allocator.cpp:139"
            )

        def persist_recent_logs(self, reason: str) -> None:
            self.persisted_reason = reason

        async def destroy(self) -> None:
            self.destroy_called = True

        async def close(self) -> None:
            self.close_called = True

    fake = FakeVllmHandle()
    manager._handles[lane_id] = fake  # noqa: SLF001
    manager._port_alloc._used[lane_id] = 15031  # noqa: SLF001

    with pytest.raises(RuntimeError, match="wake failed with CUDA OOM"):
        await manager.wake_lane(lane_id)

    assert lane_id not in manager._handles  # noqa: SLF001
    assert manager._port_alloc.get_port(lane_id) is None
    assert fake.persisted_reason == "wake_oom"
    assert fake.destroy_called is True
    assert fake.close_called is True


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



def test_auto_tp_keeps_tp1_when_model_fits() -> None:
    """Model fits on one GPU — auto-TP should keep TP=1."""
    from logos_worker_node.model_profiles import ModelProfileRegistry, ModelProfileRecord

    profiles = ModelProfileRegistry()
    # 8B model ~ 10 GB base residency, fits easily on a 24 GB GPU
    profiles._profiles["deepseek-ai/DeepSeek-R1-0528-Qwen3-8B"] = ModelProfileRecord(
        base_residency_mb=10_000.0, engine="vllm",
    )
    manager = LaneManager(
        OllamaConfig(),
        lane_port_start=15100,
        lane_port_end=15110,
        gpu_device_count=lambda: 4,
        per_gpu_vram_mb=lambda: 24_000.0,  # 24 GB per GPU
        model_profiles=profiles,
    )
    lane = LaneConfig(
        model="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        vllm=True,
        vllm_config=VllmConfig(tensor_parallel_size=1),
    )
    result = manager._auto_tensor_parallel(lane)
    assert result.vllm_config.tensor_parallel_size == 1


def test_auto_tp_escalates_when_model_does_not_fit() -> None:
    """Model too large for one GPU — auto-TP should escalate to minimum needed TP."""
    from logos_worker_node.model_profiles import ModelProfileRegistry, ModelProfileRecord

    profiles = ModelProfileRegistry()
    # 70B model ~ 42 GB base residency, needs 2 x 24 GB GPUs
    profiles._profiles["big-model/70B"] = ModelProfileRecord(
        base_residency_mb=42_000.0, engine="vllm",
    )
    manager = LaneManager(
        OllamaConfig(),
        lane_port_start=15100,
        lane_port_end=15110,
        gpu_device_count=lambda: 4,
        per_gpu_vram_mb=lambda: 24_000.0,
        model_profiles=profiles,
    )
    lane = LaneConfig(
        model="big-model/70B",
        vllm=True,
        vllm_config=VllmConfig(tensor_parallel_size=1),
    )
    result = manager._auto_tensor_parallel(lane)
    # 42000 / (24000*0.85=20400) = ceil(2.06) = 3, but model should need TP=3
    assert result.vllm_config.tensor_parallel_size >= 2
    assert result.vllm_config.tensor_parallel_size <= 4  # capped at gpu_count


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


def test_auto_tp_keeps_tp1_without_gpu_info() -> None:
    """If per-GPU VRAM is unknown, keep TP=1 (safe default)."""
    manager = LaneManager(
        OllamaConfig(),
        lane_port_start=15100,
        lane_port_end=15110,
        gpu_device_count=lambda: 4,
        per_gpu_vram_mb=lambda: 0.0,  # unknown
    )
    lane = LaneConfig(
        model="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        vllm=True,
        vllm_config=VllmConfig(tensor_parallel_size=1),
    )
    result = manager._auto_tensor_parallel(lane)
    assert result.vllm_config.tensor_parallel_size == 1


@pytest.mark.asyncio
async def test_auto_place_gpu_devices_picks_best_fit_single_gpu() -> None:
    from logos_worker_node.model_profiles import ModelProfileRecord, ModelProfileRegistry

    profiles = ModelProfileRegistry()
    profiles._profiles["Qwen/Qwen2.5-0.5B-Instruct"] = ModelProfileRecord(  # noqa: SLF001
        loaded_vram_mb=6000.0,
        engine="vllm",
    )

    async def _snapshot() -> DeviceSummary:
        return DeviceSummary(
            timestamp=datetime.now(timezone.utc),
            mode="nvidia",
            nvidia_smi_available=True,
            devices=[
                DeviceInfo(device_id="gpu0", kind="nvidia", memory_total_mb=24576.0, memory_free_mb=16000.0, extra={"index": 0}),
                DeviceInfo(device_id="gpu1", kind="nvidia", memory_total_mb=24576.0, memory_free_mb=12000.0, extra={"index": 1}),
                DeviceInfo(device_id="gpu2", kind="nvidia", memory_total_mb=24576.0, memory_free_mb=7600.0, extra={"index": 2}),
            ],
            total_memory_mb=3 * 24576.0,
            free_memory_mb=35600.0,
        )

    manager = LaneManager(
        OllamaConfig(gpu_devices="all"),
        lane_port_start=15100,
        lane_port_end=15110,
        model_profiles=profiles,
        gpu_snapshot=_snapshot,
    )
    lane = LaneConfig(
        model="Qwen/Qwen2.5-0.5B-Instruct",
        vllm=True,
        vllm_config=VllmConfig(tensor_parallel_size=1),
    )

    placed = await manager._auto_place_gpu_devices("planner-Qwen_Qwen2.5-0.5B-Instruct", lane)  # noqa: SLF001
    assert placed.gpu_devices == "2"


@pytest.mark.asyncio
async def test_auto_place_gpu_devices_keeps_sticky_gpu_when_it_still_fits() -> None:
    from logos_worker_node.model_profiles import ModelProfileRecord, ModelProfileRegistry

    profiles = ModelProfileRegistry()
    profiles._profiles["Qwen/Qwen2.5-0.5B-Instruct"] = ModelProfileRecord(  # noqa: SLF001
        loaded_vram_mb=6000.0,
        engine="vllm",
    )

    async def _snapshot() -> DeviceSummary:
        return DeviceSummary(
            timestamp=datetime.now(timezone.utc),
            mode="nvidia",
            nvidia_smi_available=True,
            devices=[
                DeviceInfo(device_id="gpu0", kind="nvidia", memory_total_mb=24576.0, memory_free_mb=15000.0, extra={"index": 0}),
                DeviceInfo(device_id="gpu1", kind="nvidia", memory_total_mb=24576.0, memory_free_mb=9000.0, extra={"index": 1}),
                DeviceInfo(device_id="gpu2", kind="nvidia", memory_total_mb=24576.0, memory_free_mb=7600.0, extra={"index": 2}),
            ],
            total_memory_mb=3 * 24576.0,
            free_memory_mb=31600.0,
        )

    manager = LaneManager(
        OllamaConfig(gpu_devices="all"),
        lane_port_start=15100,
        lane_port_end=15110,
        model_profiles=profiles,
        gpu_snapshot=_snapshot,
    )
    lane_id = "planner-Qwen_Qwen2.5-0.5B-Instruct"
    current_lane = LaneConfig(
        lane_id=lane_id,
        model="Qwen/Qwen2.5-0.5B-Instruct",
        vllm=True,
        gpu_devices="1",
        vllm_config=VllmConfig(tensor_parallel_size=1),
    )

    class FakeHandle:
        def __init__(self) -> None:
            self.lane_id = lane_id
            self.port = 15100
            self.lane_config = current_lane

    manager._handles[lane_id] = FakeHandle()  # noqa: SLF001

    new_lane = LaneConfig(
        lane_id=lane_id,
        model="Qwen/Qwen2.5-0.5B-Instruct",
        vllm=True,
        vllm_config=VllmConfig(tensor_parallel_size=1),
    )

    placed = await manager._auto_place_gpu_devices(lane_id, new_lane)  # noqa: SLF001
    assert placed.gpu_devices == "1"


@pytest.mark.asyncio
async def test_auto_place_gpu_devices_picks_smallest_feasible_tp_subset() -> None:
    from logos_worker_node.model_profiles import ModelProfileRecord, ModelProfileRegistry

    profiles = ModelProfileRegistry()
    profiles._profiles["big-model/70B"] = ModelProfileRecord(  # noqa: SLF001
        base_residency_mb=14000.0,
        kv_budget_mb=6000.0,
        loaded_vram_mb=20000.0,
        engine="vllm",
    )

    async def _snapshot() -> DeviceSummary:
        return DeviceSummary(
            timestamp=datetime.now(timezone.utc),
            mode="nvidia",
            nvidia_smi_available=True,
            devices=[
                DeviceInfo(device_id="gpu0", kind="nvidia", memory_total_mb=24576.0, memory_free_mb=24000.0, extra={"index": 0}),
                DeviceInfo(device_id="gpu1", kind="nvidia", memory_total_mb=24576.0, memory_free_mb=15000.0, extra={"index": 1}),
                DeviceInfo(device_id="gpu2", kind="nvidia", memory_total_mb=24576.0, memory_free_mb=16000.0, extra={"index": 2}),
                DeviceInfo(device_id="gpu3", kind="nvidia", memory_total_mb=24576.0, memory_free_mb=40000.0, extra={"index": 3}),
            ],
            total_memory_mb=4 * 24576.0,
            free_memory_mb=95000.0,
        )

    manager = LaneManager(
        OllamaConfig(gpu_devices="all"),
        lane_port_start=15100,
        lane_port_end=15110,
        model_profiles=profiles,
        gpu_snapshot=_snapshot,
    )
    lane = LaneConfig(
        model="big-model/70B",
        vllm=True,
        vllm_config=VllmConfig(tensor_parallel_size=2),
    )

    placed = await manager._auto_place_gpu_devices("planner-big-model_70B", lane)  # noqa: SLF001
    assert placed.gpu_devices == "1,2"


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


# ---------------------------------------------------------------------------
# Phase 5: CPU offload budget injection
# ---------------------------------------------------------------------------


def test_cpu_offload_only_when_explicit_per_lane():
    """CPU offload is only applied when explicitly set on the lane's vllm_config."""
    # Default (0.0) = no offload flag
    lc_default = LaneConfig(model="small-model", vllm=True, vllm_config=VllmConfig())
    assert lc_default.vllm_config.cpu_offload_gb == 0.0

    # Explicit value = offload enabled
    lc_explicit = LaneConfig(model="big-model", vllm=True, vllm_config=VllmConfig(cpu_offload_gb=20.0))
    assert lc_explicit.vllm_config.cpu_offload_gb == 20.0


# ---------------------------------------------------------------------------
# Phase 6: Stuck-lane detection and automatic restart
# ---------------------------------------------------------------------------


def _make_vllm_lane_status(
    lane_id: str,
    model: str = "Qwen/Qwen3-Embedding-8B",
    *,
    gen_tokens: float = 100.0,
    requests_running: float = 2.0,
) -> LaneStatus:
    """Helper to build a minimal vLLM LaneStatus with backend_metrics."""
    return LaneStatus(
        lane_id=lane_id,
        lane_uid=f"vllm:{lane_id}",
        model=model,
        port=15000,
        vllm=True,
        process=ProcessStatus(state=ProcessState.RUNNING, pid=12345),
        runtime_state="running",
        backend_metrics={
            "generation_tokens_total": gen_tokens,
            "requests_running": requests_running,
        },
    )


@pytest.mark.asyncio
async def test_stuck_lane_is_automatically_restarted(monkeypatch) -> None:
    """After stuck detection kills a lane, it should be restarted automatically."""
    lane_id = "planner-Qwen_Qwen3-Embedding-8B"
    lane_config = LaneConfig(
        lane_id=lane_id,
        model="Qwen/Qwen3-Embedding-8B",
        vllm=True,
        vllm_config=VllmConfig(),
    )
    manager = LaneManager(OllamaConfig(), lane_port_start=15000, lane_port_end=15010)
    call_log: list[str] = []

    class FakeStuckHandle:
        def __init__(self) -> None:
            self.lane_id = lane_id
            self.port = 15000
            self.lane_config = lane_config

        async def stop(self) -> ProcessStatus:
            call_log.append("stop")
            return ProcessStatus(state=ProcessState.STOPPED, pid=12345, return_code=0)

        async def destroy(self) -> None:
            call_log.append("destroy")

        async def close(self) -> None:
            call_log.append("close")

    class FakeNewHandle:
        def __init__(self, lid: str, port: int) -> None:
            self.lane_id = lid
            self.port = port
            self.lane_config = None

        async def init(self) -> None:
            call_log.append("init")

        async def spawn(self, lc: LaneConfig) -> ProcessStatus:
            self.lane_config = lc
            call_log.append("spawn")
            return ProcessStatus(state=ProcessState.RUNNING, pid=99999)

        async def destroy(self) -> None:
            pass

        async def close(self) -> None:
            pass

    stuck_handle = FakeStuckHandle()
    manager._handles[lane_id] = stuck_handle  # noqa: SLF001
    manager._port_alloc._used[lane_id] = 15000  # noqa: SLF001

    def _fake_create_handle(
        lid: str, port: int, _gc, _vec, _lc,
    ) -> FakeNewHandle:
        return FakeNewHandle(lid, port)

    monkeypatch.setattr("logos_worker_node.lane_manager._create_handle", _fake_create_handle)
    monkeypatch.setattr(PortAllocator, "_is_port_available", staticmethod(lambda _port: True))

    # Simulate stuck detection: prime the counters so the next poll trips the threshold
    manager._stuck_poll_threshold = 1  # noqa: SLF001
    manager._last_gen_tokens[lane_id] = 0.0  # noqa: SLF001

    status = _make_vllm_lane_status(lane_id, gen_tokens=0.0, requests_running=2.0)
    await manager._check_stuck_lanes([status])  # noqa: SLF001

    # Lane should have been stopped then restarted
    assert "stop" in call_log
    assert "destroy" in call_log  # _restart_lane_unlocked destroys old handle
    assert "init" in call_log
    assert "spawn" in call_log
    # New handle should now be in _handles
    new_handle = manager._handles.get(lane_id)  # noqa: SLF001
    assert isinstance(new_handle, FakeNewHandle)
    assert new_handle.lane_config == lane_config


@pytest.mark.asyncio
async def test_stuck_lane_no_restart_when_auto_restart_false(monkeypatch) -> None:
    """When auto_restart=False (lock held), stuck lane is stopped but NOT restarted."""
    lane_id = "planner-Qwen_Qwen3-Embedding-8B"
    lane_config = LaneConfig(
        lane_id=lane_id,
        model="Qwen/Qwen3-Embedding-8B",
        vllm=True,
        vllm_config=VllmConfig(),
    )
    manager = LaneManager(OllamaConfig(), lane_port_start=15000, lane_port_end=15010)
    stopped = False

    class FakeStuckHandle:
        def __init__(self) -> None:
            self.lane_id = lane_id
            self.port = 15000
            self.lane_config = lane_config

        async def stop(self) -> ProcessStatus:
            nonlocal stopped
            stopped = True
            return ProcessStatus(state=ProcessState.STOPPED, pid=12345, return_code=0)

    manager._handles[lane_id] = FakeStuckHandle()  # noqa: SLF001
    manager._stuck_poll_threshold = 1  # noqa: SLF001
    manager._last_gen_tokens[lane_id] = 0.0  # noqa: SLF001

    status = _make_vllm_lane_status(lane_id, gen_tokens=0.0, requests_running=2.0)
    await manager._check_stuck_lanes([status], auto_restart=False)  # noqa: SLF001

    assert stopped is True
    # Handle should still be the original (stopped) one — no restart attempted
    assert isinstance(manager._handles.get(lane_id), FakeStuckHandle)  # noqa: SLF001


@pytest.mark.asyncio
async def test_stuck_restart_failure_does_not_crash(monkeypatch) -> None:
    """If the restart after stuck detection fails, the error is logged but doesn't propagate."""
    lane_id = "planner-Qwen_Qwen3-Embedding-8B"
    lane_config = LaneConfig(
        lane_id=lane_id,
        model="Qwen/Qwen3-Embedding-8B",
        vllm=True,
        vllm_config=VllmConfig(),
    )
    manager = LaneManager(OllamaConfig(), lane_port_start=15000, lane_port_end=15010)

    class FakeStuckHandle:
        def __init__(self) -> None:
            self.lane_id = lane_id
            self.port = 15000
            self.lane_config = lane_config

        async def stop(self) -> ProcessStatus:
            return ProcessStatus(state=ProcessState.STOPPED, pid=12345, return_code=0)

        async def destroy(self) -> None:
            pass

        async def close(self) -> None:
            pass

    class FailingNewHandle:
        def __init__(self, lid: str, port: int) -> None:
            self.lane_id = lid
            self.port = port
            self.lane_config = None

        async def init(self) -> None:
            pass

        async def spawn(self, _lc: LaneConfig) -> ProcessStatus:
            raise RuntimeError("GPU out of memory")

        async def destroy(self) -> None:
            pass

        async def close(self) -> None:
            pass

    manager._handles[lane_id] = FakeStuckHandle()  # noqa: SLF001
    manager._port_alloc._used[lane_id] = 15000  # noqa: SLF001

    def _fake_create_handle(lid: str, port: int, _gc, _vec, _lc) -> FailingNewHandle:
        return FailingNewHandle(lid, port)

    monkeypatch.setattr("logos_worker_node.lane_manager._create_handle", _fake_create_handle)
    monkeypatch.setattr(PortAllocator, "_is_port_available", staticmethod(lambda _port: True))

    manager._stuck_poll_threshold = 1  # noqa: SLF001
    manager._last_gen_tokens[lane_id] = 0.0  # noqa: SLF001

    status = _make_vllm_lane_status(lane_id, gen_tokens=0.0, requests_running=2.0)
    # Should not raise — error is caught internally
    await manager._check_stuck_lanes([status])  # noqa: SLF001

    # Lane should have been removed from handles (restart_lane_unlocked pops on failure)
    assert lane_id not in manager._handles  # noqa: SLF001


@pytest.mark.asyncio
async def test_stuck_detection_resets_after_token_progress() -> None:
    """Stuck poll counter resets when generation tokens make progress."""
    lane_id = "planner-Qwen_Qwen3-Embedding-8B"
    lane_config = LaneConfig(
        lane_id=lane_id,
        model="Qwen/Qwen3-Embedding-8B",
        vllm=True,
        vllm_config=VllmConfig(),
    )
    manager = LaneManager(OllamaConfig(), lane_port_start=15000, lane_port_end=15010)

    class FakeHandle:
        def __init__(self) -> None:
            self.lane_id = lane_id
            self.port = 15000
            self.lane_config = lane_config

    manager._handles[lane_id] = FakeHandle()  # noqa: SLF001
    manager._stuck_poll_threshold = 3  # noqa: SLF001

    # Poll 1: no progress (gen_tokens=100, prev=None → baseline, no increment)
    s1 = _make_vllm_lane_status(lane_id, gen_tokens=100.0, requests_running=2.0)
    await manager._check_stuck_lanes([s1], auto_restart=False)  # noqa: SLF001
    assert manager._stuck_polls.get(lane_id, 0) == 0  # noqa: SLF001 — first poll sets baseline

    # Poll 2: still stuck at 100
    s2 = _make_vllm_lane_status(lane_id, gen_tokens=100.0, requests_running=2.0)
    await manager._check_stuck_lanes([s2], auto_restart=False)  # noqa: SLF001
    assert manager._stuck_polls.get(lane_id, 0) == 1  # noqa: SLF001

    # Poll 3: tokens increased → counter should reset
    s3 = _make_vllm_lane_status(lane_id, gen_tokens=200.0, requests_running=2.0)
    await manager._check_stuck_lanes([s3], auto_restart=False)  # noqa: SLF001
    assert manager._stuck_polls.get(lane_id, 0) == 0  # noqa: SLF001
