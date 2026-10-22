"""Lane operations that may overlap: unloads always, loads on GPUs no other load starts on."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest

from logos_worker_node.lane_manager import LaneManager
from logos_worker_node.logos_bridge import LogosBridgeClient
from logos_worker_node.model_profiles import ModelProfileRecord, ModelProfileRegistry
from logos_worker_node.models import DeviceInfo, DeviceSummary, LaneConfig, LogosConfig, VllmConfig, WorkerConfig
from logos_worker_node.resource_lock import ResourceLock

MODEL = "Qwen/Qwen2.5-0.5B-Instruct"


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


# ── ResourceLock ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scopes_on_other_lanes_and_gpus_are_held_together() -> None:
    lock = ResourceLock()
    async with lock.scoped(["a"], [0]):
        await asyncio.wait_for(_enter(lock.scoped(["b"], [1])), timeout=1)


async def _enter(scope) -> None:
    async with scope:
        pass


@pytest.mark.asyncio
async def test_whole_lock_waits_for_every_scope_and_scopes_wait_behind_it() -> None:
    lock = ResourceLock()
    order: list[str] = []
    release_a = asyncio.Event()

    async def hold_a() -> None:
        async with lock.scoped(["a"], [0]):
            order.append("a")
            await release_a.wait()

    async def whole() -> None:
        async with lock:
            order.append("whole")

    async def later_b() -> None:
        async with lock.scoped(["b"], [1]):
            order.append("b")

    tasks = [asyncio.create_task(hold_a())]
    await _settle()
    tasks.append(asyncio.create_task(whole()))
    await _settle()
    # b conflicts with the waiting whole-lock request, so it queues behind it.
    tasks.append(asyncio.create_task(later_b()))
    await _settle()
    assert order == ["a"]
    release_a.set()
    await asyncio.gather(*tasks)
    assert order == ["a", "whole", "b"]


@pytest.mark.asyncio
async def test_unqueued_scope_passes_waiters_but_not_holders() -> None:
    lock = ResourceLock()
    release = asyncio.Event()
    order: list[str] = []

    async def hold() -> None:
        async with lock.scoped(["a"], [0]):
            await release.wait()

    async def whole() -> None:
        async with lock:
            order.append("whole")

    async def unload_b() -> None:
        async with lock.scoped(["b"], queue=False):
            order.append("unload b")

    async def unload_a() -> None:
        async with lock.scoped(["a"], queue=False):
            order.append("unload a")

    holder = asyncio.create_task(hold())
    await _settle()
    waiter = asyncio.create_task(whole())
    await _settle()
    await unload_b()
    blocked = asyncio.create_task(unload_a())
    await _settle()
    assert order == ["unload b"]
    release.set()
    await asyncio.gather(holder, waiter, blocked)
    assert "unload a" in order


@pytest.mark.asyncio
async def test_widen_waits_for_a_holder_of_the_gpu() -> None:
    lock = ResourceLock()
    release = asyncio.Event()
    widened = asyncio.Event()

    async def wake_on_gpu0() -> None:
        async with lock.scoped(["sleeping"], [0]):
            await release.wait()

    async def load() -> None:
        async with lock.scoped(["new"]) as claim:
            await claim.widen(frozenset({0}))
            widened.set()

    waking = asyncio.create_task(wake_on_gpu0())
    await _settle()
    loading = asyncio.create_task(load())
    await _settle()
    assert not widened.is_set()
    release.set()
    await asyncio.gather(waking, loading)
    assert widened.is_set()


# ── Unloads ────────────────────────────────────────────────────────────────


class _Handle:
    def __init__(self, lane_config: LaneConfig) -> None:
        self.lane_config = lane_config
        self.port = None
        self.release = asyncio.Event()
        self.release.set()
        self.destroyed = False

    async def destroy(self) -> None:
        await self.release.wait()
        self.destroyed = True

    async def close(self) -> None:
        pass


def _manager_with(lanes: dict[str, _Handle]) -> LaneManager:
    manager = LaneManager(WorkerConfig(), lane_port_start=15300, lane_port_end=15310)
    for lane_id, handle in lanes.items():
        manager._handles[lane_id] = handle  # noqa: SLF001
        manager._port_alloc.allocate(lane_id)  # noqa: SLF001
        manager._active_requests[lane_id] = 0  # noqa: SLF001
    return manager


@pytest.mark.asyncio
async def test_unload_runs_while_another_lane_is_loading() -> None:
    manager = _manager_with({"b": _Handle(LaneConfig(model="m-b", gpu_devices="1"))})
    loading = asyncio.Event()
    release = asyncio.Event()

    async def load_a() -> None:
        async with manager._lock.scoped(["a"], [0]):  # noqa: SLF001
            loading.set()
            await release.wait()

    load = asyncio.create_task(load_a())
    await loading.wait()
    await asyncio.wait_for(manager.remove_lane("b"), timeout=2)
    assert "b" not in manager._handles  # noqa: SLF001
    release.set()
    await load


@pytest.mark.asyncio
async def test_requests_to_a_lane_are_counted_while_another_lane_loads() -> None:
    manager = _manager_with({"b": _Handle(LaneConfig(model="m-b", gpu_devices="1"))})
    async with manager._lock.scoped(["a"], [0]):  # noqa: SLF001
        await asyncio.wait_for(manager.increment_active_requests("b"), timeout=2)
        await asyncio.wait_for(manager.decrement_active_requests("b"), timeout=2)
    assert manager._active_requests["b"] == 0  # noqa: SLF001


@pytest.mark.asyncio
async def test_unload_waits_for_a_holder_of_the_whole_lock() -> None:
    manager = _manager_with({"b": _Handle(LaneConfig(model="m-b"))})
    async with manager._lock:  # noqa: SLF001
        unload = asyncio.create_task(manager.remove_lane("b"))
        await _settle()
        assert "b" in manager._handles  # noqa: SLF001
    await asyncio.wait_for(unload, timeout=2)
    assert "b" not in manager._handles  # noqa: SLF001


@pytest.mark.asyncio
async def test_port_stays_taken_until_the_unloaded_process_is_gone() -> None:
    handle = _Handle(LaneConfig(model="m-b"))
    handle.release.clear()
    manager = _manager_with({"b": handle})
    port = manager._port_alloc.get_port("b")  # noqa: SLF001

    unload = asyncio.create_task(manager.remove_lane("b"))
    await _settle()
    assert "b" not in manager._handles  # noqa: SLF001
    assert manager._port_alloc.get_port("b") == port  # noqa: SLF001
    assert "b" in manager._finalizing  # noqa: SLF001

    handle.release.set()
    await unload
    assert handle.destroyed
    assert manager._port_alloc.get_port("b") is None  # noqa: SLF001
    assert "b" not in manager._finalizing  # noqa: SLF001


@pytest.mark.asyncio
async def test_two_unloads_overlap() -> None:
    first = _Handle(LaneConfig(model="m-a", gpu_devices="0"))
    second = _Handle(LaneConfig(model="m-b", gpu_devices="1"))
    first.release.clear()
    manager = _manager_with({"a": first, "b": second})

    slow = asyncio.create_task(manager.remove_lane("a"))
    await _settle()
    await asyncio.wait_for(manager.remove_lane("b"), timeout=2)
    assert second.destroyed and not first.destroyed
    first.release.set()
    await slow


# ── Loads on separate GPUs ─────────────────────────────────────────────────


def _placement_manager(free_mb: dict[int, float]) -> LaneManager:
    async def snapshot() -> DeviceSummary:
        return DeviceSummary(
            timestamp=datetime.now(timezone.utc),
            mode="nvidia",
            nvidia_smi_available=True,
            devices=[
                DeviceInfo(
                    device_id=f"gpu{i}",
                    kind="nvidia",
                    memory_total_mb=24576.0,
                    memory_free_mb=free,
                    extra={"index": i},
                )
                for i, free in free_mb.items()
            ],
            total_memory_mb=len(free_mb) * 24576.0,
            free_memory_mb=sum(free_mb.values()),
        )

    profiles = ModelProfileRegistry()
    profiles._profiles[MODEL] = ModelProfileRecord(loaded_vram_mb=6000.0, engine="vllm")  # noqa: SLF001
    return LaneManager(
        WorkerConfig(gpu_devices="all"),
        lane_port_start=15200,
        lane_port_end=15210,
        model_profiles=profiles,
        gpu_device_count=lambda: len(free_mb),
        gpu_snapshot=snapshot,
    )


def _lane(gpu_devices: str = "") -> LaneConfig:
    return LaneConfig(model=MODEL, vllm=True, gpu_devices=gpu_devices, vllm_config=VllmConfig(tensor_parallel_size=1))


@pytest.mark.asyncio
async def test_second_load_places_on_a_gpu_no_other_load_starts_on() -> None:
    manager = _placement_manager({0: 20000.0, 1: 15000.0})
    async with manager._lock.scoped(["a"]) as first:  # noqa: SLF001
        placed_a = await manager._place_for_spawn("a", _lane(), first)  # noqa: SLF001
        async with manager._lock.scoped(["b"]) as second:  # noqa: SLF001
            placed_b = await asyncio.wait_for(manager._place_for_spawn("b", _lane(), second), timeout=2)  # noqa: SLF001
    assert placed_a.gpu_devices == "0"
    assert placed_b.gpu_devices == "1"


@pytest.mark.asyncio
async def test_load_waits_when_only_a_starting_load_s_gpu_fits() -> None:
    manager = _placement_manager({0: 20000.0, 1: 1000.0})
    placed: list[str] = []

    async def load_b() -> None:
        async with manager._lock.scoped(["b"]) as claim:  # noqa: SLF001
            placed.append((await manager._place_for_spawn("b", _lane(), claim)).gpu_devices)  # noqa: SLF001

    async with manager._lock.scoped(["a"]) as first:  # noqa: SLF001
        assert (await manager._place_for_spawn("a", _lane(), first)).gpu_devices == "0"  # noqa: SLF001
        waiting = asyncio.create_task(load_b())
        await _settle()
        assert placed == []
        manager._finish_loading("a")  # noqa: SLF001
    await asyncio.wait_for(waiting, timeout=2)
    assert placed == ["0"]


@pytest.mark.asyncio
async def test_pinned_load_waits_for_a_load_starting_on_its_gpu() -> None:
    manager = _placement_manager({0: 20000.0, 1: 20000.0})
    placed: list[str] = []

    async def load_b() -> None:
        async with manager._lock.scoped(["b"]) as claim:  # noqa: SLF001
            placed.append((await manager._place_for_spawn("b", _lane("0"), claim)).gpu_devices)  # noqa: SLF001

    async with manager._lock.scoped(["a"]) as first:  # noqa: SLF001
        await manager._place_for_spawn("a", _lane("0"), first)  # noqa: SLF001
        waiting = asyncio.create_task(load_b())
        await _settle()
        assert placed == []
        manager._finish_loading("a")  # noqa: SLF001
    await asyncio.wait_for(waiting, timeout=2)
    assert placed == ["0"]


# ── Bridge ─────────────────────────────────────────────────────────────────


class _State:
    pass


class _App:
    def __init__(self, lane_manager: object) -> None:
        self.state = _State()
        self.state.lane_manager = lane_manager


class _WS:
    def __init__(self) -> None:
        self.frames: list[dict] = []

    async def send(self, raw: str) -> None:
        self.frames.append(json.loads(raw))


class _SlowLoads:
    status_revision = 1

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.calls: list[str] = []

    async def add_lane(self, lane_config: LaneConfig) -> object:
        self.calls.append(f"add {lane_config.lane_id}")
        await self.release.wait()
        return _Status()

    async def remove_lane(self, lane_id: str) -> None:
        self.calls.append(f"delete {lane_id}")


class _Status:
    def model_dump(self, mode: str = "json") -> dict:
        return {"ok": True}


def _command(cmd_id: str, action: str, params: dict) -> str:
    return json.dumps({"type": "command", "cmd_id": cmd_id, "action": action, "params": params})


@pytest.mark.asyncio
async def test_bridge_answers_an_unload_while_a_load_runs() -> None:
    lanes = _SlowLoads()
    client = LogosBridgeClient(_App(lanes), LogosConfig(enabled=True, logos_url="https://logos.example"))
    ws = _WS()

    await client._handle_message(ws, _command("load", "add_lane", {"lane_id": "a", "model": MODEL}))  # noqa: SLF001
    await client._handle_message(ws, _command("unload", "delete_lane", {"lane_id": "b"}))  # noqa: SLF001
    await _settle()
    assert [frame["cmd_id"] for frame in ws.frames] == ["unload"]

    lanes.release.set()
    await asyncio.gather(*client._lifecycle_tasks)  # noqa: SLF001
    assert [frame["cmd_id"] for frame in ws.frames] == ["unload", "load"]


@pytest.mark.asyncio
async def test_bridge_hands_two_loads_to_the_lane_manager_at_once() -> None:
    lanes = _SlowLoads()
    client = LogosBridgeClient(_App(lanes), LogosConfig(enabled=True, logos_url="https://logos.example"))
    ws = _WS()

    await client._handle_message(ws, _command("first", "add_lane", {"lane_id": "a", "model": MODEL}))  # noqa: SLF001
    await client._handle_message(ws, _command("second", "add_lane", {"lane_id": "b", "model": MODEL}))  # noqa: SLF001
    await _settle()
    # The lane manager decides whether they may overlap (separate GPUs).
    assert lanes.calls == ["add a", "add b"]

    lanes.release.set()
    await asyncio.gather(*client._lifecycle_tasks)  # noqa: SLF001
    assert {frame["cmd_id"] for frame in ws.frames} == {"first", "second"}


@pytest.mark.asyncio
async def test_bridge_answers_a_calibration_start_while_a_load_runs() -> None:
    """A calibration start is read and answered while a load is still starting."""
    lanes = _SlowLoads()
    client = LogosBridgeClient(_App(lanes), LogosConfig(enabled=True, logos_url="https://logos.example"))
    started: list[dict] = []

    async def start(params: dict) -> dict:
        started.append(params)
        return {"ok": True}

    client._handle_start_calibration_session = start  # noqa: SLF001
    ws = _WS()

    await client._handle_message(ws, _command("load", "add_lane", {"lane_id": "a", "model": MODEL}))  # noqa: SLF001
    await client._handle_message(ws, _command("calibrate", "start_calibration_session", {}))  # noqa: SLF001
    await _settle()
    assert [frame["cmd_id"] for frame in ws.frames] == ["calibrate"]

    lanes.release.set()
    await asyncio.gather(*client._lifecycle_tasks)  # noqa: SLF001


# ── Calibration next to starting loads ─────────────────────────────────────


def test_calibration_slice_avoids_gpus_a_load_is_starting_on() -> None:
    manager = LaneManager(
        WorkerConfig(gpu_devices="all"), lane_port_start=15400, lane_port_end=15410, gpu_device_count=lambda: 3
    )
    # Three GPUs, as on deioma: the slice is two of them.
    manager._loading_gpus["starting"] = frozenset({1})  # noqa: SLF001
    assert manager.begin_calibration_session() == frozenset({0, 2})


@pytest.mark.asyncio
async def test_calibration_teardown_does_not_wait_for_a_load_on_other_gpus() -> None:
    manager = _manager_with({"slice": _Handle(LaneConfig(model="m-s", gpu_devices="2"))})
    release = asyncio.Event()

    async def load_on_gpu0() -> None:
        async with manager._lock.scoped(["new"], [0]):  # noqa: SLF001
            await release.wait()

    load = asyncio.create_task(load_on_gpu0())
    await _settle()
    assert await asyncio.wait_for(manager.destroy_lanes_on_gpus({2, 3}), timeout=2) == 1
    release.set()
    await load


# ── Review follow-ups ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_sleep_s_drain_does_not_queue_requests_behind_another_lane_s_load() -> None:
    manager = _manager_with({"b": _Handle(LaneConfig(model="m-b", gpu_devices="1"))})
    async with manager._lock.scoped(["a"], [0]):  # noqa: SLF001
        await asyncio.wait_for(manager._drain_lane_inflight("b"), timeout=2)  # noqa: SLF001


def test_a_launch_override_of_the_visible_gpus_claims_every_gpu() -> None:
    manager = _manager_with({})
    pinned = LaneConfig(model=MODEL, gpu_devices="0", vllm_config=VllmConfig())
    overridden = LaneConfig(
        model=MODEL, gpu_devices="0", vllm_config=VllmConfig(env_overrides={"CUDA_VISIBLE_DEVICES": "1"})
    )
    assert manager._launch_gpu_set(pinned) == frozenset({0})  # noqa: SLF001
    assert manager._launch_gpu_set(overridden) is None  # noqa: SLF001


class _ProbedHandle:
    """A running lane whose sleep probe lets an unload detach another lane."""

    def __init__(self, lane_config: LaneConfig, during_probe=None) -> None:
        self.lane_config = lane_config
        self._during_probe = during_probe

    def status(self):
        from logos_worker_node.models import ProcessState, ProcessStatus

        return ProcessStatus(state=ProcessState.RUNNING, pid=1)

    async def is_sleeping(self) -> bool:
        if self._during_probe is not None:
            self._during_probe()
        return False


@pytest.mark.asyncio
async def test_placement_survives_an_unload_during_its_sleep_probes() -> None:
    manager = _placement_manager({0: 20000.0, 1: 20000.0})
    vllm = VllmConfig(tensor_parallel_size=1)
    manager._handles["x"] = _ProbedHandle(  # noqa: SLF001
        LaneConfig(model=MODEL, gpu_devices="0", vllm_config=vllm),
        during_probe=lambda: manager._handles.pop("y", None),  # noqa: SLF001
    )
    manager._handles["y"] = _ProbedHandle(LaneConfig(model=MODEL, gpu_devices="1", vllm_config=vllm))  # noqa: SLF001
    placed = await manager._auto_place_gpu_devices("new", _lane())  # noqa: SLF001
    assert placed.gpu_devices in {"0", "1"}


@pytest.mark.asyncio
async def test_bridge_keeps_commands_on_one_lane_in_order_and_others_alongside() -> None:
    lanes = _SlowLoads()
    order: list[str] = []
    release_delete = asyncio.Event()

    async def remove_lane(lane_id: str) -> None:
        order.append(f"delete {lane_id} start")
        await release_delete.wait()
        order.append(f"delete {lane_id} done")

    lanes.remove_lane = remove_lane
    lanes.release.set()
    client = LogosBridgeClient(_App(lanes), LogosConfig(enabled=True, logos_url="https://logos.example"))
    ws = _WS()
    await client._handle_message(ws, _command("unload", "delete_lane", {"lane_id": "a"}))  # noqa: SLF001
    await client._handle_message(ws, _command("reload", "add_lane", {"lane_id": "a", "model": MODEL}))  # noqa: SLF001
    await client._handle_message(ws, _command("other", "add_lane", {"lane_id": "b", "model": MODEL}))  # noqa: SLF001
    await _settle()
    assert lanes.calls == ["add b"]  # lane a's load waits for its unload; lane b does not

    release_delete.set()
    await asyncio.gather(*client._lifecycle_tasks)  # noqa: SLF001
    assert lanes.calls == ["add b", "add a"]
    assert order == ["delete a start", "delete a done"]


@pytest.mark.asyncio
async def test_bridge_stop_ends_running_lane_commands() -> None:
    lanes = _SlowLoads()
    client = LogosBridgeClient(_App(lanes), LogosConfig(enabled=True, logos_url="https://logos.example"))
    await client._handle_message(_WS(), _command("load", "add_lane", {"lane_id": "a", "model": MODEL}))  # noqa: SLF001
    await _settle()
    await asyncio.wait_for(client.stop(), timeout=2)
    assert not client._lifecycle_tasks  # noqa: SLF001


@pytest.mark.asyncio
async def test_calibration_teardown_waits_for_an_unloaded_process_on_the_slice() -> None:
    handle = _Handle(LaneConfig(model="m-s", gpu_devices="2"))
    handle.release.clear()
    manager = _manager_with({"slice": handle})
    unload = asyncio.create_task(manager.remove_lane("slice"))
    await _settle()
    teardown = asyncio.create_task(manager.destroy_lanes_on_gpus({2}))
    await _settle()
    assert not teardown.done()  # the process still holds GPU 2
    handle.release.set()
    await asyncio.gather(unload, teardown)


@pytest.mark.asyncio
async def test_a_whole_lock_load_tells_calibration_where_it_starts() -> None:
    manager = _placement_manager({0: 20000.0, 1: 15000.0})
    placed = await manager._place_for_spawn("a", _lane(), None)  # noqa: SLF001
    assert manager._loading_gpus["a"] == frozenset({int(placed.gpu_devices)})  # noqa: SLF001


@pytest.mark.asyncio
async def test_a_load_that_finishes_during_placement_still_wakes_the_waiter() -> None:
    manager = _placement_manager({0: 20000.0, 1: 1000.0})
    manager._loading_gpus["a"] = frozenset({0})  # noqa: SLF001
    original = manager._auto_place_gpu_devices  # noqa: SLF001

    async def place_while_a_finishes(lane_id, lane_config, **kwargs):
        manager._finish_loading("a")  # noqa: SLF001
        return await original(lane_id, lane_config, **kwargs)

    manager._auto_place_gpu_devices = place_while_a_finishes  # noqa: SLF001
    async with manager._lock.scoped(["b"]) as claim:  # noqa: SLF001
        placed = await asyncio.wait_for(manager._place_for_spawn("b", _lane(), claim), timeout=2)  # noqa: SLF001
    assert placed.gpu_devices == "0"


@pytest.mark.asyncio
async def test_bridge_orders_a_worker_wide_change_after_earlier_lane_commands() -> None:
    lanes = _SlowLoads()
    order: list[str] = []
    release_delete = asyncio.Event()

    async def remove_lane(lane_id: str) -> None:
        await release_delete.wait()
        order.append(f"delete {lane_id}")

    async def apply_lanes(desired) -> object:
        order.append("apply")
        return _Status()

    lanes.remove_lane = remove_lane
    lanes.apply_lanes = apply_lanes
    lanes.release.set()
    client = LogosBridgeClient(_App(lanes), LogosConfig(enabled=True, logos_url="https://logos.example"))
    ws = _WS()
    await client._handle_message(ws, _command("unload", "delete_lane", {"lane_id": "a"}))  # noqa: SLF001
    await client._handle_message(ws, _command("apply", "apply_lanes", {"lanes": []}))  # noqa: SLF001
    await client._handle_message(ws, _command("load", "add_lane", {"lane_id": "b", "model": MODEL}))  # noqa: SLF001
    await _settle()
    assert order == [] and lanes.calls == []  # the apply waits for the unload, the load for the apply

    release_delete.set()
    await asyncio.gather(*client._lifecycle_tasks)  # noqa: SLF001
    assert order == ["delete a", "apply"]
    assert lanes.calls == ["add b"]


@pytest.mark.asyncio
async def test_an_unload_waits_for_a_start_on_its_gpu() -> None:
    """vLLM profiles free memory at start: it must not grow under a starting lane."""
    manager = _manager_with({"old": _Handle(LaneConfig(model="m-a", gpu_devices="0"))})
    release = asyncio.Event()

    async def start_on_gpu0() -> None:
        async with manager._lock.scoped(["new"], [0]):  # noqa: SLF001
            await release.wait()

    starting = asyncio.create_task(start_on_gpu0())
    await _settle()
    unload = asyncio.create_task(manager.remove_lane("old"))
    await _settle()
    assert not unload.done()
    release.set()
    await asyncio.wait_for(asyncio.gather(starting, unload), timeout=2)


@pytest.mark.asyncio
async def test_a_cancelled_unload_still_stops_its_process() -> None:
    handle = _Handle(LaneConfig(model="m-a", gpu_devices="0"))
    handle.release.clear()
    manager = _manager_with({"a": handle})
    unload = asyncio.create_task(manager.remove_lane("a"))
    await _settle()
    unload.cancel()
    await _settle()
    handle.release.set()
    with pytest.raises(asyncio.CancelledError):
        await unload
    assert handle.destroyed


@pytest.mark.asyncio
async def test_a_cancelled_replacement_spawn_stops_its_process() -> None:
    started = asyncio.Event()

    class _Spawning(_Handle):
        async def spawn(self, lane_config):
            started.set()
            await asyncio.Event().wait()

    handle = _Spawning(LaneConfig(model="m-a"))
    manager = _manager_with({})
    spawn = asyncio.create_task(manager._spawn_or_destroy("a", handle, handle.lane_config))  # noqa: SLF001
    await _settle()
    assert "a" in manager._loading_gpus  # noqa: SLF001
    await started.wait()
    spawn.cancel()
    with pytest.raises(asyncio.CancelledError):
        await spawn
    assert handle.destroyed
    assert "a" not in manager._loading_gpus  # noqa: SLF001


@pytest.mark.asyncio
async def test_a_failed_wake_holds_its_gpu_until_the_process_has_exited() -> None:
    class _WakeOOM(_Handle):
        async def wake_up(self) -> None:
            raise RuntimeError("CUDA out of memory")

    handle = _WakeOOM(LaneConfig(model="m-a", gpu_devices="0"))
    handle.release.clear()
    manager = _manager_with({"a": handle})
    manager._is_probable_cuda_oom = lambda exc: True  # noqa: SLF001
    waking = asyncio.create_task(manager.wake_lane("a"))
    await _settle()
    claimed = asyncio.Event()

    async def start_on_gpu0() -> None:
        async with manager._lock.scoped(["new"], [0]):  # noqa: SLF001
            claimed.set()

    starting = asyncio.create_task(start_on_gpu0())
    await _settle()
    assert not claimed.is_set()  # the failed process still holds GPU 0
    handle.release.set()
    with pytest.raises(RuntimeError):
        await waking
    await asyncio.wait_for(starting, timeout=2)


def test_a_model_stays_protected_while_one_of_two_starts_remains() -> None:
    manager = _manager_with({})
    manager.reserve_model_startup(MODEL, "a")
    manager.reserve_model_startup(MODEL, "b")
    manager.release_model_startup(MODEL, "a")  # one start failed
    manager.release_model_startup(MODEL, "a")  # released again by its finally
    assert MODEL in manager.starting_models()
    manager.release_model_startup(MODEL, "b")
    assert MODEL not in manager.starting_models()
