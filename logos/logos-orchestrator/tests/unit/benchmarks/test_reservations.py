from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from logos.benchmarks.reservations import BenchmarkReservations, benchmark_reservations
from logos.logosnode_registry import LogosNodeCommandError, LogosNodeRuntimeRegistry
from logos.queue.models import Priority
from logos.queue.priority_queue import PriorityQueueManager
from logos.sdi.logosnode_facade import LogosNodeSchedulingDataFacade


@pytest.fixture
def lease():
    benchmark_reservations.reserve(9001, "model", 9002)
    try:
        yield benchmark_reservations
    finally:
        benchmark_reservations.release(9002)


def test_only_the_authenticated_job_can_use_reserved_model_lanes():
    lease = BenchmarkReservations()
    lease.reserve(1, "m", 7)
    assert not lease.allows(1, "m", "production")
    assert lease.allows(1, "other", "production")
    assert lease.allows(2, "m", "production")
    with pytest.raises(RuntimeError):
        lease.register_request(1, "m", 8, "wrong-job")
    lease.register_request(1, "m", 7, "benchmark")
    assert lease.allows(1, "m", "benchmark")
    lease.finish_request("benchmark")
    assert not lease.allows(1, "m", "benchmark")
    lease.release(7)
    assert lease.allows(1, "m", "production")


def test_old_job_cannot_release_new_job_reservation():
    lease = BenchmarkReservations()
    lease.reserve(1, "m", 7)
    with pytest.raises(RuntimeError):
        lease.reserve(1, "m", 8)
    lease.release(7)
    lease.reserve(1, "m", 8)
    lease.release(7)
    assert lease.owner(1, "m") == 8


def test_reserved_queue_leaves_production_waiting_for_other_workers():
    queue = PriorityQueueManager()
    queue.enqueue("production", 1, priority=Priority.HIGH, api_key_id=12)
    queue.enqueue("benchmark", 1, provider_affinity=2, api_key_id=-7)
    task, entry = queue.dequeue_with_entry(1, 2, required_api_key_id=-7)
    assert task == "benchmark"
    assert entry.api_key_id == -7
    assert queue.dequeue_with_entry(1, 2, required_api_key_id=-7) == (None, None)
    assert queue.dequeue(1, 3) == "production"


async def test_lane_selection_excludes_production_but_allows_benchmark(lease):
    registry = LogosNodeRuntimeRegistry()
    lane = {"lane_id": "lane", "model": "model", "runtime_state": "running"}
    registry._get_active_session = AsyncMock(
        return_value=SimpleNamespace(capabilities_models=["model"], latest_runtime={"lanes": [lane]})
    )
    assert await registry.select_lane_for_model(9001, "model", request_id="production") is None
    lease.register_request(9001, "model", 9002, "benchmark")
    assert await registry.select_lane_for_model(9001, "model", request_id="benchmark") == lane


def test_transport_rechecks_requests_selected_before_reservation(lease):
    session = SimpleNamespace(provider_id=9001, latest_runtime={"lanes": [{"lane_id": "lane", "model": "model"}]})
    for action in ("infer", "infer_stream"):
        with pytest.raises(LogosNodeCommandError, match="reserved"):
            LogosNodeRuntimeRegistry._check_benchmark_reservation(session, action, {"lane_id": "lane"}, "production")
    lease.register_request(9001, "model", 9002, "benchmark")
    LogosNodeRuntimeRegistry._check_benchmark_reservation(session, "infer", {"lane_id": "lane"}, "benchmark")


def test_scheduler_does_not_reserve_capacity_for_production(lease):
    facade = LogosNodeSchedulingDataFacade(MagicMock())
    provider = MagicMock()
    provider.try_reserve_capacity.return_value = True
    facade._get_provider_for_model = MagicMock(return_value=provider)
    facade.get_model_name = MagicMock(return_value="model")
    assert not facade.try_reserve_capacity(1, 9001, "production")
    provider.try_reserve_capacity.assert_not_called()
    lease.register_request(9001, "model", 9002, "benchmark")
    assert facade.try_reserve_capacity(1, 9001, "benchmark")


@pytest.mark.parametrize("cancelled", [False, True])
async def test_benchmark_completion_or_cancellation_releases_reservation(lease, cancelled):
    import asyncio

    import logos as main

    task = asyncio.create_task(asyncio.sleep(0))
    if cancelled:
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    main._forget_benchmark_task(9002, task)
    assert lease.allows(9001, "model", "production")


@pytest.mark.parametrize("action_name", ["stop", "sleep_l1", "sleep_l2", "reconfigure_kv_cache"])
async def test_planner_cannot_reclaim_reserved_model(lease, action_name):
    from logos.capacity.capacity_planner import CapacityPlanner

    planner = object.__new__(CapacityPlanner)
    planner._execute_action_core = AsyncMock(return_value=True)
    action = SimpleNamespace(action=action_name, provider_id=9001, model_name="model")
    assert not await planner._execute_action_with_confirmation(action)
    planner._execute_action_core.assert_not_awaited()


@pytest.mark.parametrize("action", ["infer", "infer_stream"])
def test_benchmark_permission_survives_processing_until_completion(lease, action):
    facade = LogosNodeSchedulingDataFacade(MagicMock())
    provider = MagicMock(provider_id=9001)
    provider._model_id_to_name = {1: "model"}
    provider.get_model_status.return_value = SimpleNamespace(queue_depth=0)
    facade._get_provider_for_model = MagicMock(return_value=provider)
    session = SimpleNamespace(provider_id=9001, latest_runtime={"lanes": [{"lane_id": "lane", "model": "model"}]})

    lease.register_request(9001, "model", 9002, "benchmark")
    facade.on_request_start("benchmark", 1, 9001, api_key_id=-9002)
    facade.on_request_begin_processing("benchmark", provider_id=9001)
    LogosNodeRuntimeRegistry._check_benchmark_reservation(session, action, {"lane_id": "lane"}, "benchmark")
    assert not lease.allows(9001, "model", "production")

    facade.on_request_complete("benchmark", was_cold_start=False, duration_ms=10, provider_id=9001)
    assert not lease.allows(9001, "model", "benchmark")
    assert lease.owner(9001, "model") == 9002


def test_nightly_node_reservation_blocks_all_models_until_restoration():
    lease = BenchmarkReservations()
    lease.reserve(1, "*", -31)
    assert not lease.allows(1, "other", "production")
    assert lease.allows(2, "other", "production")
    lease.reserve(1, "m", 7)
    lease.register_request(1, "m", 7, "benchmark")
    assert lease.allows(1, "m", "benchmark")
    lease.release(7)
    assert not lease.allows(1, "m", "production")
    lease.release(-31)
    assert lease.allows(1, "m", "production")


def test_nightly_owner_allows_recovery_but_blocks_unrelated_lane_changes():
    from logos.benchmarks.nightly import NIGHTLY_CONTEXT

    benchmark_reservations.reserve(9001, "*", -31)
    session = SimpleNamespace(provider_id=9001)
    try:
        with pytest.raises(LogosNodeCommandError, match="reserved"):
            LogosNodeRuntimeRegistry._check_benchmark_reservation(session, "reconfigure_lane", {}, None)
        token = NIGHTLY_CONTEXT.set(True)
        try:
            LogosNodeRuntimeRegistry._check_benchmark_reservation(session, "reconfigure_lane", {}, None)
        finally:
            NIGHTLY_CONTEXT.reset(token)
    finally:
        benchmark_reservations.release(-31)


@pytest.mark.parametrize("action", ["infer", "sync_model_profiles"])
async def test_reserved_worker_commands_preserve_dispatch_confirmation(action, lease):
    import asyncio

    registry = LogosNodeRuntimeRegistry()
    session = SimpleNamespace(
        provider_id=9001,
        latest_runtime={"lanes": [{"lane_id": "lane", "model": "model"}]},
        pending_commands={},
        send_lock=asyncio.Lock(),
        calibrating=False,
        optimistic_calibration_until=None,
    )
    dispatched = []

    async def reply(message):
        future = session.pending_commands.pop(message["cmd_id"])
        assert dispatched == [future]
        future.set_result({"success": True, "result": {"ok": True}})

    session.websocket = SimpleNamespace(send_json=AsyncMock(side_effect=reply))
    registry._get_active_session = AsyncMock(return_value=session)
    lease.register_request(9001, "model", 9002, "benchmark")
    lease.reserve(9001, "*", 9002)
    result = await registry.send_command(
        9001,
        action,
        {"lane_id": "lane"},
        request_id="benchmark",
        on_dispatched=dispatched.append,
    )
    assert result == {"ok": True}
    session.websocket.send_json.assert_awaited_once()
    assert dispatched[0].done()
    assert not session.pending_commands
