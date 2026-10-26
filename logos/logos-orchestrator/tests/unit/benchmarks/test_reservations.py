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


@pytest.mark.parametrize("other_deployment", [(2, "m"), (1, "other")])
def test_scoped_completion_preserves_access_for_a_different_deployment(other_deployment):
    lease = BenchmarkReservations()
    assert lease.try_admit(1, "m", "production", lambda: True)
    lease.reserve(1, "m", 7)
    lease.register_request(1, "m", 7, "benchmark")

    for request_id in ("production", "benchmark"):
        lease.finish_request(request_id, deployment=other_deployment)
        assert lease.allows(1, "m", request_id)
        lease.finish_request(request_id, deployment=(1, "m"))
        assert not lease.allows(1, "m", request_id)


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


async def test_nightly_drain_preserves_admitted_requests_through_lane_selection_and_send():
    facade = LogosNodeSchedulingDataFacade(MagicMock())
    provider = MagicMock(provider_id=9001)
    provider._model_id_to_name = {1: "model"}
    provider.get_model_status.return_value = SimpleNamespace(queue_depth=0)
    facade._get_provider_for_model = MagicMock(return_value=provider)
    facade.get_model_name = MagicMock(return_value="model")
    facade.on_request_start("admitted", 1, 9001, api_key_id=31)
    facade.reserve_worker_for_drain(9001, -31)
    lane = {"lane_id": "lane", "model": "model", "runtime_state": "running"}
    session = SimpleNamespace(provider_id=9001, capabilities_models=["model"], latest_runtime={"lanes": [lane]})
    registry = LogosNodeRuntimeRegistry()
    registry._get_active_session = AsyncMock(return_value=session)
    try:
        assert await registry.select_lane_for_model(9001, "model", request_id="admitted") == lane
        assert await registry.select_lane_for_model(9001, "model", request_id="new") is None
        for action in ("infer", "infer_stream"):
            registry._check_benchmark_reservation(session, action, {"lane_id": "lane"}, "admitted")
            with pytest.raises(LogosNodeCommandError):
                registry._check_benchmark_reservation(session, action, {"lane_id": "lane"}, "new")
        with pytest.raises(RuntimeError, match="reserved"):
            facade.on_request_start("new", 1, 9001)
        assert facade.model_inflight_requests(9001, "model") == 1
        facade.on_request_complete("admitted", False, 10, provider_id=9001)
        assert facade.model_inflight_requests(9001, "model") == 0
        assert not benchmark_reservations.allows(9001, "model", "admitted")
    finally:
        benchmark_reservations.release(-31)


def test_fenced_benchmark_cannot_send_previously_admitted_request(lease):
    active = True
    lease.register_request(9001, "model", 9002, "request", guard=lambda: active)
    assert lease.allows(9001, "model", "request")
    active = False
    session = SimpleNamespace(provider_id=9001, latest_runtime={"lanes": [{"lane_id": "lane", "model": "model"}]})
    with pytest.raises(LogosNodeCommandError):
        LogosNodeRuntimeRegistry._check_benchmark_reservation(session, "infer_stream", {"lane_id": "lane"}, "request")


async def test_already_admitted_request_waiting_for_send_lock_survives_nightly_reservation():
    import asyncio

    facade = LogosNodeSchedulingDataFacade(MagicMock())
    provider = MagicMock(provider_id=9001)
    provider._model_id_to_name = {1: "model"}
    provider.get_model_status.return_value = SimpleNamespace(queue_depth=0)
    facade._get_provider_for_model = MagicMock(return_value=provider)
    facade.get_model_name = MagicMock(return_value="model")
    facade.on_request_start("admitted", 1, 9001)
    session = SimpleNamespace(
        provider_id=9001,
        latest_runtime={"lanes": [{"lane_id": "lane", "model": "model"}]},
        pending_commands={},
        send_lock=asyncio.Lock(),
        calibrating=False,
        optimistic_calibration_until=None,
    )

    async def reply(message):
        session.pending_commands.pop(message["cmd_id"]).set_result({"success": True, "result": {"choices": []}})

    session.websocket = SimpleNamespace(send_json=AsyncMock(side_effect=reply))
    registry = LogosNodeRuntimeRegistry()
    registry._get_active_session = AsyncMock(return_value=session)
    await session.send_lock.acquire()
    task = asyncio.create_task(registry.send_command(9001, "infer", {"lane_id": "lane"}, request_id="admitted"))
    await asyncio.sleep(0)
    session.websocket.send_json.assert_not_awaited()
    try:
        facade.reserve_worker_for_drain(9001, -31)
        session.send_lock.release()
        assert await task == {"choices": []}
        facade.on_request_complete("admitted", False, 10, provider_id=9001)
        assert not benchmark_reservations.allows(9001, "model", "admitted")
    finally:
        benchmark_reservations.release(-31)
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_worker_ok_false_has_an_explicit_refusal_type():
    import asyncio

    from logos.logosnode_registry import LogosNodeCommandRejectedError

    registry = LogosNodeRuntimeRegistry()
    session = SimpleNamespace(
        provider_id=9001,
        latest_runtime={},
        pending_commands={},
        send_lock=asyncio.Lock(),
        calibrating=False,
        optimistic_calibration_until=None,
    )

    async def reply(message):
        session.pending_commands.pop(message["cmd_id"]).set_result(
            {"success": True, "result": {"ok": False, "error": "Worker is degraded"}}
        )

    session.websocket = SimpleNamespace(send_json=AsyncMock(side_effect=reply))
    registry._get_active_session = AsyncMock(return_value=session)
    with pytest.raises(LogosNodeCommandRejectedError, match="degraded"):
        await registry.send_command(9001, "reconfigure_lane")


def test_lost_execution_lease_blocks_worker_mutations_but_allows_cleanup():
    from logos.benchmarks.nightly import LEASE_CHECK, NIGHTLY_CONTEXT

    nightly = NIGHTLY_CONTEXT.set(True)
    lease = LEASE_CHECK.set(lambda: False)
    session = SimpleNamespace(provider_id=9001)
    try:
        with pytest.raises(LogosNodeCommandError, match="lease was lost"):
            LogosNodeRuntimeRegistry._check_benchmark_reservation(session, "reconfigure_lane", {}, None)
        LogosNodeRuntimeRegistry._check_benchmark_reservation(session, "cancel_command", {}, None)
        LogosNodeRuntimeRegistry._check_benchmark_reservation(session, "get_runtime", {}, None)
    finally:
        LEASE_CHECK.reset(lease)
        NIGHTLY_CONTEXT.reset(nightly)


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


@pytest.mark.parametrize("action", ["infer", "infer_stream"])
async def test_rerouted_production_keeps_destination_admission_during_benchmark(action):
    from logos.pipeline.correcting_scheduler import ClassificationCorrectingScheduler
    from logos.pipeline.ettft_estimator import ReadinessTier
    from logos.pipeline.scheduler_interface import SchedulingRequest

    source, destination, job_id = 9050, 9051, 9052
    model_id, model, request_id = 1, "rerouted-model", "rerouted-production"
    queue = PriorityQueueManager()
    facade = LogosNodeSchedulingDataFacade(queue)
    for provider_id in (source, destination):
        provider = MagicMock(provider_id=provider_id)
        provider._model_id_to_name = {model_id: model}
        provider.try_reserve_capacity.return_value = True
        provider.get_model_status.return_value = SimpleNamespace(queue_depth=0, active_requests=0, is_loaded=True)
        facade._providers[provider_id] = provider

    scheduler = ClassificationCorrectingScheduler.__new__(ClassificationCorrectingScheduler)
    scheduler._logosnode = facade
    scheduler._queue_mgr = queue
    scheduler._check_starvation = MagicMock()
    scheduler.reevaluate_model_queues = MagicMock()
    scheduler._weighted_shuffle_tied = lambda scored: scored
    scheduler._compute_candidate_scores = MagicMock(
        return_value=[
            (
                model_id,
                destination,
                "logosnode",
                1.0,
                1,
                SimpleNamespace(
                    tier=ReadinessTier.WARM,
                    ettft_ms=0.0,
                    warmth_state=0,
                    expected_wait_s=0.0,
                ),
            )
        ]
    )
    request = SchedulingRequest(
        request_id=request_id,
        payload={"input": "hello"},
        deployments=[{"model_id": model_id, "provider_id": pid, "type": "logosnode"} for pid in (source, destination)],
        classified_models=[(model_id, 1.0, 1)],
    )
    lane = {"lane_id": "destination-lane", "model": model, "runtime_state": "running"}
    session = SimpleNamespace(provider_id=destination, capabilities_models=[model], latest_runtime={"lanes": [lane]})
    registry = LogosNodeRuntimeRegistry()
    registry._get_active_session = AsyncMock(return_value=session)
    try:
        assert facade.try_reserve_capacity(model_id, source, request_id)
        scheduler._create_result(model_id, source, "logosnode", 1, request_id, was_queued=False)
        result = scheduler.try_reroute(request, model_id, source)
        assert result.provider_id == destination

        benchmark_reservations.reserve(destination, model, job_id)
        assert benchmark_reservations.admitted_requests(destination, model) == {request_id}
        assert facade.model_inflight_requests(destination, model) == 1
        assert await registry.select_lane_for_model(destination, model, request_id=request_id) == lane
        registry._check_benchmark_reservation(session, action, {"lane_id": lane["lane_id"]}, request_id)
        assert not facade.try_reserve_capacity(model_id, destination, "new-production")

        scheduler.release(model_id, destination, "logosnode", request_id)
        assert not benchmark_reservations.admitted_requests(destination, model)
        assert facade.model_inflight_requests(destination, model) == 0
        with pytest.raises(LogosNodeCommandError, match="reserved"):
            registry._check_benchmark_reservation(session, action, {"lane_id": lane["lane_id"]}, request_id)
    finally:
        benchmark_reservations.finish_request(request_id)
        benchmark_reservations.release(job_id)


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


async def test_queue_dispatch_admits_request_before_waiter_resumes():
    import asyncio

    lease = BenchmarkReservations()
    queue = PriorityQueueManager()
    admitted = asyncio.get_running_loop().create_future()
    waiting = asyncio.get_running_loop().create_future()
    queue.enqueue(admitted, 1, request_id="dispatched", api_key_id=12)
    queue.enqueue(waiting, 1, request_id="still-queued", api_key_id=12)

    def dequeue(owner):
        return queue.dequeue_with_entry(1, 2, required_api_key_id=-owner if owner is not None else None)

    assert lease.admit_queued(2, "m", dequeue)[0] is admitted
    lease.reserve(2, "m", 7)
    assert lease.allows(2, "m", "dispatched")
    assert not lease.allows(2, "m", "still-queued")
    assert lease.admit_queued(2, "m", dequeue) == (None, None)
    lease.finish_request("dispatched")
    assert not lease.admitted_requests(2, "m")
    lease.release(7)
    assert lease.admit_queued(2, "m", dequeue)[0] is waiting


@pytest.mark.parametrize("action", ["infer", "infer_stream"])
async def test_released_queue_request_keeps_transport_access_during_benchmark(action):
    import asyncio

    from logos.pipeline.base_scheduler import BaseScheduler

    queue = PriorityQueueManager()
    future = asyncio.get_running_loop().create_future()
    queue.enqueue(future, 1, request_id="released-production", api_key_id=12)
    facade = MagicMock()
    facade.is_provider_cordoned.return_value = False
    facade.get_model_name.return_value = "queued-model"
    facade.get_model_status.return_value = SimpleNamespace(active_requests=0)
    facade.get_parallel_capacity.return_value = (1, None)
    scheduler = SimpleNamespace(
        _model_registry={(1, 9030): "logosnode"},
        _logosnode=facade,
        _queue_mgr=queue,
        _admission_batch_limit=lambda *args: 1,
    )
    BaseScheduler.reevaluate_model_queues(scheduler, "queued-model")
    # The queue release is scheduled, but its waiter has not resumed yet.
    benchmark_reservations.reserve(9030, "queued-model", 9031)
    try:
        assert (await future).provider_id == 9030
        session = SimpleNamespace(
            provider_id=9030, latest_runtime={"lanes": [{"lane_id": "lane", "model": "queued-model"}]}
        )
        LogosNodeRuntimeRegistry._check_benchmark_reservation(
            session, action, {"lane_id": "lane"}, "released-production"
        )
        assert not benchmark_reservations.allows(9030, "queued-model", "new-production")
        benchmark_reservations.finish_request("released-production")
        with pytest.raises(LogosNodeCommandError, match="reserved"):
            LogosNodeRuntimeRegistry._check_benchmark_reservation(
                session, action, {"lane_id": "lane"}, "released-production"
            )
    finally:
        benchmark_reservations.finish_request("released-production")
        benchmark_reservations.release(9031)


def test_model_job_cleanup_takes_priority_over_owning_nightly_reservation():
    lease = BenchmarkReservations()
    lease.reserve(1, "*", -31)
    lease.reserve(1, "model", 7)
    assert lease.provider_owner(1) == 7
    lease.release(7)
    assert lease.provider_owner(1) == -31


def test_atomic_capacity_admission_survives_nightly_worker_drain():
    lease = BenchmarkReservations()
    assert lease.try_admit(1, "model", "admitted", lambda: True)
    lease.reserve(1, "*", -31)
    assert lease.allows(1, "model", "admitted")
    assert not lease.try_admit(1, "model", "new", lambda: True)
    lease.finish_request("admitted", deployment=(1, "model"))
    assert not lease.allows(1, "model", "admitted")
