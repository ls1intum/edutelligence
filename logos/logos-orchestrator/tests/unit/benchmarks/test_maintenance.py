import asyncio
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from logos.benchmarks import maintenance as module
from logos.logosnode_registry import LogosNodeCommandError, MaintenanceBusyError


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
    assert await service.reconcile() == ([] if result["calibrating"] else [1])
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


async def test_explicit_idle_refusal_releases_manual_claim_for_next_start(coordinator):
    from logos.logosnode_registry import LogosNodeCommandRejectedError

    service, state = coordinator

    async def refuse(callback):
        callback(None)
        raise LogosNodeCommandRejectedError("Node is degraded")

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
        raise LogosNodeCommandRejectedError("Worker refused calibration")

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
