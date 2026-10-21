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

    def write(self, provider_id, lane_id, revision, record):
        self.writes.append((provider_id, lane_id, revision, record))
        row = self.rows.get((provider_id, lane_id))
        if row is None or not row[2] or row[3] != revision:
            return False
        row[4] = record
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
    """Found on the e2e stack: the report after an unload still showed the lane, which was recorded and put back."""
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
    assert [(a.action, a.lane_id, a.restore) for a in _restore(planner)] == [("sleep_l1", EMBED_LANE, True)]
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
