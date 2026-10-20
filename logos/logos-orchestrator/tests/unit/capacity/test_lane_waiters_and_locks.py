"""Requests waiting for a lane and operator lane locks.

A request can hold a reservation for a model on a worker while the lane it was
meant for goes to sleep. It is then not in the scheduler queue, so the planner
used to see no demand and left the lane asleep until unrelated traffic arrived.
These tests cover the waiter registry that turns such a request into queued
demand, the guard that keeps the idle pass from sleeping a lane while reserved
requests have no other lane, and the operator lock that keeps a lane warm.
"""

import asyncio
import time
from types import SimpleNamespace

from logos import CapacityPlanner, LaneSchedulerSignals
from logos.capacity.demand_tracker import DemandTracker
from logos.sdi.models import CapacityPlanAction

MODEL = "intfloat/multilingual-e5-large"
OTHER_MODEL = "Qwen/Qwen3.6-35B-A3B"
LANE = "planner-intfloat_multilingual-e5-large"
SECOND_LANE = "planner-intfloat_multilingual-e5-large-2"
OTHER_LANE = "planner-Qwen_Qwen3.6-35B"
PROVIDER = 7


def _signal(lane_id, model, *, runtime_state="loaded", sleep_state="awake", active=0, queue=0.0):
    return LaneSchedulerSignals(
        lane_id=lane_id,
        model_name=model,
        runtime_state=runtime_state,
        sleep_state=sleep_state,
        active_requests=active,
        queue_waiting=queue,
        requests_running=float(active),
        gpu_cache_usage_percent=None,
        ttft_p95_seconds=0.0,
        e2e_latency_p50_seconds=0.0,
        effective_vram_mb=20_000.0,
        num_parallel=1,
        gpu_devices="0",
    )


class _StubRegistry:
    def peek_runtime_snapshot(self, provider_id):  # noqa: ARG002
        return None

    def is_provider_online(self, provider_id):  # noqa: ARG002
        return True


class _Facade:
    def __init__(self, lanes=None, inflight=0):
        self.lanes = lanes or []
        self.inflight = inflight

    def get_provider_name(self, provider_id):  # noqa: ARG002
        return "worker"

    def get_model_last_activity(self, provider_id, model_name):  # noqa: ARG002
        return None

    def get_scheduler_queue_depth_by_model_name(self, model_name, provider_id):  # noqa: ARG002
        return 0

    def get_inflight_request_count_by_model_name(self, model_name, provider_id):  # noqa: ARG002
        return self.inflight if model_name == MODEL else 0

    def get_all_provider_lane_signals(self, provider_id):  # noqa: ARG002
        return list(self.lanes)


def _planner(facade, lock_reader=None):
    return CapacityPlanner(
        logosnode_facade=facade,
        logosnode_registry=_StubRegistry(),
        demand_tracker=DemandTracker(),
        lane_lock_reader=lock_reader,
    )


def _long_idle(planner, *lane_ids):
    for lane_id in lane_ids:
        planner._lane_idle_since[planner._lane_key(PROVIDER, lane_id)] = time.time() - (planner.IDLE_SLEEP_L1 + 60)


def _sleeps(actions):
    return {a.lane_id for a in actions if a.action in ("sleep_l1", "sleep_l2")}


# ---------------------------------------------------------------------------
# Idle timer
# ---------------------------------------------------------------------------


def test_idle_sleep_waits_thirty_minutes_by_default(monkeypatch):
    monkeypatch.delenv("LOGOS_IDLE_SLEEP_L1_S", raising=False)
    planner = _planner(_Facade())
    assert planner.IDLE_SLEEP_L1 == 1800


def test_idle_sleep_is_still_configurable(monkeypatch):
    monkeypatch.setenv("LOGOS_IDLE_SLEEP_L1_S", "600")
    planner = _planner(_Facade())
    assert planner.IDLE_SLEEP_L1 == 600


def test_a_lane_idle_for_five_minutes_stays_awake():
    lanes = [_signal(LANE, MODEL), _signal(OTHER_LANE, OTHER_MODEL)]
    planner = _planner(_Facade(lanes))
    for lane in lanes:
        planner._lane_idle_since[planner._lane_key(PROVIDER, lane.lane_id)] = time.time() - 300
    assert _sleeps(planner._compute_idle_actions(PROVIDER, lanes)) == set()


# ---------------------------------------------------------------------------
# Lane waiters
# ---------------------------------------------------------------------------


def test_a_waiting_request_counts_as_queued_demand():
    lanes = [_signal(LANE, MODEL, runtime_state="sleeping", sleep_state="sleeping")]
    planner = _planner(_Facade(lanes))
    assert planner._get_queue_depth_for_model(PROVIDER, MODEL, lanes) == 0

    planner.register_lane_waiter("req-1", PROVIDER, MODEL)
    planner.register_lane_waiter("req-2", PROVIDER, MODEL)

    # The wake gate bypasses its demand floor on queued demand, so the
    # sleeping lane is woken for these requests instead of waiting for
    # unrelated traffic.
    assert planner._get_queue_depth_for_model(PROVIDER, MODEL, lanes) == 2
    assert planner._get_queue_depth_for_model(PROVIDER + 1, MODEL, lanes) == 0

    planner.clear_lane_waiter("req-1")
    planner.clear_lane_waiter("req-2")
    assert planner._get_queue_depth_for_model(PROVIDER, MODEL, lanes) == 0


def test_registering_a_waiter_wakes_the_cycle():
    planner = _planner(_Facade())
    planner._tick_event = asyncio.Event()
    planner.register_lane_waiter("req-1", PROVIDER, MODEL)
    assert planner._tick_event.is_set()


def test_an_expired_waiter_is_dropped():
    planner = _planner(_Facade())
    planner.register_lane_waiter("req-1", PROVIDER, MODEL)
    rid_entry = planner._lane_waiters["req-1"]
    planner._lane_waiters["req-1"] = (rid_entry[0], rid_entry[1], time.time() - planner.LANE_WAITER_TTL_SECONDS - 1)
    assert planner._lane_waiter_count(PROVIDER, MODEL) == 0
    assert "req-1" not in planner._lane_waiters


def test_a_lane_with_a_waiting_request_is_not_idle_slept():
    lanes = [_signal(LANE, MODEL), _signal(OTHER_LANE, OTHER_MODEL)]
    planner = _planner(_Facade(lanes))
    _long_idle(planner, LANE, OTHER_LANE)
    planner.register_lane_waiter("req-1", PROVIDER, MODEL)

    planner._update_idle_tracking(PROVIDER, lanes)
    actions = planner._compute_idle_actions(PROVIDER, lanes)

    assert LANE not in _sleeps(actions)
    assert OTHER_LANE in _sleeps(actions)


def test_reserved_requests_keep_the_only_lane_of_their_model_awake():
    """A request the scheduler reserved but that has not reached the worker yet
    shows in no lane counter; sleeping the only lane would strand it."""
    lanes = [_signal(LANE, MODEL), _signal(OTHER_LANE, OTHER_MODEL)]
    planner = _planner(_Facade(lanes, inflight=1))
    _long_idle(planner, LANE, OTHER_LANE)

    actions = planner._compute_idle_actions(PROVIDER, lanes)

    assert LANE not in _sleeps(actions)
    assert OTHER_LANE in _sleeps(actions)


def test_reserved_requests_do_not_block_a_lane_with_an_awake_sibling():
    lanes = [_signal(LANE, MODEL), _signal(SECOND_LANE, MODEL), _signal(OTHER_LANE, OTHER_MODEL)]
    planner = _planner(_Facade(lanes, inflight=1))
    assert planner._model_inflight_without_other_lane(PROVIDER, MODEL, LANE) is False


def test_reserved_requests_block_when_the_sibling_is_asleep():
    lanes = [
        _signal(LANE, MODEL),
        _signal(SECOND_LANE, MODEL, runtime_state="sleeping", sleep_state="sleeping"),
    ]
    planner = _planner(_Facade(lanes, inflight=1))
    assert planner._model_inflight_without_other_lane(PROVIDER, MODEL, LANE) is True


# ---------------------------------------------------------------------------
# Lane locks
# ---------------------------------------------------------------------------


def test_locks_are_read_from_the_reader():
    planner = _planner(_Facade(), lock_reader=lambda: [(PROVIDER, LANE)])
    planner._refresh_lane_locks()
    assert planner.is_lane_locked(PROVIDER, LANE)
    assert not planner.is_lane_locked(PROVIDER, OTHER_LANE)


def test_a_failed_lock_read_keeps_the_previous_locks():
    reads = iter([[(PROVIDER, LANE)], None])
    planner = _planner(_Facade(), lock_reader=lambda: next(reads))
    planner._refresh_lane_locks()
    planner._refresh_lane_locks()
    assert planner.is_lane_locked(PROVIDER, LANE)


def test_a_raising_lock_reader_keeps_the_previous_locks():
    calls = {"n": 0}

    def reader():
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("database down")
        return [(PROVIDER, LANE)]

    planner = _planner(_Facade(), lock_reader=reader)
    planner._refresh_lane_locks()
    planner._refresh_lane_locks()
    assert planner.is_lane_locked(PROVIDER, LANE)


def test_without_a_reader_no_lane_is_locked():
    planner = _planner(_Facade())
    planner._refresh_lane_locks()
    assert not planner.is_lane_locked(PROVIDER, LANE)


def test_a_locked_lane_is_never_idle_slept():
    lanes = [_signal(LANE, MODEL), _signal(OTHER_LANE, OTHER_MODEL)]
    planner = _planner(_Facade(lanes), lock_reader=lambda: [(PROVIDER, LANE)])
    planner._refresh_lane_locks()
    _long_idle(planner, LANE, OTHER_LANE)

    actions = planner._compute_idle_actions(PROVIDER, lanes)

    assert LANE not in _sleeps(actions)
    assert OTHER_LANE in _sleeps(actions)


def test_a_locked_lane_found_asleep_is_woken():
    lanes = [
        _signal(LANE, MODEL, runtime_state="sleeping", sleep_state="sleeping"),
        _signal(OTHER_LANE, OTHER_MODEL, runtime_state="sleeping", sleep_state="sleeping"),
    ]
    planner = _planner(_Facade(lanes), lock_reader=lambda: [(PROVIDER, LANE)])
    planner._refresh_lane_locks()

    planned: set[str] = set()
    actions = planner._compute_lock_wake_actions(PROVIDER, lanes, planned)

    assert [(a.action, a.lane_id) for a in actions] == [("wake", LANE)]
    assert MODEL in planned


def test_an_awake_locked_lane_needs_no_wake():
    lanes = [_signal(LANE, MODEL)]
    planner = _planner(_Facade(lanes), lock_reader=lambda: [(PROVIDER, LANE)])
    planner._refresh_lane_locks()
    assert planner._compute_lock_wake_actions(PROVIDER, lanes) == []


def test_a_locked_lane_is_never_an_eviction_victim():
    lanes = [_signal(LANE, MODEL), _signal(OTHER_LANE, OTHER_MODEL)]
    planner = _planner(_Facade(lanes), lock_reader=lambda: [(PROVIDER, LANE)])
    planner._refresh_lane_locks()

    eviction = planner._find_eviction_set(
        PROVIDER,
        frozenset({0}),
        {0: 10_000.0},
        lanes,
        {},
        target_model_name="some/other-model",
    )

    victims = {lane.lane_id for lane, _, _ in eviction}
    assert victims == {OTHER_LANE}


def test_eviction_cannot_free_memory_when_every_lane_is_locked():
    lanes = [_signal(LANE, MODEL), _signal(OTHER_LANE, OTHER_MODEL)]
    planner = _planner(_Facade(lanes), lock_reader=lambda: [(PROVIDER, LANE), (PROVIDER, OTHER_LANE)])
    planner._refresh_lane_locks()

    eviction = planner._find_eviction_set(
        PROVIDER,
        frozenset({0}),
        {0: 10_000.0},
        lanes,
        {},
        target_model_name="some/other-model",
    )

    assert eviction is None


def test_the_executor_refuses_to_sleep_a_locked_lane():
    planner = _planner(_Facade(), lock_reader=lambda: [(PROVIDER, LANE)])
    planner._refresh_lane_locks()
    action = CapacityPlanAction(action="sleep_l1", provider_id=PROVIDER, lane_id=LANE, model_name=MODEL)

    assert asyncio.run(planner._execute_action_with_confirmation(action)) is False


def test_the_executor_still_runs_an_operator_sleep_of_a_locked_lane():
    planner = _planner(_Facade(), lock_reader=lambda: [(PROVIDER, LANE)])
    planner._refresh_lane_locks()
    ran = []

    async def core(action, timeout_seconds=60.0, deadline=None):  # noqa: ARG001
        ran.append(action.action)
        return True

    planner._execute_action_core = core
    planner._mark_lane_cold = lambda *a: None
    planner._unmark_lane_cold = lambda *a: None
    action = CapacityPlanAction(
        action="sleep_l1",
        provider_id=PROVIDER,
        lane_id=LANE,
        model_name=MODEL,
        operator_initiated=True,
    )

    assert asyncio.run(planner._execute_action_with_confirmation(action)) is True
    assert ran == ["sleep_l1"]


def test_an_operator_sleep_escalated_to_a_stop_stays_an_operator_action():
    planner = _planner(_Facade(), lock_reader=lambda: [(PROVIDER, LANE)])
    planner._refresh_lane_locks()
    planner._safe_get_profiles = lambda *a: {}
    planner._safe_get_capacity = lambda *a: None
    planner._lane_gpu_devices_str = lambda *a: None
    planner._get_per_gpu_free = lambda *a: {}
    planner._check_host_ram_headroom_for_sleep = lambda *a, **k: (False, 100.0, 4_000.0)
    escalated = []

    async def confirm(action, timeout_seconds=60.0, deadline=None):  # noqa: ARG001
        escalated.append(action)
        return True

    planner._execute_action_with_confirmation = confirm
    action = CapacityPlanAction(
        action="sleep_l1",
        provider_id=PROVIDER,
        lane_id=LANE,
        model_name=MODEL,
        operator_initiated=True,
    )

    assert asyncio.run(planner._execute_action_core(action)) is True
    assert [(a.action, a.operator_initiated) for a in escalated] == [("stop", True)]


def _profile(loaded_vram_mb):
    return SimpleNamespace(
        loaded_vram_mb=loaded_vram_mb,
        sleeping_residual_mb=500.0,
        base_residency_mb=loaded_vram_mb,
        kv_budget_mb=0.0,
        tensor_parallel_size=1,
        residency_source="calibrated",
        engine="vllm",
        estimate_base_residency_mb=lambda: loaded_vram_mb,
    )


def test_a_worker_whose_only_victim_is_locked_cannot_win_the_ranking():
    planner = _planner(_Facade(), lock_reader=lambda: [(PROVIDER, OTHER_LANE)])
    planner._refresh_lane_locks()
    lanes = [_signal(OTHER_LANE, OTHER_MODEL)]
    profiles = {MODEL: _profile(30_000.0)}
    capacity = SimpleNamespace(available_vram_mb=5_000.0, total_vram_mb=48_000.0)

    assert planner._estimate_demand_action_cost(PROVIDER, MODEL, lanes, profiles, capacity) is None


def test_an_unlocked_victim_still_makes_the_worker_feasible():
    planner = _planner(_Facade())
    lanes = [_signal(OTHER_LANE, OTHER_MODEL)]
    profiles = {MODEL: _profile(30_000.0)}
    capacity = SimpleNamespace(available_vram_mb=5_000.0, total_vram_mb=48_000.0)

    assert planner._estimate_demand_action_cost(PROVIDER, MODEL, lanes, profiles, capacity) is not None


def test_a_lock_pushed_after_planning_refuses_the_automatic_sleep():
    reads = []

    def reader():
        reads.append(1)
        return []

    planner = _planner(_Facade(), lock_reader=reader)
    planner._refresh_lane_locks()
    ran = []

    async def core(action, timeout_seconds=60.0, deadline=None):  # noqa: ARG001
        ran.append(action.action)
        return True

    planner._execute_action_core = core
    # The webservice pushes a lock taken after the cycle planned the sleep.
    planner.apply_lane_lock(PROVIDER, LANE, True, 1)
    action = CapacityPlanAction(action="sleep_l1", provider_id=PROVIDER, lane_id=LANE, model_name=MODEL)

    assert asyncio.run(planner._execute_action_with_confirmation(action)) is False
    assert ran == []
    # Decided from memory: no database read on the execution path.
    assert len(reads) == 1


def test_a_lane_locked_while_it_drains_is_not_slept():
    locks = []
    planner = _planner(_Facade(), lock_reader=lambda: list(locks))
    planner._refresh_lane_locks()
    planner._safe_get_profiles = lambda *a: {}
    planner._safe_get_capacity = lambda *a: None
    planner._lane_gpu_devices_str = lambda *a: None
    planner._get_per_gpu_free = lambda *a: {}
    planner._check_host_ram_headroom_for_sleep = lambda *a, **k: (True, 0.0, 0.0)
    planner._mark_lane_cold = lambda *a: None
    sent = []

    async def drain(provider_id, lane_id, timeout_seconds=60.0):  # noqa: ARG001
        # The operator locks the lane while its requests drain; the
        # webservice pushes the change.
        planner.apply_lane_lock(PROVIDER, LANE, True, 1)
        return True

    async def send_command(*args, **kwargs):  # noqa: ARG001
        sent.append(args)

    planner._drain_lane = drain
    planner._registry.send_command = send_command
    action = CapacityPlanAction(action="sleep_l1", provider_id=PROVIDER, lane_id=LANE, model_name=MODEL)

    assert asyncio.run(planner._execute_action_core(action)) is False
    assert sent == []


def test_lock_changes_delivered_in_reverse_order_keep_the_newer_one():
    planner = _planner(_Facade())

    # The admin unlocked (revision 1) and then locked (revision 2); the
    # unlock push arrives last.
    planner.apply_lane_lock(PROVIDER, LANE, True, 2)
    planner.apply_lane_lock(PROVIDER, LANE, False, 1)

    assert planner.is_lane_locked(PROVIDER, LANE)

    planner.apply_lane_lock(PROVIDER, LANE, False, 3)
    assert not planner.is_lane_locked(PROVIDER, LANE)


def test_a_push_older_than_the_last_read_is_ignored():
    # The table already shows the lane unlocked at revision 5.
    planner = _planner(_Facade(), lock_reader=lambda: [(PROVIDER, LANE, False, 5)])
    planner._refresh_lane_locks()

    planner.apply_lane_lock(PROVIDER, LANE, True, 4)

    assert not planner.is_lane_locked(PROVIDER, LANE)


def test_a_read_newer_than_a_push_wins():
    rows = [(PROVIDER, LANE, True, 9)]
    planner = _planner(_Facade(), lock_reader=lambda: list(rows))
    planner.apply_lane_lock(PROVIDER, LANE, False, 8)

    planner._refresh_lane_locks()

    assert planner.is_lane_locked(PROVIDER, LANE)


def test_a_locked_lane_on_one_worker_does_not_suppress_another_workers_lock_wake():
    # The model was already planned this cycle — by the lock wake of a copy on
    # another worker whose wake may still fail VRAM validation. This worker's
    # locked copy must be woken on its own.
    lanes = [_signal(LANE, MODEL, runtime_state="sleeping", sleep_state="sleeping")]
    planner = _planner(_Facade(lanes), lock_reader=lambda: [(PROVIDER, LANE)])
    planner._refresh_lane_locks()

    actions = planner._compute_lock_wake_actions(PROVIDER, lanes, {MODEL})

    assert [(a.action, a.lane_id) for a in actions] == [("wake", LANE)]


class _DrainFacade(_Facade):
    def get_worker_capabilities(self, provider_id):  # noqa: ARG002
        return [MODEL, OTHER_MODEL, "third/model"]

    def get_model_profiles(self, provider_id):  # noqa: ARG002
        return {}


def test_demand_drain_skips_a_locked_busy_lane_and_takes_the_next_one():
    third_lane = "planner-third_model"
    lanes = [
        _signal(LANE, MODEL, active=2),
        _signal(third_lane, "third/model", active=1),
    ]
    planner = _planner(_DrainFacade(lanes), lock_reader=lambda: [(PROVIDER, LANE)])
    planner._refresh_lane_locks()
    planner._demand.get_ranked_models = lambda: [(OTHER_MODEL, planner.DRAIN_DEMAND_SCORE_THRESHOLD + 5)]
    planner._should_initiate_drain = lambda *args, **kwargs: True  # noqa: ARG005

    actions = planner._compute_demand_drain_actions(PROVIDER, lanes)

    assert [a.lane_id for a in actions] == [third_lane]


def test_a_busy_locked_lane_is_not_worth_waiting_for():
    # A request needs the memory a busy locked lane holds. The lane can never
    # be reclaimed, so the request must not poll until its deadline for it.
    busy_locked = _signal(LANE, MODEL, active=2)
    target = _signal(OTHER_LANE, OTHER_MODEL, runtime_state="cold", sleep_state="unsupported")
    planner = _planner(_Facade([busy_locked]), lock_reader=lambda: [(PROVIDER, LANE)])
    kwargs = dict(provider_id=PROVIDER, target=target, lanes=[busy_locked], profiles={}, required_free_mb=10_000.0)

    assert planner._has_blocking_busy_lanes(**kwargs) is True  # before the lock is read
    planner._refresh_lane_locks()
    assert planner._has_blocking_busy_lanes(**kwargs) is False
