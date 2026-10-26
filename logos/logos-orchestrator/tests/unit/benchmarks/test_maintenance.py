import asyncio
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from logos.benchmarks import maintenance as module
from logos.logosnode_registry import LogosNodeCommandError, LogosNodeOfflineError, MaintenanceBusyError


@pytest.fixture
def coordinator(monkeypatch):
    state = {"claim": None, "locked": False, "benchmark": False, "recovery": False}

    @contextmanager
    def lock():
        if state["locked"]:
            yield None
            return
        state["locked"] = True
        try:
            yield object()
        finally:
            state["locked"] = False

    def claim(pid, token, automatic=False):
        assert state["claim"] is None
        state["claim"] = dict(
            provider_id=pid, token=token, confirmed=False, automatic=automatic, created_at=datetime.now(UTC)
        )

    def confirm(token):
        assert state["claim"]["token"] == token
        state["claim"]["confirmed"] = True

    def release(token):
        assert state["claim"]["token"] == token
        state["claim"] = None

    monkeypatch.setattr(module.store, "cluster_lock", lock)
    monkeypatch.setattr(module.store, "lock_held", lambda _: state["locked"])
    monkeypatch.setattr(module.store, "has_active_benchmarks", lambda: state["benchmark"])
    monkeypatch.setattr(module.store, "has_recovery", lambda: state["recovery"])
    monkeypatch.setattr(module.store, "calibration_claims", lambda: [state["claim"]] if state["claim"] else [])
    monkeypatch.setattr(module.store, "claim_calibration", claim)
    monkeypatch.setattr(module.store, "confirm_calibration", confirm)
    monkeypatch.setattr(module.store, "release_calibration", release)
    registry = MagicMock()
    registry.active_provider_ids.return_value = [1, 2]
    registry.is_calibrating.return_value = False
    registry.send_command = AsyncMock(return_value={"calibrating": False})
    service = module.MaintenanceCoordinator(registry)
    return service, state


async def dispatch(callback):
    callback(None)
    return {"ok": True}


async def test_serializes_calibrations_across_providers_and_until_worker_completion(coordinator):
    service, state = coordinator
    await service.start_calibration(1, dispatch)
    with pytest.raises(MaintenanceBusyError):
        await service.start_calibration(2, dispatch)
    service.registry.send_command.return_value = {"calibrating": True}
    assert await service.reconcile() == []
    assert state["claim"] is not None
    service.registry.send_command.return_value = {"calibrating": False}
    assert await service.reconcile() == [1]
    await service.start_calibration(2, dispatch)
    assert state["claim"]["provider_id"] == 2


async def test_concurrent_manual_calibration_cannot_enter_before_first_start_ack(coordinator):
    service, _ = coordinator
    sent, finish = asyncio.Event(), asyncio.Event()

    async def slow_send(callback):
        callback(None)
        sent.set()
        await finish.wait()

    first = asyncio.create_task(service.start_calibration(1, slow_send))
    await sent.wait()
    try:
        with pytest.raises(MaintenanceBusyError):
            await service.start_calibration(2, dispatch)
    finally:
        finish.set()
        await first


@pytest.mark.parametrize("blocker", ["benchmark", "recovery"])
async def test_benchmark_and_recovery_block_calibration(coordinator, blocker):
    service, state = coordinator
    state[blocker] = True
    send = AsyncMock()
    with pytest.raises(MaintenanceBusyError):
        await service.start_calibration(1, send)
    send.assert_not_awaited()
    assert state["claim"] is None


async def test_live_calibration_without_claim_also_blocks(coordinator):
    service, _ = coordinator
    service.registry.is_calibrating.return_value = True
    with pytest.raises(MaintenanceBusyError):
        await service.start_calibration(2, dispatch)


@pytest.mark.parametrize("dispatched", [False, True])
async def test_uncertain_dispatch_retains_claim_until_explicit_stop(coordinator, dispatched):
    service, state = coordinator

    async def timeout(callback):
        if dispatched:
            callback(None)
        raise TimeoutError()

    with pytest.raises(TimeoutError):
        await service.start_calibration(1, timeout)
    assert (state["claim"] is not None) == dispatched
    if dispatched:
        assert not state["claim"]["confirmed"]
        await service.reconcile()
        service.registry.send_command.assert_not_awaited()
        await service.stop_calibration(1, AsyncMock())
        assert state["claim"] is None


@pytest.mark.parametrize("result", [{"calibrating": False}, {"calibrating": True}])
async def test_lost_start_reply_is_reconciled_after_grace(coordinator, result):
    service, state = coordinator

    async def timeout(callback):
        callback(None)
        raise TimeoutError()

    with pytest.raises(TimeoutError):
        await service.start_calibration(1, timeout)
    state["claim"]["created_at"] -= module.UNCONFIRMED_CLAIM_GRACE
    service.registry.send_command.return_value = result
    # Released, but not reported as completed: the start may never have run.
    assert await service.reconcile() == []
    service.registry.send_command.assert_awaited_once_with(1, "get_calibration_status", {}, timeout_seconds=20)
    assert (state["claim"] is None) == (not result["calibrating"])


async def test_stop_ack_alone_does_not_release_calibration(coordinator):
    service, state = coordinator
    await service.start_calibration(1, dispatch)
    service.registry.send_command.return_value = {"calibrating": True}
    await service.stop_calibration(1, AsyncMock())
    assert state["claim"] is not None
    service.registry.send_command.side_effect = TimeoutError()
    with pytest.raises(TimeoutError):
        await service.stop_calibration(1, AsyncMock())
    assert state["claim"] is not None


async def test_lock_loss_before_dispatch_releases_only_undispatched_claim(coordinator, monkeypatch):
    service, state = coordinator
    monkeypatch.setattr(module.store, "lock_held", lambda _: False)
    with pytest.raises(LogosNodeCommandError):
        await service.start_calibration(1, dispatch)
    assert state["claim"] is None


async def test_automatic_claim_survives_without_context_leaking_to_manual_start(coordinator):
    service, state = coordinator
    token = module.AUTOMATIC_CALIBRATION.set(True)
    try:
        await service.start_calibration(1, dispatch)
    finally:
        module.AUTOMATIC_CALIBRATION.reset(token)
    assert state["claim"]["automatic"]
    await service.reconcile()
    await service.start_calibration(2, dispatch)
    assert not state["claim"]["automatic"]


async def test_cancelled_benchmark_releases_only_after_cleanup(coordinator, monkeypatch):
    service, _ = coordinator
    events = []
    started = asyncio.Event()
    monkeypatch.setattr(module.store, "release_benchmark", lambda job: events.append(("released", job)))

    async def execute():
        started.set()
        try:
            await asyncio.Future()
        finally:
            await asyncio.sleep(0)
            events.append("cleaned")

    task = asyncio.create_task(service.run_benchmark(7, execute))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert events == ["cleaned", ("released", 7)]


async def test_registry_routes_all_calibration_starts_through_coordinator(coordinator):
    from logos.logosnode_registry import LogosNodeRuntimeRegistry

    service, state = coordinator
    registry = LogosNodeRuntimeRegistry.__new__(LogosNodeRuntimeRegistry)
    registry.maintenance = service
    caller_callback = MagicMock()

    async def send(*args):
        args[-1](None)
        return {"ok": True}

    registry._send_command = AsyncMock(side_effect=send)
    await registry.send_command(1, "start_calibration_session", on_dispatched=caller_callback)
    assert state["claim"]["confirmed"]
    caller_callback.assert_called_once_with(None)
    with pytest.raises(MaintenanceBusyError):
        await registry.send_command(2, "start_calibration_session")
    registry._send_command.assert_awaited_once()


def test_pending_calibration_keeps_priority_while_worker_is_busy():
    from logos.capacity.calibration_orchestrator import CalibrationOrchestrator

    registry, facade = MagicMock(), MagicMock()
    facade.provider_ids.return_value = [1]
    service = CalibrationOrchestrator(registry, facade)
    service._is_in_window = lambda: True
    service._was_in_window = True
    service._provider_is_unhealthy = lambda _: False
    service._provider_has_active_requests = lambda _: True
    service._provider_has_uncalibrated_models = lambda _: True
    assert service._pick_next_provider() is None
    assert service.benchmarks_must_wait()
    service._completed_this_window.add(1)
    assert not service.benchmarks_must_wait()
    service._completed_this_window.clear()
    service._config.enabled = False
    assert not service.benchmarks_must_wait()


async def test_busy_admission_does_not_mark_calibration_attempt_completed():
    from logos.capacity.calibration_orchestrator import CalibrationOrchestrator

    registry, facade = MagicMock(), MagicMock()
    registry.send_command = AsyncMock(side_effect=MaintenanceBusyError("benchmark still cleaning up"))
    service = CalibrationOrchestrator(registry, facade)
    service._capacity_skip_models = lambda _: frozenset()
    await service._start_session_on(1)
    assert service._active_provider_ids == set()
    assert 1 not in service._completed_this_window


async def test_running_session_refusal_releases_claim_after_idle_status(coordinator):
    from logos.logosnode_registry import LogosNodeCommandRejectedError

    service, state = coordinator

    async def refuse(callback):
        callback(None)
        raise LogosNodeCommandRejectedError(module.SESSION_ALREADY_RUNNING)

    with pytest.raises(LogosNodeCommandRejectedError):
        await service.start_calibration(1, refuse)
    service.registry.send_command.assert_awaited_once_with(1, "get_calibration_status", {}, timeout_seconds=20)
    assert state["claim"] is None
    await service.start_calibration(2, dispatch)
    assert state["claim"]["provider_id"] == 2


@pytest.mark.parametrize("result", [{"calibrating": True}, {}, TimeoutError()])
async def test_refused_start_retains_claim_until_fresh_idle_confirmation(coordinator, result):
    from logos.logosnode_registry import LogosNodeCommandRejectedError

    service, state = coordinator
    if isinstance(result, Exception):
        service.registry.send_command.side_effect = result
    else:
        service.registry.send_command.return_value = result

    async def refuse(callback):
        callback(None)
        raise LogosNodeCommandRejectedError(module.SESSION_ALREADY_RUNNING)

    with pytest.raises(LogosNodeCommandRejectedError):
        await service.start_calibration(1, refuse)
    assert state["claim"] is not None
    with pytest.raises(MaintenanceBusyError):
        await service.start_calibration(2, dispatch)
    service.registry.send_command.side_effect = None
    service.registry.send_command.return_value = {"calibrating": False}
    await service.reconcile()
    assert state["claim"] is None


async def test_parallel_calibration_admission_respects_limit_and_worker_identity(coordinator, monkeypatch):
    service, _ = coordinator
    monkeypatch.setenv("LOGOS_MAINTENANCE_MAX_NODES", "2")
    claims = {}
    monkeypatch.setattr(module.store, "calibration_claims", lambda: list(claims.values()))
    monkeypatch.setattr(
        module.store,
        "claim_calibration",
        lambda pid, token, automatic: claims.update(
            {pid: dict(provider_id=pid, token=token, automatic=automatic, confirmed=False)}
        ),
    )
    monkeypatch.setattr(
        module.store,
        "confirm_calibration",
        lambda token: next(claim for claim in claims.values() if claim["token"] == token).update(confirmed=True),
    )
    await service.start_calibration(1, dispatch)
    with pytest.raises(MaintenanceBusyError):
        await service.start_calibration(1, dispatch)
    await service.start_calibration(2, dispatch)
    with pytest.raises(MaintenanceBusyError):
        await service.start_calibration(3, dispatch)
    assert set(claims) == {1, 2}


@pytest.mark.parametrize("failure", ["offline", "timeout", "command"])
async def test_unreachable_claim_does_not_prevent_reconciliation_of_healthy_worker(coordinator, monkeypatch, failure):
    from logos.logosnode_registry import LogosNodeOfflineError

    service, _ = coordinator
    claims = [dict(provider_id=1, token="one", confirmed=True), dict(provider_id=2, token="two", confirmed=True)]
    monkeypatch.setattr(module.store, "calibration_claims", lambda: claims)
    released = []
    monkeypatch.setattr(module.store, "release_calibration", released.append)
    error = {
        "offline": LogosNodeOfflineError("offline"),
        "timeout": TimeoutError(),
        "command": LogosNodeCommandError("refused"),
    }[failure]
    service.registry.send_command.side_effect = [error, {"calibrating": False}]
    assert await service.reconcile() == [2]
    assert released == ["two"]


async def test_automatic_calibration_starts_two_workers_and_stops_both_at_window_end(monkeypatch):
    from logos.capacity.calibration_orchestrator import CalibrationOrchestrator

    monkeypatch.setenv("LOGOS_MAINTENANCE_MAX_NODES", "2")
    registry, facade = MagicMock(), MagicMock()
    registry.is_cordoned.return_value = False
    registry.send_command = AsyncMock()
    facade.provider_ids.return_value = [1, 2, 3]
    service = CalibrationOrchestrator(registry, facade)
    service._is_in_window = lambda: True
    service._provider_is_unhealthy = lambda _: False
    service._provider_has_active_requests = lambda _: False
    service._provider_has_uncalibrated_models = lambda _: True
    service._capacity_skip_models = lambda _: frozenset()
    await service._tick()
    assert service._active_provider_ids == {1, 2}
    assert [c.args[0] for c in registry.send_command.await_args_list] == [1, 2]
    service._is_in_window = lambda: False
    registry.send_command.reset_mock()
    await service._tick()
    assert {c.args[0] for c in registry.send_command.await_args_list} == {1, 2}
    assert all(c.args[1] == "stop_calibration_session" for c in registry.send_command.await_args_list)


@pytest.mark.parametrize(
    "error",
    [
        "calibration is unavailable on the Metal backend: it measures against nvidia-smi",
        "node is in a degraded state (reason=gpu_error): GPU 0 ERR",
    ],
)
async def test_refusal_without_running_session_releases_claim_at_once(coordinator, error):
    from logos.logosnode_registry import LogosNodeCommandRejectedError

    service, state = coordinator

    async def refuse(callback):
        callback(None)
        raise LogosNodeCommandRejectedError(error)

    with pytest.raises(LogosNodeCommandRejectedError):
        await service.start_calibration(1, refuse)
    assert state["claim"] is None
    # The refusal itself settles it; the worker may not even know the status command.
    service.registry.send_command.assert_not_awaited()
    await service.start_calibration(2, dispatch)
    assert state["claim"]["provider_id"] == 2


@pytest.mark.parametrize("calibrating", [False, True])
async def test_worker_without_status_command_is_judged_by_its_status_reports(coordinator, calibrating):
    service, state = coordinator
    await service.start_calibration(1, dispatch)
    service.registry.send_command.side_effect = LogosNodeCommandError(
        "Unsupported bridge command 'get_calibration_status'"
    )
    service.registry.is_calibrating.return_value = calibrating
    assert await service.reconcile() == ([] if calibrating else [1])
    assert (state["claim"] is not None) == calibrating


async def test_other_status_command_errors_keep_the_claim(coordinator):
    service, state = coordinator
    await service.start_calibration(1, dispatch)
    service.registry.send_command.side_effect = LogosNodeCommandError("worker busy")
    assert await service.reconcile() == []
    assert state["claim"] is not None


async def _claimed(service, state, confirmed=True):
    await service.start_calibration(1, dispatch)
    state["claim"]["confirmed"] = confirmed
    state["claim"]["age_s"] = 5
    return state["claim"]["token"]


async def test_release_claim_of_offline_worker_releases_without_contacting_it(coordinator):
    service, state = coordinator
    token = await _claimed(service, state)
    service.registry.is_provider_online.return_value = False
    service.registry._send_command = AsyncMock()
    assert await service.release_claim(1, token) == {"released": True, "forced": True}
    assert state["claim"] is None
    service.registry._send_command.assert_not_awaited()


async def test_release_claim_stops_an_online_worker_before_releasing(coordinator):
    service, state = coordinator
    token = await _claimed(service, state)
    service.registry.is_provider_online.return_value = True
    service.registry._send_command = AsyncMock(return_value={"ok": True, "was_active": True})
    assert await service.release_claim(1, token) == {"released": True, "forced": False}
    service.registry._send_command.assert_awaited_once_with(1, "stop_calibration_session", {}, 30)
    assert state["claim"] is None


@pytest.mark.parametrize("status", [{"calibrating": True}, LogosNodeCommandError("Unsupported bridge command")])
async def test_release_claim_refuses_while_the_worker_reports_a_session(coordinator, status):
    service, state = coordinator
    token = await _claimed(service, state)
    service.registry.is_provider_online.return_value = True
    service.registry.is_calibrating.return_value = True
    service.registry._send_command = AsyncMock(return_value={"ok": True})
    if isinstance(status, Exception):
        service.registry.send_command.side_effect = status
    else:
        service.registry.send_command.return_value = status
    with pytest.raises(MaintenanceBusyError):
        await service.release_claim(1, token)
    assert state["claim"] is not None


@pytest.mark.parametrize(
    "failure", [TimeoutError(), LogosNodeOfflineError("Command timeout waiting for worker response")]
)
async def test_release_claim_keeps_the_claim_of_an_online_worker_that_does_not_answer(coordinator, failure):
    service, state = coordinator
    token = await _claimed(service, state)
    service.registry.is_provider_online.return_value = True
    service.registry._send_command = AsyncMock(side_effect=failure)
    with pytest.raises(MaintenanceBusyError, match="did not answer"):
        await service.release_claim(1, token)
    assert state["claim"] is not None


async def test_release_claim_releases_once_the_silent_worker_is_offline(coordinator):
    service, state = coordinator
    token = await _claimed(service, state)
    online = iter([True, False])
    service.registry.is_provider_online.side_effect = lambda _pid: next(online)
    service.registry._send_command = AsyncMock(side_effect=LogosNodeOfflineError("No active logosnode worker session"))
    assert await service.release_claim(1, token) == {"released": True, "forced": True}
    assert state["claim"] is None


async def test_release_claim_of_a_worker_that_refuses_the_stop_uses_its_status_reports(coordinator):
    service, state = coordinator
    token = await _claimed(service, state)
    service.registry.is_provider_online.return_value = True
    service.registry._send_command = AsyncMock(side_effect=LogosNodeCommandError("Unsupported bridge command"))
    assert await service.release_claim(1, token) == {"released": True, "forced": True}
    assert state["claim"] is None


async def test_release_claim_waits_for_an_unconfirmed_start_on_an_online_worker(coordinator):
    service, state = coordinator
    token = await _claimed(service, state, confirmed=False)
    service.registry.is_provider_online.return_value = True
    with pytest.raises(MaintenanceBusyError):
        await service.release_claim(1, token)
    assert state["claim"] is not None
    state["claim"]["age_s"] = module.UNCONFIRMED_CLAIM_GRACE.total_seconds()
    service.registry._send_command = AsyncMock(return_value={"ok": True})
    assert (await service.release_claim(1, token))["released"]


async def test_release_claim_needs_the_current_token(coordinator):
    service, state = coordinator
    await _claimed(service, state)
    with pytest.raises(LookupError):
        await service.release_claim(1, "older-token")
    with pytest.raises(LookupError):
        await service.release_claim(2, state["claim"]["token"])
    assert state["claim"] is not None


def test_slot_status_lists_claims_live_sessions_benchmarks_and_recoveries(coordinator, monkeypatch):
    service, _ = coordinator
    since = datetime(2026, 10, 22, 4, 0, tzinfo=UTC)
    monkeypatch.setattr(
        module.store,
        "maintenance_holders",
        lambda: {
            "calibrations": [
                dict(
                    provider_id=1,
                    provider_name="worker-a",
                    token="t1",
                    automatic=True,
                    confirmed=True,
                    created_at=since,
                    age_s=61.7,
                )
            ],
            "benchmarks": [dict(job_id=7, status="running", provider_id=2, model_name="m", nightly=False, age_s=3.2)],
            "recoveries": [],
        },
    )
    service.registry.active_provider_ids.return_value = [1, 2]
    service.registry.is_calibrating.side_effect = lambda pid: True
    service.registry.is_provider_online.side_effect = lambda pid: pid == 2
    service.registry.supports_action.return_value = False
    status = service.slot_status()
    assert status["free"] is False
    assert status["limit"] == 1
    first, second = status["calibrations"]
    assert first == dict(
        provider_id=1,
        provider_name="worker-a",
        claim_token="t1",
        automatic=True,
        confirmed=True,
        since=since,
        age_s=61,
        online=False,
        calibrating=True,
        status_supported=False,
    )
    assert second["provider_id"] == 2 and second["claim_token"] is None and second["online"]
    assert status["benchmarks"][0]["age_s"] == 3


def test_slot_status_reports_a_free_slot(coordinator, monkeypatch):
    service, _ = coordinator
    monkeypatch.setattr(
        module.store, "maintenance_holders", lambda: {"calibrations": [], "benchmarks": [], "recoveries": []}
    )
    status = service.slot_status()
    assert status["free"] is True
    assert status["calibrations"] == status["benchmarks"] == status["recoveries"] == []


def test_automatic_calibration_skips_workers_without_the_status_command():
    from logos.capacity.calibration_orchestrator import CalibrationOrchestrator

    registry, facade = MagicMock(), MagicMock()
    facade.provider_ids.return_value = [1, 2]
    registry.is_cordoned.return_value = False
    registry.supports_action.side_effect = lambda pid, action: pid == 2 or action != "get_calibration_status"
    service = CalibrationOrchestrator(registry, facade)
    service._is_in_window = lambda: True
    service._was_in_window = True
    service._provider_is_unhealthy = lambda _: False
    service._provider_has_active_requests = lambda _: False
    service._provider_has_uncalibrated_models = lambda _: True
    assert service._pick_next_provider() == 2
    assert service._pick_next_provider(excluding={2}) is None
    # A worker that cannot be calibrated automatically does not hold benchmarks back.
    facade.provider_ids.return_value = [1]
    assert not service.benchmarks_must_wait()


ORIGINAL = {"max_num_seqs": 16}


@pytest.fixture
def recovery(coordinator, monkeypatch):
    import importlib

    from logos.benchmarks.reservations import benchmark_reservations

    main = importlib.import_module("logos.main")
    service, state = coordinator
    state.update(
        row={
            "model_provider_id": 31,
            "report": [{"status": "ok"}],
            "recovery": {"provider_id": 20, "lane_id": "lane", "model": "model", "vllm_config": ORIGINAL},
        },
        execution_busy=False,
        jobs=[],
        saved=[],
        fenced=[],
        finished=[],
    )

    @contextmanager
    def execution_lock(_pair):
        yield None if state["execution_busy"] else object()

    monkeypatch.setattr(module.store, "rows", lambda: [state["row"]])
    monkeypatch.setattr(module.store, "execution_lock", execution_lock)
    monkeypatch.setattr(module.store, "execution_lock_held", lambda *_: True)
    monkeypatch.setattr(module.store, "recovery_jobs", lambda _: list(state["jobs"]))
    monkeypatch.setattr(module.store, "fence_recovery_jobs", lambda ids: state["fenced"].extend(ids))
    monkeypatch.setattr(module.store, "finish_recovery_jobs", lambda ids: state["finished"].extend(ids))
    monkeypatch.setattr(module.store, "save", lambda *args: state["saved"].append(args))
    monkeypatch.setattr(main, "_benchmark_tasks_by_job", {})
    service.registry.send_command = AsyncMock(
        return_value={"lanes": [{"lane_id": "lane", "lane_config": {"vllm_config": dict(ORIGINAL)}}]}
    )
    benchmark_reservations.reserve(20, "*", -31)
    yield service, state
    benchmark_reservations.release(-31)


def _reserved():
    from logos.benchmarks.reservations import benchmark_reservations

    return benchmark_reservations.owner(20, "model") == -31


async def test_release_recovery_after_the_worker_shows_the_original_settings(recovery):
    service, state = recovery
    assert await service.release_recovery(31) == {"released": True, "forced": False}
    service.registry.send_command.assert_awaited_once_with(20, "get_lanes", {}, timeout_seconds=30)
    assert state["saved"] == [(31, "interrupted_recovered", [{"status": "ok"}], None)]
    assert not _reserved()


@pytest.mark.parametrize(
    "reply",
    [
        {"lanes": []},
        {"lanes": [{"lane_id": "lane", "lane_config": {"vllm_config": {"max_num_seqs": 64}}}]},
        LogosNodeCommandError("worker offline"),
        TimeoutError(),
    ],
)
async def test_release_recovery_refuses_without_proof_and_force_releases(recovery, reply):
    service, state = recovery
    if isinstance(reply, Exception):
        service.registry.send_command.side_effect = reply
    else:
        service.registry.send_command.return_value = reply
    with pytest.raises(MaintenanceBusyError):
        await service.release_recovery(31)
    assert not state["saved"]
    assert _reserved()
    assert await service.release_recovery(31, force=True) == {"released": True, "forced": True}
    assert state["saved"][-1][1:] == ("interrupted_recovered", [{"status": "ok"}], None)
    assert not _reserved()


async def test_release_recovery_refuses_while_a_recovery_runs(recovery):
    service, state = recovery
    state["execution_busy"] = True
    with pytest.raises(MaintenanceBusyError, match="A recovery is running right now"):
        await service.release_recovery(31, force=True)
    assert not state["saved"]


async def test_release_recovery_refuses_while_the_cluster_lock_is_taken(recovery):
    service, state = recovery
    state["locked"] = True
    with pytest.raises(MaintenanceBusyError):
        await service.release_recovery(31, force=True)
    assert not state["saved"]


async def test_release_recovery_without_a_journal_is_not_found(recovery):
    service, state = recovery
    state["row"] = {**state["row"], "recovery": None}
    with pytest.raises(LookupError):
        await service.release_recovery(31)
    with pytest.raises(LookupError):
        await service.release_recovery(99, force=True)


async def test_release_recovery_fails_its_orphaned_jobs(recovery):
    service, state = recovery
    state["jobs"] = [701]
    assert (await service.release_recovery(31))["released"]
    assert state["fenced"] == [701]
    assert state["finished"] == [701]


async def test_release_recovery_refuses_while_one_of_its_jobs_still_runs(recovery, monkeypatch):
    import importlib

    main = importlib.import_module("logos.main")
    service, state = recovery
    state["jobs"] = [701]
    monkeypatch.setitem(main._benchmark_tasks_by_job, 701, MagicMock(done=lambda: False))
    with pytest.raises(MaintenanceBusyError):
        await service.release_recovery(31, force=True)
    assert not state["saved"]


async def test_release_recovery_of_an_unchanged_lane_needs_no_worker(recovery):
    service, state = recovery
    state["row"]["recovery"]["mutated"] = False
    service.registry.send_command.side_effect = LogosNodeCommandError("worker offline")
    assert await service.release_recovery(31) == {"released": True, "forced": False}
