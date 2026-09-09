"""Idle detection tracks last activity, not sampled concurrency.

The idle timer used to reset only when a poll happened to sample
``active_requests > 0 or queue_waiting > 0``. A blocking planner action (e.g. a
long cold load) can stall the cycle long enough that a short request starts and
completes entirely between two polls, so the poll sees the lane empty and the
idle clock runs straight through the busy window — the lane is then slept while
it was demonstrably active.

The fix feeds the idle tracker a monotonic last-activity timestamp that the
facade records from request begin/complete events. These tests cover both ends:
the facade recording the timestamp, and the planner refusing to sleep a lane
whose last activity is recent even though the poll caught it empty.
"""

import time

from logos import CapacityPlanner, LaneSchedulerSignals
from logos.queue import PriorityQueueManager
from logos.sdi.logosnode_facade import LogosNodeSchedulingDataFacade

MODEL = "Qwen/Qwen3.8-27B"
OTHER_MODEL = "Qwen/Qwen3.6-35B-A3B"
LANE = "planner-Qwen_Qwen3.8-27B"
OTHER_LANE = "planner-Qwen_Qwen3.6-35B"
PROVIDER = 13


# ---------------------------------------------------------------------------
# Planner-side: the idle clock is pushed forward to the last activity
# ---------------------------------------------------------------------------


def _signal(lane_id, model, *, runtime_state="loaded", sleep_state="awake", active=0, queue=0.0, is_vllm=True):
    return LaneSchedulerSignals(
        lane_id=lane_id,
        model_name=model,
        runtime_state=runtime_state,
        sleep_state=sleep_state,
        is_vllm=is_vllm,
        active_requests=active,
        queue_waiting=queue,
        requests_running=float(active),
        gpu_cache_usage_percent=None,
        ttft_p95_seconds=0.0,
        e2e_latency_p50_seconds=0.0,
        effective_vram_mb=0.0,
        num_parallel=1,
    )


def _lanes():
    # Two awake vLLM lanes so the "only one usable lane on a worker" guard does
    # not short-circuit the idle pass.
    return [_signal(LANE, MODEL), _signal(OTHER_LANE, OTHER_MODEL)]


class _StubRegistry:
    def peek_runtime_snapshot(self, provider_id):  # noqa: ARG002
        return None

    def is_provider_online(self, provider_id):  # noqa: ARG002
        return True


class _Facade:
    """A planner facade whose last-activity map the test controls directly."""

    def __init__(self, last_activity):
        self._last_activity = last_activity

    def get_provider_name(self, provider_id):  # noqa: ARG002
        return "worker"

    def get_model_last_activity(self, provider_id, model_name):
        return self._last_activity.get((provider_id, model_name))

    def get_scheduler_queue_depth_by_model_name(self, model_name, provider_id):  # noqa: ARG002
        return 0


def _planner(last_activity):
    return CapacityPlanner(
        logosnode_facade=_Facade(last_activity),
        logosnode_registry=_StubRegistry(),
        demand_tracker=None,
    )


def _idle_actions(planner, lanes):
    planner._update_idle_tracking(PROVIDER, lanes)
    return planner._compute_idle_actions(PROVIDER, lanes)


def _sleep_l1_for(actions, lane_id):
    return [a for a in actions if a.action == "sleep_l1" and a.lane_id == lane_id]


def test_lane_busy_between_polls_is_not_slept():
    """A completion a few seconds ago keeps the lane awake even though the poll
    catches it empty — the idle clock is pushed forward to the last activity."""
    last_activity = time.time() - 5.0
    planner = _planner({(PROVIDER, MODEL): last_activity})
    key = planner._lane_key(PROVIDER, LANE)
    # The idle clock that accumulated across the window the cycle was blocked.
    planner._lane_idle_since[key] = last_activity - 177.0  # ~182 s ago

    actions = _idle_actions(planner, _lanes())

    assert _sleep_l1_for(actions, LANE) == []
    # The idle start moved forward to the last activity, not left stale.
    assert planner._lane_idle_since[key] == last_activity


def test_lane_idle_long_enough_is_still_slept():
    """No recent activity: a genuinely idle lane is still slept as before."""
    planner = _planner({})  # no recorded activity for the model
    key = planner._lane_key(PROVIDER, LANE)
    planner._lane_idle_since[key] = time.time() - 182.0

    actions = _idle_actions(planner, _lanes())

    assert len(_sleep_l1_for(actions, LANE)) == 1


def test_older_last_activity_does_not_reset_a_longer_idle_clock():
    """Last-activity only ever pushes the clock forward. A timestamp older than
    the recorded idle start (clock drift, stale event) must not move it back."""
    idle_start = time.time() - 182.0
    last_activity = idle_start - 20.0  # 200 s ago — older than the idle start
    planner = _planner({(PROVIDER, MODEL): last_activity})
    key = planner._lane_key(PROVIDER, LANE)
    planner._lane_idle_since[key] = idle_start

    _idle_actions(planner, _lanes())

    assert planner._lane_idle_since[key] == idle_start  # unchanged


# ---------------------------------------------------------------------------
# Facade-side: request events record a monotonic last-activity timestamp
# ---------------------------------------------------------------------------


def _real_facade(monkeypatch, *, provider_id=PROVIDER, model_name=MODEL, model_id=1):
    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._load_provider_config",
        lambda self: {},
    )
    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._fetch_ps_data",
        lambda self: {"models": []},
    )
    facade = LogosNodeSchedulingDataFacade(PriorityQueueManager())
    facade.register_model(model_id, "logosnode", "http://fake", model_name, 65536, provider_id=provider_id)
    return facade


def _drive_one_request(facade, request_id="req-1", model_id=1, provider_id=PROVIDER):
    facade.on_request_start(request_id, model_id, provider_id)
    facade.on_request_begin_processing(request_id, increment_active=True, provider_id=provider_id)
    facade.on_request_complete(request_id, was_cold_start=False, duration_ms=600.0, provider_id=provider_id)


def test_facade_records_last_activity_on_request_events(monkeypatch):
    facade = _real_facade(monkeypatch)
    before = time.time()
    _drive_one_request(facade)
    after = time.time()

    ts = facade.get_model_last_activity(PROVIDER, MODEL)
    assert ts is not None
    assert before <= ts <= after


def test_facade_last_activity_is_none_until_a_request(monkeypatch):
    facade = _real_facade(monkeypatch)
    assert facade.get_model_last_activity(PROVIDER, MODEL) is None
    assert facade.get_model_last_activity(999, MODEL) is None


def test_facade_last_activity_scoped_per_provider(monkeypatch):
    facade = _real_facade(monkeypatch, provider_id=PROVIDER)
    _drive_one_request(facade, provider_id=PROVIDER)

    assert facade.get_model_last_activity(PROVIDER, MODEL) is not None
    # The same model on a different provider has no recorded activity.
    assert facade.get_model_last_activity(PROVIDER + 1, MODEL) is None


# ---------------------------------------------------------------------------
# End to end: a completion recorded by the real facade keeps the real planner
# from sleeping the lane on the next (empty) poll.
# ---------------------------------------------------------------------------


def test_request_completion_between_polls_prevents_sleep(monkeypatch):
    facade = _real_facade(monkeypatch)
    _drive_one_request(facade)
    last_activity = facade.get_model_last_activity(PROVIDER, MODEL)
    assert last_activity is not None

    planner = CapacityPlanner(
        logosnode_facade=facade,
        logosnode_registry=_StubRegistry(),
        demand_tracker=None,
    )
    key = planner._lane_key(PROVIDER, LANE)
    # The idle clock had accumulated across the window where the cycle blocked.
    planner._lane_idle_since[key] = last_activity - 177.0

    lanes = _lanes()
    planner._update_idle_tracking(PROVIDER, lanes)
    actions = planner._compute_idle_actions(PROVIDER, lanes)

    assert _sleep_l1_for(actions, LANE) == []
    assert planner._lane_idle_since[key] == last_activity


def test_no_activity_between_polls_still_sleeps(monkeypatch):
    """Same wiring, but the lane did no work: the accumulated idle clock still
    crosses the threshold and the lane is slept."""
    facade = _real_facade(monkeypatch)  # no request driven
    planner = CapacityPlanner(
        logosnode_facade=facade,
        logosnode_registry=_StubRegistry(),
        demand_tracker=None,
    )
    key = planner._lane_key(PROVIDER, LANE)
    planner._lane_idle_since[key] = time.time() - 182.0

    lanes = _lanes()
    planner._update_idle_tracking(PROVIDER, lanes)
    actions = planner._compute_idle_actions(PROVIDER, lanes)

    assert len(_sleep_l1_for(actions, LANE)) == 1
