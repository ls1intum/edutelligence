"""Locked workers, and locked lanes put back the way they were after a worker restart.

A lock on a whole worker (lane id ``*``) stops every automatic load, wake,
sleep and unload there. A locked lane, and every lane of a locked worker, is
recorded as the worker reports it, so a restart that comes back without lanes
is followed by loads with the same config, on the same GPUs.
"""

import asyncio
from unittest.mock import AsyncMock

from tests.unit.pipeline.test_correcting_scheduler import MockAzureFacade, MockLogosNodeFacade, _make_view

from logos import CapacityPlanner
from logos.capacity.demand_tracker import DemandTracker
from logos.capacity.lane_restore import WORKER_LOCK_ID, missing_lanes, observed_lanes, updated_record
from logos.pipeline.correcting_scheduler import ClassificationCorrectingScheduler
from logos.queue import PriorityQueueManager
from logos.sdi.models import CapacityPlanAction

PROVIDER = 22
MODEL = "Qwen/Qwen3.8-27B"
EMBED = "Qwen/Qwen3-Embedding-8B"
LANE = "planner-Qwen_Qwen3.8-27B"
EMBED_LANE = "planner-Qwen_Qwen3-Embedding-8B"


def _runtime_lane(lane_id, model, gpu_devices, *, sleep_state="awake", runtime_state="running", transition=None):
    return {
        "lane_id": lane_id,
        "model": model,
        "runtime_state": runtime_state,
        "sleep_state": sleep_state,
        "transition": transition,
        "lane_config": {
            "lane_id": lane_id,
            "model": model,
            "gpu_devices": gpu_devices,
            "vllm": True,
            "vllm_config": {"tensor_parallel_size": len(gpu_devices.split(",")), "max_model_len": 32768},
        },
    }


class _Registry:
    def __init__(self, lanes):
        self.lanes = lanes

    def peek_runtime_snapshot(self, provider_id):  # noqa: ARG002
        return {"runtime": {"lanes": list(self.lanes)}}

    def is_provider_online(self, provider_id):  # noqa: ARG002
        return True

    def has_received_first_status(self, provider_id):  # noqa: ARG002
        return True

    def is_calibrating(self, provider_id):  # noqa: ARG002
        return False

    def mark_lane_cold(self, provider_id, lane_id):  # noqa: ARG002
        pass

    def unmark_lane_cold(self, provider_id, lane_id):  # noqa: ARG002
        pass


class _Facade:
    def get_provider_name(self, provider_id):  # noqa: ARG002
        return "deioma"


class _Table:
    """lane_locks as the planner reads and writes it."""

    def __init__(self, rows):
        self.rows = {(row[0], row[1]): list(row) for row in rows}
        self.writes = []

    def read(self):
        return [tuple(row) for row in self.rows.values()]

    def write(self, changes):
        rows = [self.rows.get((provider_id, lane_id)) for provider_id, lane_id, _revision, _record in changes]
        if any(row is None or not row[2] or row[3] != change[2] for row, change in zip(rows, changes)):
            return False  # all or none
        for row, change in zip(rows, changes):
            self.writes.append(change)
            row[4] = change[3]
        return True


def _planner(registry, table):
    planner = CapacityPlanner(
        logosnode_facade=_Facade(),
        logosnode_registry=registry,
        demand_tracker=DemandTracker(),
        lane_lock_reader=table.read,
        lane_restore_writer=table.write,
    )
    planner._refresh_lane_locks()
    return planner


def _restore(planner):
    return asyncio.run(planner._compute_restore_actions(PROVIDER))


def _attempt(planner, actions):
    """Run planned actions through the executor, the worker answering at once."""
    planner._execute_action_core = AsyncMock(return_value=True)
    for action in actions:
        asyncio.run(planner._execute_action_with_confirmation(action))


# ── Records ────────────────────────────────────────────────────────────────


def test_only_settled_lanes_with_a_config_are_recorded():
    observed = observed_lanes(
        [
            _runtime_lane(LANE, MODEL, "0,1"),
            _runtime_lane(EMBED_LANE, EMBED, "2", transition="waking"),
            _runtime_lane("planner-broken", MODEL, "3", runtime_state="error"),
            {"lane_id": "no-config", "model": MODEL},
        ]
    )
    assert set(observed) == {LANE}
    assert observed[LANE]["lane_config"]["gpu_devices"] == "0,1"
    assert observed[LANE]["sleeping"] is False


def test_a_lane_lock_records_its_lane_and_a_worker_lock_records_every_lane():
    observed = observed_lanes([_runtime_lane(LANE, MODEL, "0,1"), _runtime_lane(EMBED_LANE, EMBED, "2")])
    assert set(updated_record(None, observed, LANE)) == {LANE}
    assert set(updated_record(None, observed, WORKER_LOCK_ID)) == {LANE, EMBED_LANE}


def test_a_record_keeps_a_lane_the_worker_no_longer_reports():
    before = updated_record(None, observed_lanes([_runtime_lane(LANE, MODEL, "0,1")]), WORKER_LOCK_ID)
    after = updated_record(before, {}, WORKER_LOCK_ID)
    assert after == before
    assert [lane_id for lane_id, _ in missing_lanes(after, [])] == [LANE]


# ── Restore after a restart ─────────────────────────────────────────────────


def test_a_locked_lane_is_recorded_and_put_back_on_the_same_gpus_after_a_restart():
    registry = _Registry([_runtime_lane(LANE, MODEL, "0,1")])
    table = _Table([(PROVIDER, LANE, True, 5, None)])
    planner = _planner(registry, table)

    assert _restore(planner) == []
    assert table.writes[-1][:3] == (PROVIDER, LANE, 5)

    registry.lanes = []  # the worker restarted and came back without lanes
    actions = _restore(planner)
    assert [(a.action, a.lane_id, a.restore) for a in actions] == [("load", LANE, True)]
    assert actions[0].params["gpu_devices"] == "0,1"
    assert actions[0].params["vllm_config"]["max_model_len"] == 32768


def test_a_record_survives_an_orchestrator_restart():
    record = updated_record(None, observed_lanes([_runtime_lane(LANE, MODEL, "0,1")]), LANE)
    planner = _planner(_Registry([]), _Table([(PROVIDER, LANE, True, 5, record)]))
    assert [a.lane_id for a in _restore(planner)] == [LANE]


def test_a_record_is_not_written_to_a_lock_taken_again_since():
    registry = _Registry([_runtime_lane(LANE, MODEL, "0,1")])
    table = _Table([(PROVIDER, LANE, True, 5, None)])
    planner = _planner(registry, table)
    table.rows[(PROVIDER, LANE)][3] = 6  # unlocked and locked again meanwhile

    _restore(planner)
    assert table.rows[(PROVIDER, LANE)][4] is None
    registry.lanes = []
    assert _restore(planner) == []


def test_an_operator_unload_is_not_undone():
    registry = _Registry([_runtime_lane(LANE, MODEL, "0,1")])
    planner = _planner(registry, _Table([(PROVIDER, LANE, True, 5, None)]))
    _restore(planner)

    asyncio.run(planner.forget_restored_lane(PROVIDER, LANE))
    registry.lanes = []
    assert _restore(planner) == []


def test_two_unloads_at_once_both_stay_unloaded():
    """Each unload rewrites the record it reads; two at once must not put the other lane back."""
    registry = _Registry([_runtime_lane(LANE, MODEL, "0,1"), _runtime_lane(EMBED_LANE, EMBED, "2")])
    planner = _planner(registry, _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, None)]))
    _restore(planner)

    async def unload_both():
        await asyncio.gather(
            planner.forget_restored_lane(PROVIDER, LANE), planner.forget_restored_lane(PROVIDER, EMBED_LANE)
        )

    asyncio.run(unload_both())
    registry.lanes = []
    assert _restore(planner) == []


def test_a_lane_still_reported_while_it_unloads_is_not_recorded_again():
    """The report right after an unload still shows the lane; it must not be recorded and put back."""
    registry = _Registry([_runtime_lane(LANE, MODEL, "0,1")])
    planner = _planner(registry, _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, None)]))
    _restore(planner)

    asyncio.run(planner.forget_restored_lane(PROVIDER, LANE))
    assert _restore(planner) == []  # the report still shows the lane being unloaded
    registry.lanes = []
    assert _restore(planner) == []


def test_an_unlocked_lane_is_not_put_back():
    registry = _Registry([_runtime_lane(LANE, MODEL, "0,1")])
    planner = _planner(registry, _Table([(PROVIDER, LANE, True, 5, None)]))
    _restore(planner)
    planner.apply_lane_lock(PROVIDER, LANE, False, 6)
    registry.lanes = []
    assert _restore(planner) == []


def test_a_locked_worker_puts_every_lane_back_and_its_sleepers_to_sleep_again():
    registry = _Registry(
        [_runtime_lane(LANE, MODEL, "0,1"), _runtime_lane(EMBED_LANE, EMBED, "2", sleep_state="sleeping")]
    )
    planner = _planner(registry, _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, None)]))
    _restore(planner)

    registry.lanes = []
    loads = _restore(planner)
    assert {(a.action, a.lane_id, a.params["gpu_devices"]) for a in loads} == {
        ("load", LANE, "0,1"),
        ("load", EMBED_LANE, "2"),
    }

    # Both are back and awake; the one that slept before goes to sleep again, once.
    registry.lanes = [_runtime_lane(LANE, MODEL, "0,1"), _runtime_lane(EMBED_LANE, EMBED, "2")]
    sleeps = _restore(planner)
    assert [(a.action, a.lane_id, a.restore) for a in sleeps] == [("sleep_l1", EMBED_LANE, True)]
    _attempt(planner, sleeps)
    assert _restore(planner) == []


# ── Worker lock ────────────────────────────────────────────────────────────


def test_a_worker_lock_is_not_a_lane_lock():
    planner = _planner(_Registry([]), _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, None)]))
    assert planner.is_worker_locked(PROVIDER)
    assert not planner.is_lane_locked(PROVIDER, LANE)
    assert not planner.is_worker_locked(PROVIDER + 1)


def test_a_locked_worker_refuses_automatic_actions_but_not_operator_or_restore_ones():
    planner = _planner(_Registry([]), _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, None)]))
    planner._execute_action_core = AsyncMock(return_value=True)

    def run(**flags):
        action = CapacityPlanAction(action="load", provider_id=PROVIDER, lane_id=LANE, model_name=MODEL, **flags)
        return asyncio.run(planner._execute_action_with_confirmation(action))

    assert run() is False
    planner._execute_action_core.assert_not_awaited()
    assert run(operator_initiated=True) is True
    assert run(restore=True) is True


def test_a_benchmark_is_refused_on_a_locked_worker():
    planner = _planner(_Registry([]), _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, None)]))
    try:
        asyncio.run(planner.prepare_benchmark_lane(PROVIDER, MODEL))
    except RuntimeError as exc:
        assert "locked" in str(exc)
    else:
        raise AssertionError("expected the benchmark to be refused")


def test_requests_reach_a_locked_worker_only_through_an_awake_lane():
    worker_a, worker_b = 10, 11
    deployments = [
        {"model_id": 1, "provider_id": worker_a, "type": "logosnode"},
        {"model_id": 1, "provider_id": worker_b, "type": "logosnode"},
    ]
    logosnode = MockLogosNodeFacade()
    logosnode.set_view(
        1, worker_a, _make_view(model_id=1, provider_id=worker_a, best_lane_state="sleeping", is_loaded=False)
    )
    logosnode.set_view(1, worker_b, _make_view(model_id=1, provider_id=worker_b))
    scheduler = ClassificationCorrectingScheduler(
        queue_manager=PriorityQueueManager(), logosnode_facade=logosnode, azure_facade=MockAzureFacade()
    )

    def providers():
        return {p for _m, p, *_ in scheduler._compute_candidate_scores([(1, 10.0, 1)], deployments, {})}

    assert providers() == {worker_a, worker_b}
    scheduler.set_worker_lock_check(lambda provider_id: provider_id in {worker_a, worker_b})
    # The sleeping lane on the locked worker would never be woken; the awake one still serves.
    assert providers() == {worker_b}


# ── Review follow-ups ──────────────────────────────────────────────────────


def test_a_relock_that_overtakes_its_unlock_does_not_keep_the_old_record():
    registry = _Registry([_runtime_lane(LANE, MODEL, "0,1")])
    planner = _planner(registry, _Table([(PROVIDER, LANE, True, 5, None)]))
    _restore(planner)
    planner.apply_lane_lock(PROVIDER, LANE, True, 7, record=None)  # relock, as committed: no record
    planner.apply_lane_lock(PROVIDER, LANE, False, 6)  # the unlock arrives late and is ignored
    planner._lane_restore_writer = None  # the table no longer holds revision 5
    registry.lanes = []
    assert _restore(planner) == []


def _entry(lane_id, model, gpus, sleeping):
    return {
        "lane_config": {"lane_id": lane_id, "model": model, "gpu_devices": gpus, "vllm": True},
        "sleeping": sleeping,
    }


def test_a_lane_that_slept_is_put_back_before_an_awake_lane_on_its_gpu():
    record = {LANE: _entry(LANE, MODEL, "0", False), EMBED_LANE: _entry(EMBED_LANE, EMBED, "0", True)}
    registry = _Registry([])
    planner = _planner(registry, _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, record)]))

    assert [(a.action, a.lane_id) for a in _restore(planner)] == [("load", EMBED_LANE)]
    registry.lanes = [_runtime_lane(EMBED_LANE, EMBED, "0")]  # back, still awake
    sleeps = _restore(planner)
    assert [(a.action, a.lane_id) for a in sleeps] == [("sleep_l1", EMBED_LANE)]
    _attempt(planner, sleeps)
    registry.lanes = [_runtime_lane(EMBED_LANE, EMBED, "0", sleep_state="sleeping")]
    assert [(a.action, a.lane_id) for a in _restore(planner)] == [("load", LANE)]


def test_an_awake_lane_on_other_gpus_does_not_wait_for_a_sleeper():
    record = {LANE: _entry(LANE, MODEL, "1", False), EMBED_LANE: _entry(EMBED_LANE, EMBED, "0", True)}
    planner = _planner(_Registry([]), _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, record)]))
    assert {a.lane_id for a in _restore(planner)} == {LANE, EMBED_LANE}


def test_a_worker_locked_while_a_lane_drains_stops_the_automatic_sleep():
    planner = _planner(_Registry([]), _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, None)]))

    def locked_since(**flags):
        action = CapacityPlanAction(action="sleep_l1", provider_id=PROVIDER, lane_id=LANE, model_name=MODEL, **flags)
        return asyncio.run(planner._locked_since_planning(action))

    assert locked_since() is True
    assert locked_since(restore=True) is False
    assert locked_since(operator_initiated=True) is False


def test_a_locked_worker_does_not_hold_nightly_benchmarks_back_for_its_calibration():
    from unittest.mock import MagicMock

    from logos.capacity.calibration_orchestrator import CalibrationOrchestrator

    registry, facade = MagicMock(), MagicMock()
    facade.provider_ids.return_value = [PROVIDER]
    service = CalibrationOrchestrator(registry, facade, worker_locked=lambda pid: pid == PROVIDER)
    service._is_in_window = lambda: True
    service._was_in_window = True
    service._provider_is_unhealthy = lambda _: False
    service._provider_has_uncalibrated_models = lambda _: True
    assert not service.benchmarks_must_wait()


def test_an_unload_is_refused_when_its_lane_cannot_be_forgotten():
    import pytest

    from logos.capacity.capacity_planner import RestoreRecordError

    table = _Table([(PROVIDER, LANE, True, 5, None)])
    planner = _planner(_Registry([_runtime_lane(LANE, MODEL, "0,1")]), table)
    _restore(planner)

    def broken(*args):
        raise RuntimeError("database down")

    planner._lane_restore_writer = broken
    with pytest.raises(RestoreRecordError):
        asyncio.run(planner.forget_restored_lane(PROVIDER, LANE))
    assert "unloading" not in planner._lock_cache().peek()[(PROVIDER, LANE)][2][LANE]


def test_a_restored_sleeper_is_put_to_sleep_only_once_it_serves():
    record = {EMBED_LANE: _entry(EMBED_LANE, EMBED, "0", True)}
    registry = _Registry([])
    planner = _planner(registry, _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, record)]))
    _restore(planner)
    registry.lanes = [_runtime_lane(EMBED_LANE, EMBED, "0", runtime_state="starting")]
    assert _restore(planner) == []
    registry.lanes = [_runtime_lane(EMBED_LANE, EMBED, "0")]
    assert [(a.action, a.lane_id) for a in _restore(planner)] == [("sleep_l1", EMBED_LANE)]


def test_a_malformed_record_does_not_break_the_cycle():
    record = {"broken": {"sleeping": True}, "worse": "text", LANE: _entry(LANE, MODEL, "0", False)}
    planner = _planner(_Registry([]), _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, record)]))
    assert [a.lane_id for a in _restore(planner)] == [LANE]


def test_nightly_recovery_may_prepare_its_lane_on_a_locked_worker():
    from logos.capacity.capacity_planner import MAINTENANCE_RECOVERY

    planner = _planner(_Registry([]), _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, None)]))
    token = MAINTENANCE_RECOVERY.set(True)
    try:
        planner._refuse_benchmark_on_locked_worker(PROVIDER)
    finally:
        MAINTENANCE_RECOVERY.reset(token)


def test_a_re_sleep_survives_an_orchestrator_restart():
    record = {EMBED_LANE: _entry(EMBED_LANE, EMBED, "0", True)}
    registry = _Registry([])
    table = _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, record)])
    _restore(_planner(registry, table))  # plans the load and marks the re-sleep in the table
    assert table.rows[(PROVIDER, WORKER_LOCK_ID)][4][EMBED_LANE].get("resleep") is True

    restarted = _planner(registry, table)  # a new orchestrator reads the table
    registry.lanes = [_runtime_lane(EMBED_LANE, EMBED, "0")]
    sleeps = _restore(restarted)
    assert [(a.action, a.lane_id) for a in sleeps] == [("sleep_l1", EMBED_LANE)]
    _attempt(restarted, sleeps)
    assert "resleep" not in table.rows[(PROVIDER, WORKER_LOCK_ID)][4][EMBED_LANE]


def test_an_unload_waiting_on_the_worker_stays_forgotten_until_the_lane_is_gone():
    registry = _Registry([_runtime_lane(LANE, MODEL, "0,1")])
    planner = _planner(registry, _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, None)]))
    _restore(planner)
    asyncio.run(planner.forget_restored_lane(PROVIDER, LANE))
    _age_unload(planner, 600)  # ten minutes behind other work
    assert _restore(planner) == []
    registry.lanes = []
    assert _restore(planner) == []


def test_an_unload_queued_for_hours_is_still_not_undone():
    registry = _Registry([_runtime_lane(LANE, MODEL, "0,1")])
    planner = _planner(registry, _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, None)]))
    _restore(planner)
    asyncio.run(planner.forget_restored_lane(PROVIDER, LANE))
    _age_unload(planner, 6 * 3600)
    assert _restore(planner) == []
    registry.lanes = []
    assert _restore(planner) == []


def test_a_new_lane_lock_marks_its_unload_before_it_has_recorded_the_lane():
    registry = _Registry([_runtime_lane(LANE, MODEL, "0,1")])
    planner = _planner(registry, _Table([(PROVIDER, LANE, True, 5, None)]))
    asyncio.run(planner.forget_restored_lane(PROVIDER, LANE))  # no cycle has recorded it yet
    assert _restore(planner) == []
    registry.lanes = []
    assert _restore(planner) == []


def test_a_re_sleep_that_never_went_out_stays_due():
    record = {EMBED_LANE: {**_entry(EMBED_LANE, EMBED, "0", True), "resleep": True}}
    registry = _Registry([_runtime_lane(EMBED_LANE, EMBED, "0")])
    table = _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, record)])
    planner = _planner(registry, table)
    sleeps = _restore(planner)
    planner._execute_action_core = AsyncMock(return_value=False)  # the drain timed out, nothing was sent
    asyncio.run(planner._execute_action_with_confirmation(sleeps[0]))
    assert table.rows[(PROVIDER, WORKER_LOCK_ID)][4][EMBED_LANE].get("resleep") is True
    assert [a.action for a in _restore(planner)] == ["sleep_l1"]


def test_an_operator_stop_that_never_went_out_records_the_lane_again():
    registry = _Registry([_runtime_lane(LANE, MODEL, "0,1")])
    planner = _planner(registry, _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, None)]))
    _restore(planner)
    planner._execute_action_core = AsyncMock(return_value=False)
    stop = CapacityPlanAction(
        action="stop", provider_id=PROVIDER, lane_id=LANE, model_name=MODEL, operator_initiated=True
    )
    asyncio.run(planner._execute_action_with_confirmation(stop))
    _restore(planner)
    registry.lanes = []
    assert [a.lane_id for a in _restore(planner)] == [LANE]


def test_a_refused_unload_records_the_lane_again():
    registry = _Registry([_runtime_lane(LANE, MODEL, "0,1")])
    planner = _planner(registry, _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, None)]))
    _restore(planner)
    attempt = asyncio.run(planner.forget_restored_lane(PROVIDER, LANE))
    asyncio.run(planner.unload_refused(PROVIDER, LANE, attempt))
    _restore(planner)
    registry.lanes = []
    assert [a.lane_id for a in _restore(planner)] == [LANE]


def _age_unload(planner, seconds):
    for (pid, _lock_id), (_locked, _revision, record) in planner._lock_cache().peek().items():
        if pid == PROVIDER and record and "unloading" in record.get(LANE, {}):
            record[LANE]["unloading"] = [since - seconds for since in record[LANE]["unloading"]]


def test_an_unload_mark_survives_an_orchestrator_restart():
    registry = _Registry([_runtime_lane(LANE, MODEL, "0,1")])
    table = _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, None)])
    planner = _planner(registry, table)
    _restore(planner)
    asyncio.run(planner.forget_restored_lane(PROVIDER, LANE))

    restarted = _planner(registry, table)  # the unload still waits on the worker
    assert _restore(restarted) == []
    registry.lanes = []
    assert _restore(restarted) == []
    assert LANE not in table.rows[(PROVIDER, WORKER_LOCK_ID)][4]


def test_a_planned_re_sleep_keeps_its_mark_until_it_is_attempted():
    record = {EMBED_LANE: _entry(EMBED_LANE, EMBED, "0", True)}
    registry = _Registry([])
    table = _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, record)])
    planner = _planner(registry, table)
    _restore(planner)
    registry.lanes = [_runtime_lane(EMBED_LANE, EMBED, "0")]
    sleeps = _restore(planner)
    assert [(a.action, a.lane_id) for a in sleeps] == [("sleep_l1", EMBED_LANE)]
    assert table.rows[(PROVIDER, WORKER_LOCK_ID)][4][EMBED_LANE].get("resleep") is True  # planned, not yet attempted

    _attempt(planner, sleeps)
    assert "resleep" not in table.rows[(PROVIDER, WORKER_LOCK_ID)][4][EMBED_LANE]


def test_a_sleeper_is_not_loaded_while_its_re_sleep_mark_cannot_be_written():
    record = {EMBED_LANE: _entry(EMBED_LANE, EMBED, "0", True)}
    table = _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, record)])
    planner = _planner(_Registry([]), table)

    def broken(*args):
        raise RuntimeError("database down")

    planner._lane_restore_writer = broken
    assert _restore(planner) == []
    planner._lane_restore_writer = table.write
    assert [a.lane_id for a in _restore(planner)] == [EMBED_LANE]


def test_a_refused_unload_of_a_lane_never_recorded_drops_its_mark():
    registry = _Registry([_runtime_lane(LANE, MODEL, "0,1")])
    table = _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, None)])
    planner = _planner(registry, table)
    attempt = asyncio.run(planner.forget_restored_lane(PROVIDER, LANE))  # marked before any observation
    asyncio.run(planner.unload_refused(PROVIDER, LANE, attempt))
    assert LANE not in (table.rows[(PROVIDER, WORKER_LOCK_ID)][4] or {})
    _restore(planner)  # recorded again
    registry.lanes = []
    assert [a.lane_id for a in _restore(planner)] == [LANE]


def test_a_re_sleep_of_an_earlier_lock_does_not_carry_over_to_a_new_one():
    record = {EMBED_LANE: _entry(EMBED_LANE, EMBED, "0", True)}
    registry = _Registry([])
    table = _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, record)])
    planner = _planner(registry, table)
    _restore(planner)  # the sleeper's load is planned and its re-sleep marked
    planner.apply_lane_lock(PROVIDER, WORKER_LOCK_ID, False, 10)
    table.rows[(PROVIDER, WORKER_LOCK_ID)] = [PROVIDER, WORKER_LOCK_ID, True, 11, None]
    planner.apply_lane_lock(PROVIDER, WORKER_LOCK_ID, True, 11, record=None)  # a new lock
    registry.lanes = [_runtime_lane(EMBED_LANE, EMBED, "0")]
    assert _restore(planner) == []


def _answered(message):
    async def build():
        future = asyncio.get_running_loop().create_future()
        future.set_result(message)
        return future

    return asyncio.run(build())


def test_a_refused_or_rolled_back_stop_counts_as_refused_and_a_silent_one_does_not():
    refused = CapacityPlanner._answer_refused
    assert refused(_answered({"success": False, "error": "busy"}))
    assert refused(_answered({"success": True, "result": {"rolled_back": True}}))
    assert not refused(_answered({"success": True, "result": {}}))
    assert not refused(None)


def test_an_operator_stop_the_worker_refused_records_the_lane_again():
    registry = _Registry([_runtime_lane(LANE, MODEL, "0,1")])
    planner = _planner(registry, _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, None)]))
    _restore(planner)
    stop = CapacityPlanAction(
        action="stop", provider_id=PROVIDER, lane_id=LANE, model_name=MODEL, operator_initiated=True
    )

    async def refused_stop(action, **kwargs):
        future = asyncio.get_running_loop().create_future()
        future.set_result({"success": False, "error": "refused"})
        planner._lifecycle_commands_sent[(PROVIDER, LANE)] = future
        return False

    planner._execute_action_core = refused_stop
    asyncio.run(planner._execute_action_with_confirmation(stop))
    _restore(planner)
    registry.lanes = []
    assert [a.lane_id for a in _restore(planner)] == [LANE]


def test_a_payload_refusal_counts_as_refused():
    assert CapacityPlanner._answer_refused(_answered({"success": True, "result": {"ok": False, "calibrating": True}}))


def test_a_refusal_that_answers_after_the_timeout_records_the_lane_again():
    registry = _Registry([_runtime_lane(LANE, MODEL, "0,1")])
    planner = _planner(registry, _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, None)]))
    _restore(planner)

    async def late_refusal():
        attempt = await planner.forget_restored_lane(PROVIDER, LANE)
        answer = asyncio.get_running_loop().create_future()
        await planner.settle_unload(PROVIDER, LANE, attempt, answer)  # the caller stopped waiting
        await asyncio.sleep(0)
        assert _unloading_marked(planner)
        answer.set_result({"success": True, "result": {"rolled_back": True}})
        await asyncio.gather(*planner._unload_settlers)
        assert not _unloading_marked(planner)

    asyncio.run(late_refusal())


def _unloading_marked(planner):
    record = planner._lock_cache().peek()[(PROVIDER, WORKER_LOCK_ID)][2] or {}
    return "unloading" in record.get(LANE, {})


def test_a_late_refusal_of_an_earlier_unload_keeps_a_retry_suppressed():
    registry = _Registry([_runtime_lane(LANE, MODEL, "0,1")])
    planner = _planner(registry, _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, None)]))
    _restore(planner)

    async def retried():
        first = await planner.forget_restored_lane(PROVIDER, LANE)
        await asyncio.sleep(0.01)
        await planner.forget_restored_lane(PROVIDER, LANE)  # the operator tries again
        await planner.unload_refused(PROVIDER, LANE, first)  # the first one's late refusal

    asyncio.run(retried())
    assert _unloading_marked(planner)


def test_a_refused_retry_keeps_an_earlier_unload_still_on_its_way():
    registry = _Registry([_runtime_lane(LANE, MODEL, "0,1")])
    planner = _planner(registry, _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, None)]))
    _restore(planner)

    async def retried():
        await planner.forget_restored_lane(PROVIDER, LANE)  # A: timed out, still queued on the worker
        await asyncio.sleep(0.01)
        retry = await planner.forget_restored_lane(PROVIDER, LANE)  # B: never went out
        await planner.unload_refused(PROVIDER, LANE, retry)

    asyncio.run(retried())
    assert _unloading_marked(planner)
    registry.lanes = []  # A unloads it in the end
    assert _restore(planner) == []


def test_a_planned_restore_is_dropped_when_its_lock_changed_before_dispatch():
    record = {EMBED_LANE: _entry(EMBED_LANE, EMBED, "0", True)}
    registry = _Registry([_runtime_lane(EMBED_LANE, EMBED, "0")])
    table = _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, {EMBED_LANE: {**record[EMBED_LANE], "resleep": True}})])
    planner = _planner(registry, table)
    sleeps = _restore(planner)
    assert [a.action for a in sleeps] == ["sleep_l1"]
    planner.apply_lane_lock(PROVIDER, WORKER_LOCK_ID, False, 10)
    planner.apply_lane_lock(PROVIDER, WORKER_LOCK_ID, True, 11, record=None)  # unlocked and locked again
    planner._execute_action_core = AsyncMock(return_value=True)
    assert asyncio.run(planner._execute_action_with_confirmation(sleeps[0])) is False
    planner._execute_action_core.assert_not_awaited()


def test_an_unload_marked_in_two_locks_is_written_all_or_none():
    registry = _Registry([_runtime_lane(LANE, MODEL, "0,1")])
    table = _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, None), (PROVIDER, LANE, True, 5, None)])
    planner = _planner(registry, table)
    _restore(planner)
    table.rows[(PROVIDER, LANE)][3] = 6  # the lane lock changed meanwhile
    import pytest

    from logos.capacity.capacity_planner import RestoreRecordError

    with pytest.raises(RestoreRecordError):
        asyncio.run(planner.forget_restored_lane(PROVIDER, LANE))
    assert "unloading" not in (table.rows[(PROVIDER, WORKER_LOCK_ID)][4] or {}).get(LANE, {})


def test_a_queued_restore_load_is_dropped_when_the_operator_unloads_the_lane_first():
    record = updated_record(None, observed_lanes([_runtime_lane(LANE, MODEL, "0,1")]), LANE)
    planner = _planner(_Registry([]), _Table([(PROVIDER, LANE, True, 5, record)]))
    loads = _restore(planner)
    assert [a.lane_id for a in loads] == [LANE]
    asyncio.run(planner.forget_restored_lane(PROVIDER, LANE))
    planner._execute_action_core = AsyncMock(return_value=True)
    assert asyncio.run(planner._execute_action_with_confirmation(loads[0])) is False
    planner._execute_action_core.assert_not_awaited()


def test_an_operator_stop_cancelled_before_it_was_sent_records_the_lane_again():
    registry = _Registry([_runtime_lane(LANE, MODEL, "0,1")])
    planner = _planner(registry, _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, None)]))
    _restore(planner)
    stop = CapacityPlanAction(
        action="stop", provider_id=PROVIDER, lane_id=LANE, model_name=MODEL, operator_initiated=True
    )

    async def drain_forever(action, **kwargs):
        await asyncio.Event().wait()

    planner._execute_action_core = drain_forever

    async def cancelled():
        task = asyncio.create_task(planner._execute_action_with_confirmation(stop))
        for _ in range(20):
            await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(cancelled())
    assert not _unloading_marked(planner)


def test_an_unload_cancelled_while_its_mark_is_written_leaves_no_mark():
    import threading

    registry = _Registry([_runtime_lane(LANE, MODEL, "0,1")])
    table = _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, None)])
    planner = _planner(registry, table)
    _restore(planner)
    writing, release = threading.Event(), threading.Event()

    def slow_write(changes):
        writing.set()
        release.wait(2)
        return table.write(changes)

    async def cancelled():
        planner._lane_restore_writer = slow_write
        task = asyncio.create_task(planner.forget_restored_lane(PROVIDER, LANE))
        await asyncio.to_thread(writing.wait, 2)
        task.cancel()
        planner._lane_restore_writer = table.write
        release.set()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(cancelled())
    assert not _unloading_marked(planner)
    assert "unloading" not in (table.rows[(PROVIDER, WORKER_LOCK_ID)][4] or {}).get(LANE, {})


def test_a_refusal_whose_write_failed_is_retried_until_it_lands():
    registry = _Registry([_runtime_lane(LANE, MODEL, "0,1")])
    table = _Table([(PROVIDER, WORKER_LOCK_ID, True, 9, None)])
    planner = _planner(registry, table)
    _restore(planner)
    attempt = asyncio.run(planner.forget_restored_lane(PROVIDER, LANE))

    def broken(changes):
        raise RuntimeError("database down")

    planner._lane_restore_writer = broken
    asyncio.run(planner.unload_refused(PROVIDER, LANE, attempt))
    assert _unloading_marked(planner)
    planner._lane_restore_writer = table.write  # the database is back
    _restore(planner)
    assert not _unloading_marked(planner)
    registry.lanes = []
    assert [a.lane_id for a in _restore(planner)] == [LANE]
