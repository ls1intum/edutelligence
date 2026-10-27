import asyncio
from contextlib import nullcontext
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from logos.benchmarks import nightly_scheduler as module
from logos.benchmarks.nightly import NightlyStopped
from logos.benchmarks.reservations import benchmark_reservations


@pytest.fixture
def scheduler(monkeypatch):
    monkeypatch.delenv("LOGOS_MAINTENANCE_MAX_NODES", raising=False)
    registry = MagicMock()
    registry.is_provider_online.return_value = True
    registry.has_received_first_status.return_value = True
    registry.is_calibrating.return_value = False
    registry.send_command = AsyncMock(return_value={"lanes": []})
    registry.active_provider_ids.return_value = [20, 21]
    registry.peek_runtime_snapshot.return_value = {
        "runtime": {
            "supports_benchmark_restart": True,
            "lanes": [
                {
                    "lane_id": "lane",
                    "runtime_state": "running",
                    "model": "model",
                    "lane_config": {
                        "lane_id": "lane",
                        "model": "model",
                        "vllm": True,
                        "vllm_config": {"max_num_seqs": 16, "max_num_batched_tokens": 4096},
                    },
                }
            ],
            "devices": {"nvidia_smi_available": True, "devices": [{"kind": "nvidia"}]},
        }
    }
    planner = MagicMock()
    planner._facade.model_inflight_requests.return_value = 0
    planner._drain_lane = AsyncMock(return_value=True)
    planner.is_worker_locked.return_value = False
    service = module.NightlyScheduler(registry, planner)
    service.restore = AsyncMock()
    db = MagicMock()
    db.__enter__.return_value = db
    db.get_model_provider_benchmark_target.return_value = {
        "provider_id": 20,
        "provider_type": "logosnode",
        "model_name": "model",
    }
    monkeypatch.setattr(module, "DBManager", lambda: db)
    monkeypatch.setattr(module, "local_now", lambda: datetime.fromisoformat("2026-10-13T05:00:00+02:00"))
    monkeypatch.setattr(module.store, "status", lambda _: {"enabled": True})
    monkeypatch.setattr(module.store, "lock_held", lambda _: True)
    monkeypatch.setattr(module.store, "execution_lock", lambda _: nullcontext(object()))
    monkeypatch.setattr(module.store, "execution_lock_held", lambda *args: True)
    monkeypatch.setattr(module.store, "recovery_jobs", lambda _: [])
    monkeypatch.setattr(module.store, "fence_recovery_jobs", lambda _: None)
    monkeypatch.setattr(module.store, "finish_recovery_jobs", lambda _: None)
    planner._facade.reserve_worker_for_drain.side_effect = lambda pid, owner: benchmark_reservations.reserve(
        pid, "*", owner
    )
    monkeypatch.setattr(module.store, "record_comparison", MagicMock())
    service.saved = []
    monkeypatch.setattr(module.store, "save", lambda *args: service.saved.append(args))
    yield service
    benchmark_reservations.release(-31)


async def test_stall_retries_same_configuration_once_then_moves_on(scheduler):
    calls = []

    async def submit(pair, settings):
        calls.append(settings.model_dump())

        async def execute():
            if len(calls) <= 2:
                raise NightlyStopped("stalled")
            return len(calls)

        return len(calls), asyncio.create_task(execute())

    scheduler.submit = submit
    assert await scheduler.run_schedule(31, MagicMock())
    assert len(calls) == 6
    assert calls[0] == calls[1]
    assert calls[2] != calls[1]
    assert scheduler.saved[-1][1] == "completed"
    assert scheduler.saved[-1][3] is None
    assert benchmark_reservations.owner(20, "other") is None


async def test_cutoff_stops_remaining_configurations_and_restores(scheduler):
    async def execute():
        raise NightlyStopped("window_closed_below_half")

    scheduler.submit = AsyncMock(side_effect=lambda *args: asyncio.sleep(0))

    async def submit(*args):
        return 7, asyncio.create_task(execute())

    scheduler.submit = AsyncMock(side_effect=submit)
    assert await scheduler.run_schedule(31, MagicMock())
    assert scheduler.submit.await_count == 1
    scheduler.restore.assert_awaited_once()
    assert scheduler.saved[-1][1] == "window_closed_below_half"


async def test_recovery_failure_holds_node_and_stops_other_schedules(scheduler):
    scheduler.restore.side_effect = RuntimeError("worker disconnected")

    async def submit(*args):
        return 7, asyncio.create_task(asyncio.sleep(0, result=1))

    scheduler.submit = submit
    assert not await scheduler.run_schedule(31, MagicMock())
    assert scheduler.saved[-1][1] == "recovery_required"
    assert scheduler.saved[-1][3] is not None
    assert not benchmark_reservations.allows(20, "other", "production")


async def test_no_configuration_or_retry_starts_at_0450(scheduler, monkeypatch):
    monkeypatch.setattr(module, "local_now", lambda: datetime.fromisoformat("2026-10-13T07:50:00+02:00"))
    scheduler.submit = AsyncMock()
    assert await scheduler.run_schedule(31, MagicMock())
    scheduler.submit.assert_not_awaited()
    assert scheduler.saved[-1][1] == "window_closed"


async def test_lost_cluster_lock_keeps_recovery_journal(scheduler, monkeypatch):
    async def submit(*args):
        async def run():
            raise NightlyStopped("lease_lost")

        return 7, asyncio.create_task(run())

    scheduler.submit = submit
    monkeypatch.setattr(module.store, "lock_held", lambda _: False)
    assert not await scheduler.run_schedule(31, MagicMock())
    scheduler.restore.assert_not_awaited()
    assert scheduler.saved[-1][3] is not None


async def test_failed_initial_drain_releases_worker_without_restart(scheduler):
    scheduler.restore = module.NightlyScheduler.restore.__get__(scheduler)
    scheduler.planner._drain_lane.return_value = False
    scheduler.submit = AsyncMock()
    assert await scheduler.run_schedule(31, MagicMock())
    scheduler.submit.assert_not_awaited()
    scheduler.registry.send_command.assert_not_called()
    assert scheduler.saved[-1][1] == "failed"
    assert scheduler.saved[-1][3] is None
    assert benchmark_reservations.allows(20, "model", "production")


@pytest.fixture
def rotation(scheduler, monkeypatch):
    rows = [
        {"model_provider_id": pair, "enabled": True, "last_run_date": None, "recovery": None, "report": []}
        for pair in (31, 32, 33)
    ]
    claimed = set()
    monkeypatch.setattr(module.store, "rows", lambda: rows)
    monkeypatch.setattr(module.store, "cluster_lock", MagicMock())
    monkeypatch.setattr(module.store, "has_active_benchmarks", lambda **kwargs: False)
    monkeypatch.setattr(module.store, "claimed_today", lambda day: len(claimed))

    def claim(pair, day):
        if pair in claimed:
            return False
        claimed.add(pair)
        return True

    monkeypatch.setattr(module.store, "claim", claim)
    scheduler.run_schedule = AsyncMock(return_value=True)
    scheduler.target_lane = MagicMock(side_effect=lambda pair: ({"provider_id": pair}, {}, {}))
    return rows, claimed


async def test_rotation_admits_two_pairs_sequentially_and_keeps_daily_cap(scheduler, rotation):
    _, claimed = rotation
    await scheduler.tick()
    await scheduler.tick()
    assert claimed == {31, 32}
    assert [call.args[0] for call in scheduler.run_schedule.await_args_list] == [31, 32]


async def test_unavailable_pair_does_not_consume_a_nightly_slot(scheduler, rotation):
    _, claimed = rotation
    scheduler.target_lane.side_effect = [
        RuntimeError("Worker is offline"),
        ({"provider_id": 32}, {}, {}),
        ({"provider_id": 33}, {}, {}),
    ]
    await scheduler.tick()
    assert claimed == {32, 33}
    assert scheduler.saved[0][1] == "unavailable"


async def test_all_pending_recovery_precedes_any_new_pair(scheduler, rotation):
    rows, claimed = rotation
    rows[2]["recovery"] = {"provider_id": 20}
    scheduler.restore.side_effect = RuntimeError("Worker is offline")
    await scheduler.tick()
    assert claimed == set()
    scheduler.run_schedule.assert_not_awaited()


async def test_daily_quota_never_blocks_pending_recovery(scheduler, rotation):
    rows, claimed = rotation
    rows[2]["recovery"] = {"provider_id": 20}
    claimed.update({31, 32})
    await scheduler.tick()
    scheduler.restore.assert_awaited_once()
    scheduler.run_schedule.assert_not_awaited()


async def test_calibration_runs_before_benchmarks_even_without_enabled_schedules(scheduler, monkeypatch):
    events = []
    scheduler.calibration = MagicMock()
    scheduler.calibration._active_provider_ids = set()
    scheduler.calibration._tick = AsyncMock(side_effect=lambda: events.append("calibration"))
    scheduler.tick = AsyncMock(side_effect=lambda: events.append("benchmarks"))
    monkeypatch.setattr(module.store, "has_recovery", lambda: False)
    monkeypatch.setattr(module.store, "has_active_benchmarks", lambda: False)
    await scheduler._cycle()
    assert events == ["calibration", "benchmarks"]


async def test_manual_benchmark_does_not_consume_pending_calibration_attempt(scheduler, monkeypatch):
    scheduler.calibration = MagicMock()
    scheduler.calibration._tick = AsyncMock()
    scheduler.tick = AsyncMock()
    monkeypatch.setattr(module.store, "has_recovery", lambda: False)
    monkeypatch.setattr(module.store, "has_active_benchmarks", lambda: True)
    await scheduler._cycle()
    scheduler.calibration._tick.assert_not_awaited()


async def test_pending_calibration_prevents_next_configuration(scheduler):
    scheduler.calibration = MagicMock()
    scheduler.calibration.benchmarks_must_wait.return_value = True
    scheduler.submit = AsyncMock()
    assert await scheduler.run_schedule(31, MagicMock())
    scheduler.submit.assert_not_awaited()
    scheduler.restore.assert_awaited_once()
    assert scheduler.saved[-1][1] == "calibration_pending"


async def test_automatic_calibration_claim_is_reattached_after_restart(scheduler, monkeypatch):
    scheduler.calibration = MagicMock()
    scheduler.calibration._active_provider_ids = set()
    scheduler.calibration._tick = AsyncMock()
    scheduler.maintenance = MagicMock()
    scheduler.maintenance.reconcile = AsyncMock(return_value=[])
    scheduler.tick = AsyncMock()
    monkeypatch.setattr(module.store, "calibration_claims", lambda: [{"provider_id": 20, "automatic": True}])
    monkeypatch.setattr(module.store, "has_recovery", lambda: False)
    monkeypatch.setattr(module.store, "has_active_benchmarks", lambda: False)
    await scheduler._cycle()
    assert scheduler.calibration._active_provider_ids == {20}
    scheduler.calibration._tick.assert_awaited_once()


async def test_metal_plan_runs_all_batching_configurations(scheduler):
    snapshot = scheduler.registry.peek_runtime_snapshot.return_value
    snapshot["runtime"]["devices"] = {
        "mode": "metal",
        "nvidia_smi_available": False,
        "telemetry_available": True,
        "devices": [{"kind": "metal", "memory_total_mb": 24000}],
    }

    async def submit(*args):
        return 7, asyncio.create_task(asyncio.sleep(0, result=1))

    scheduler.submit = AsyncMock(side_effect=submit)
    assert await scheduler.run_schedule(31, MagicMock())
    assert scheduler.submit.await_count == 5
    assert scheduler.saved[-1][1] == "completed"


async def test_unknown_inventory_is_rejected_before_worker_is_drained(scheduler):
    scheduler.registry.peek_runtime_snapshot.return_value["runtime"]["devices"] = {}
    scheduler.submit = AsyncMock()
    assert await scheduler.run_schedule(31, MagicMock())
    scheduler.planner._facade.reserve_worker_for_drain.assert_not_called()
    scheduler.planner._drain_lane.assert_not_awaited()
    scheduler.submit.assert_not_awaited()


async def test_orphaned_nightly_job_is_fenced_drained_and_recovered(scheduler, rotation, monkeypatch):
    rows, claimed = rotation
    row = rows[0]
    row["recovery"] = {"provider_id": 20, "mutated": True}
    events = []
    monkeypatch.setattr(module.store, "recovery_jobs", lambda _: [701])
    monkeypatch.setattr(module.store, "has_active_benchmarks", lambda excluding=None: excluding != [701])
    monkeypatch.setattr(module.store, "fence_recovery_jobs", lambda ids: events.append(("fence", ids)))
    monkeypatch.setattr(module.store, "finish_recovery_jobs", lambda ids: events.append(("failed", ids)))
    scheduler.recovery_worker_idle = AsyncMock(side_effect=lambda _: events.append("idle") or True)
    scheduler.restore.side_effect = lambda *args: events.append("restore")
    await scheduler.tick()
    assert events == [("fence", [701]), "idle", ("failed", [701]), "restore"]
    assert scheduler.saved[-1][1] == "interrupted_recovered"
    assert scheduler.saved[-1][3] is None
    assert not claimed


@pytest.mark.parametrize("blocker", ["execution", "manual", "task", "worker_busy", "lease"])
async def test_recovery_keeps_journal_when_execution_or_cleanup_is_uncertain(scheduler, rotation, monkeypatch, blocker):
    import importlib

    main = importlib.import_module("logos.main")

    rows, _ = rotation
    rows[0]["recovery"] = {"provider_id": 20}
    monkeypatch.setattr(module.store, "recovery_jobs", lambda _: [701])
    monkeypatch.setattr(module.store, "has_active_benchmarks", lambda **_: blocker == "manual")
    finish = MagicMock()
    monkeypatch.setattr(module.store, "finish_recovery_jobs", finish)
    if blocker == "execution":
        monkeypatch.setattr(module.store, "execution_lock", lambda _: nullcontext(None))
    if blocker == "task":
        monkeypatch.setitem(main._benchmark_tasks_by_job, 701, MagicMock(done=lambda: False))
    if blocker == "lease":
        monkeypatch.setattr(module.store, "execution_lock_held", lambda *args: False)
    scheduler.recovery_worker_idle = AsyncMock(return_value=blocker != "worker_busy")
    await scheduler.tick()
    finish.assert_not_called()
    scheduler.restore.assert_not_awaited()
    scheduler.run_schedule.assert_not_awaited()
    assert not scheduler.saved


@pytest.mark.parametrize(
    "runtime,expected",
    [
        (
            {
                "lanes": [
                    {
                        "model": "model",
                        "active_requests": 0,
                        "backend_metrics": {"requests_running": 0, "queue_waiting": 0},
                    }
                ]
            },
            True,
        ),
        ({"lanes": [{"model": "model", "active_requests": 1}]}, False),
        ({"lanes": [{"model": "model", "active_requests": 0, "backend_metrics": {"queue_waiting": 1}}]}, False),
        ({"lanes": [{"model": "model"}]}, False),
        ({}, False),
    ],
)
async def test_recovery_uses_fresh_worker_request_counters(scheduler, runtime, expected):
    scheduler.registry.send_command = AsyncMock(return_value=runtime)
    assert await scheduler.recovery_worker_idle({"provider_id": 20, "lane_id": "lane", "model": "model"}) == expected
    scheduler.registry.send_command.assert_awaited_once_with(20, "get_runtime", {}, timeout_seconds=30)


def _lane(lane_id, model, active=0, **metrics):
    return {"lane_id": lane_id, "model": model, "active_requests": active, "backend_metrics": metrics}


async def test_stale_orchestrator_inflight_counter_does_not_block_recovery(scheduler):
    scheduler.planner._facade.model_inflight_requests.return_value = 3
    scheduler.registry.send_command = AsyncMock(return_value={"lanes": [_lane("lane", "model")]})
    assert await scheduler.recovery_worker_idle({"provider_id": 20, "lane_id": "lane", "model": "model"})


async def test_production_traffic_on_other_lanes_does_not_block_recovery(scheduler):
    lanes = [_lane("lane", "model"), _lane("other", "other-model", 4, requests_running=4, queue_waiting=2)]
    scheduler.registry.send_command = AsyncMock(return_value={"lanes": lanes})
    assert await scheduler.recovery_worker_idle({"provider_id": 20, "lane_id": "lane", "model": "model"})


@pytest.mark.parametrize(
    "busy",
    [
        _lane("lane", "model", 1),
        _lane("lane", "model", requests_running=1),
        # A second lane of the recovered model, e.g. after a replacement.
        _lane("lane-2", "model", 2),
    ],
)
async def test_requests_on_the_recovered_model_block_recovery(scheduler, busy):
    lanes = [busy, _lane("other", "other-model")]
    if busy["lane_id"] != "lane":
        lanes.append(_lane("lane", "model"))
    scheduler.registry.send_command = AsyncMock(return_value={"lanes": lanes})
    assert not await scheduler.recovery_worker_idle({"provider_id": 20, "lane_id": "lane", "model": "model"})


async def test_missing_recovered_lane_counts_as_idle(scheduler):
    scheduler.registry.send_command = AsyncMock(return_value={"lanes": [_lane("other", "other-model", 1)]})
    assert await scheduler.recovery_worker_idle({"provider_id": 20, "lane_id": "lane", "model": "model"})


async def test_journal_without_lane_requires_the_whole_worker_idle(scheduler):
    scheduler.registry.send_command = AsyncMock(return_value={"lanes": [_lane("other", "other-model", 1)]})
    assert not await scheduler.recovery_worker_idle({"provider_id": 20})


async def test_unhealthy_worker_blocks_recovery(scheduler):
    scheduler.registry.send_command = AsyncMock(
        return_value={"lanes": [_lane("lane", "model")], "node_health": {"healthy": False}}
    )
    assert not await scheduler.recovery_worker_idle({"provider_id": 20, "lane_id": "lane", "model": "model"})


async def test_terminal_orphan_job_still_requires_worker_cleanup_before_restore(scheduler, rotation):
    rows, _ = rotation
    rows[0]["recovery"] = {"provider_id": 20, "mutated": True}
    scheduler.registry.send_command.return_value = {"lanes": [{"model": "model", "active_requests": 1}]}
    await scheduler.tick()
    scheduler.restore.assert_not_awaited()
    scheduler.run_schedule.assert_not_awaited()
    assert not scheduler.saved


async def test_explicit_single_worker_maintenance_runs_and_restores(scheduler, monkeypatch):
    monkeypatch.setenv("LOGOS_MAINTENANCE_MAX_NODES", "1")
    scheduler.registry.active_provider_ids.return_value = [20]

    async def submit(*args):
        assert not benchmark_reservations.allows(20, "other", "new-production-request")
        return 7, asyncio.create_task(asyncio.sleep(0, result=1))

    scheduler.submit = AsyncMock(side_effect=submit)
    assert await scheduler.run_schedule(31, MagicMock())
    assert scheduler.submit.await_count == 5
    scheduler.restore.assert_awaited_once()
    assert scheduler.saved[-1][1] == "completed"
    assert benchmark_reservations.owner(20, "other") is None


def test_locked_worker_is_excluded_from_preview_without_changing_its_schedule(scheduler):
    from logos.benchmarks.nightly_overview import overview

    scheduler.planner.is_worker_locked.return_value = True
    schedule = dict(
        model_provider_id=31,
        model_id=1,
        provider_name="Worker",
        enabled=True,
        last_run_date=None,
        report=[],
        recovery=None,
    )
    result = overview([schedule], scheduler, datetime.fromisoformat("2026-10-26T12:00:00+01:00"))
    assert result["schedules"][0]["state"] == "blocked"
    assert result["schedules"][0]["reason"] == "The selected worker is locked"
    assert scheduler.saved == []


@pytest.mark.parametrize("condition", ["offline", "unhealthy", "calibrating"])
def test_single_worker_override_still_requires_healthy_idle_worker(scheduler, monkeypatch, condition):
    monkeypatch.setenv("LOGOS_MAINTENANCE_MAX_NODES", "1")
    scheduler.registry.active_provider_ids.return_value = [20]
    if condition == "offline":
        scheduler.registry.is_provider_online.return_value = False
    elif condition == "calibrating":
        scheduler.registry.is_calibrating.return_value = True
    else:
        scheduler.registry.peek_runtime_snapshot.return_value["runtime"]["node_health"] = {"healthy": False}
    with pytest.raises(RuntimeError, match="selected worker must be online and healthy"):
        scheduler.target_lane(31)


async def test_two_distinct_workers_run_concurrently_with_limit_two(scheduler, rotation, monkeypatch):
    monkeypatch.setenv("LOGOS_MAINTENANCE_MAX_NODES", "2")
    started = set()
    both_started = asyncio.Event()

    async def run(pair, connection):
        started.add(pair)
        if len(started) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=1)
        return True

    scheduler.run_schedule.side_effect = run
    await scheduler.tick()
    assert started == {31, 32}
    assert rotation[1] == {31, 32}


async def test_two_models_on_same_worker_remain_sequential(scheduler, rotation, monkeypatch):
    monkeypatch.setenv("LOGOS_MAINTENANCE_MAX_NODES", "2")
    scheduler.target_lane.side_effect = lambda pair: ({"provider_id": 20}, {}, {})
    active = set()
    order = []

    async def run(pair, connection):
        assert not active
        active.add(pair)
        await asyncio.sleep(0)
        active.remove(pair)
        order.append(pair)
        return True

    scheduler.run_schedule.side_effect = run
    await scheduler.tick()
    assert order == [31, 32]


async def test_parallel_wave_failure_waits_for_sibling_cleanup(scheduler, rotation, monkeypatch):
    monkeypatch.setenv("LOGOS_MAINTENANCE_MAX_NODES", "2")
    running = asyncio.Event()
    cleaned = []

    async def run(pair, connection):
        if pair == 31:
            await running.wait()
            raise RuntimeError("database unavailable")
        try:
            running.set()
            await asyncio.Future()
        finally:
            await asyncio.sleep(0)
            cleaned.append(pair)

    scheduler.run_schedule.side_effect = run
    with pytest.raises(ExceptionGroup):
        await scheduler.tick()
    assert cleaned == [32]


async def test_offline_calibration_keeps_claim_but_scheduler_cycle_continues(scheduler, monkeypatch, caplog):
    from logos.benchmarks.maintenance import MaintenanceCoordinator
    from logos.logosnode_registry import LogosNodeOfflineError

    claim = {"provider_id": 20, "token": "offline", "automatic": True, "confirmed": True}
    monkeypatch.setattr(module.store, "calibration_claims", lambda: [claim])
    monkeypatch.setattr(module.store, "cluster_lock", lambda: nullcontext(object()))
    monkeypatch.setattr(module.store, "has_recovery", lambda: False)
    monkeypatch.setattr(module.store, "has_active_benchmarks", lambda: False)
    release = MagicMock()
    monkeypatch.setattr(module.store, "release_calibration", release)
    scheduler.registry.send_command.side_effect = LogosNodeOfflineError("offline")
    scheduler.maintenance = MaintenanceCoordinator(scheduler.registry)
    scheduler.calibration = MagicMock()
    scheduler.calibration._tick = AsyncMock()
    scheduler.tick = AsyncMock()
    await scheduler._cycle()
    release.assert_not_called()
    assert scheduler.calibration._active_provider_ids == {20}
    scheduler.calibration._tick.assert_awaited_once()
    scheduler.tick.assert_awaited_once()
    assert "remains reserved" in caplog.text


async def test_recovery_of_crashed_parallel_wave_excludes_only_orphaned_sibling_jobs(scheduler, rotation, monkeypatch):
    rows, _ = rotation
    rows[0]["recovery"] = {"provider_id": 20, "mutated": True}
    rows[1]["recovery"] = {"provider_id": 21, "mutated": True}
    monkeypatch.setattr(module.store, "recovery_jobs", lambda pair: {31: [7], 32: [8]}[pair])
    checks = []
    monkeypatch.setattr(module.store, "has_active_benchmarks", lambda excluding: checks.append(excluding) or False)
    scheduler.recovery_worker_idle = AsyncMock(return_value=True)
    assert await scheduler.recover(rows[0], MagicMock())
    assert checks == [[7, 8]]
    scheduler.restore.assert_awaited_once_with(31, rows[0]["recovery"])


async def test_live_sibling_execution_prevents_parallel_wave_recovery(scheduler, rotation, monkeypatch):
    rows, _ = rotation
    rows[0]["recovery"] = {"provider_id": 20}
    rows[1]["recovery"] = {"provider_id": 21}
    monkeypatch.setattr(module.store, "execution_lock", lambda pair: nullcontext(None if pair == 32 else object()))
    assert not await scheduler.recover(rows[0], MagicMock())
    scheduler.restore.assert_not_awaited()


async def test_recovery_completes_although_the_orchestrator_counter_is_stale(scheduler, rotation):
    """The whole path: idle check, restore, planner preparation, journal release."""
    from types import SimpleNamespace

    from logos.capacity.capacity_planner import CapacityPlanner

    rows, _ = rotation
    original = {"max_num_seqs": 16, "max_num_batched_tokens": 4096}
    recovery = {
        "provider_id": 20,
        "model": "model",
        "lane_id": "lane",
        "vllm_config": original,
        "lane_config": {"lane_id": "lane", "model": "model", "vllm": True, "vllm_config": original},
        "mutated": True,
    }
    rows[0]["recovery"] = recovery
    idle_lane = {"lane_id": "lane", "model": "model", "active_requests": 0, "backend_metrics": {}}

    async def send_command(_pid, action, params, timeout_seconds=None):
        if action in {"get_runtime", "get_lanes"}:
            return {"lanes": [idle_lane]}
        assert action == "reconfigure_lane" and params["updates"] == {"vllm_config": original}
        return {"restarted": True, "lane_config": {"vllm_config": original}}

    scheduler.registry.send_command = AsyncMock(side_effect=send_command)
    planner = object.__new__(CapacityPlanner)
    planner._registry = scheduler.registry
    planner._facade = MagicMock()
    planner._facade.model_inflight_requests.return_value = 2  # never drops: stale
    ready = SimpleNamespace(lane_id="lane", runtime_state="running", sleep_state="awake")
    planner._pick_request_target_lane = MagicMock(return_value=ready)
    planner._drain_lane = AsyncMock(return_value=True)
    planner.is_worker_locked = MagicMock(return_value=False)
    scheduler.planner = planner
    scheduler.restore = module.NightlyScheduler.restore.__get__(scheduler)

    await asyncio.wait_for(scheduler.tick(), timeout=5)

    planner._drain_lane.assert_awaited_once()
    assert scheduler.saved[-1][1:] == ("interrupted_recovered", [], None)
    assert benchmark_reservations.owner(20, "model") is None
