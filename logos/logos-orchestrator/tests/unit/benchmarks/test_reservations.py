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


@pytest.mark.parametrize("action", ["infer", "infer_stream"])
async def test_admitted_production_survives_reservation_until_completion(action):
    registry = LogosNodeRuntimeRegistry()
    lane = {"lane_id": "lane", "model": "drain-model", "runtime_state": "running"}
    session = SimpleNamespace(provider_id=9010, capabilities_models=["drain-model"], latest_runtime={"lanes": [lane]})
    registry._get_active_session = AsyncMock(return_value=session)
    facade = LogosNodeSchedulingDataFacade(MagicMock())
    provider = MagicMock(provider_id=9010)
    provider.try_reserve_capacity.return_value = True
    facade._get_provider_for_model = MagicMock(return_value=provider)
    facade.get_model_name = MagicMock(return_value="drain-model")
    assert facade.try_reserve_capacity(1, 9010, "admitted")
    benchmark_reservations.reserve(9010, "drain-model", 9011)
    try:
        assert facade.model_inflight_requests(9010, "drain-model") == 1
        assert await registry.select_lane_for_model(9010, "drain-model", request_id="admitted") == lane
        registry._check_benchmark_reservation(session, action, {"lane_id": "lane"}, "admitted")
        assert not facade.try_reserve_capacity(1, 9010, "new-request")
        assert await registry.select_lane_for_model(9010, "drain-model", request_id="new-request") is None
        benchmark_reservations.finish_request("admitted")
        assert facade.model_inflight_requests(9010, "drain-model") == 0
        assert not benchmark_reservations.allows(9010, "drain-model", "admitted")
    finally:
        benchmark_reservations.finish_request("admitted")
        benchmark_reservations.release(9011)


def test_failed_capacity_admission_does_not_keep_access():
    lease = BenchmarkReservations()
    assert not lease.try_admit(1, "m", "rejected", lambda: False)
    lease.reserve(1, "m", 7)
    assert not lease.allows(1, "m", "rejected")


def test_reclaim_plan_does_not_count_reserved_memory(lease):
    from logos.capacity.capacity_planner import CapacityPlanner

    planner = object.__new__(CapacityPlanner)
    target = SimpleNamespace(lane_id="target", model_name="target", gpu_devices=None)
    reserved = SimpleNamespace(lane_id="reserved", model_name="model")
    # A reserved lane must be excluded before its state or reclaim capacity is inspected.
    assert (
        planner._next_request_reclaim_action(
            provider_id=9001, target=target, lanes=[reserved], profiles={}, required_free_mb=100
        )
        is None
    )
    assert not planner._has_blocking_busy_lanes(
        provider_id=9001, target=target, lanes=[reserved], profiles={}, required_free_mb=100
    )


def test_reclaim_selects_unreserved_alternative(lease):
    from logos.capacity.capacity_planner import CapacityPlanner

    planner = object.__new__(CapacityPlanner)
    planner._facade = MagicMock()
    planner._facade.get_scheduler_queue_depth_by_model_name.return_value = 0
    planner._lane_is_in_load_cooldown = MagicMock(return_value=False)
    target = SimpleNamespace(lane_id="target", model_name="target", gpu_devices=None)
    reserved = SimpleNamespace(lane_id="reserved", model_name="model")
    alternative = SimpleNamespace(
        lane_id="alternative",
        model_name="other",
        runtime_state="running",
        sleep_state="unsupported",
        active_requests=0,
        queue_waiting=0,
        effective_vram_mb=200,
    )
    action = planner._next_request_reclaim_action(
        provider_id=9001, target=target, lanes=[reserved, alternative], profiles={}, required_free_mb=100
    )
    assert action.lane_id == "alternative"


def test_reserved_reclaim_is_not_credited_to_vram_budget(lease):
    from logos.capacity.capacity_planner import CapacityPlanner

    planner = object.__new__(CapacityPlanner)
    action = SimpleNamespace(action="stop", provider_id=9001, model_name="model")
    assert planner._validate_vram_budget([action]) == []
