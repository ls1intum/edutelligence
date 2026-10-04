"""Tests for the orchestrator-level forwarding gate.

A request that is forwarded to a worker is committed: it cannot be
re-prioritised ahead of what is already there, cannot be re-scheduled onto a
peer, and cannot be given back when the worker wants to drain for a restart.
So the orchestrator forwards only while the engine is observed to be keeping
up — everything else waits in the orchestrator queue, where all three remain
possible.

Nothing outside the engine can predict whether vLLM will start a given
request or park it, so the gate is retrospective by necessity: it reads
``queue_waiting`` (the engine is already parking work) and
``gpu_cache_usage_percent`` (it is about to preempt). It deliberately does
*not* compare ``requests_running`` against ``num_parallel`` — see
``test_a_lane_running_far_past_num_parallel_is_still_admissible``.
"""

from logos.queue import PriorityQueueManager
from logos.sdi.logosnode_facade import LogosNodeSchedulingDataFacade


def _lane(
    model: str = "m",
    *,
    num_parallel: int = 10,
    runtime_state: str = "loaded",
    queue_waiting: float = 0,
    requests_running: float = 0,
    gpu_cache_usage_percent: float | None = None,
    lane_id: str | None = None,
):
    backend_metrics = {
        "queue_waiting": queue_waiting,
        "requests_running": requests_running,
    }
    if gpu_cache_usage_percent is not None:
        backend_metrics["gpu_cache_usage_percent"] = gpu_cache_usage_percent
    return {
        "lane_id": lane_id or f"lane-{model}-{num_parallel}-{runtime_state}",
        "model": model,
        "runtime_state": runtime_state,
        "vllm": True,
        "num_parallel": num_parallel,
        "backend_metrics": backend_metrics,
    }


class _FakeRegistry:
    """A worker report the test can advance, the way a heartbeat would."""

    def __init__(self, lanes):
        self.lanes = lanes
        self.runtime_revision = 0
        self.heartbeat = 0

    def new_report(self):
        """Stand in for the next status message arriving from the worker."""
        self.runtime_revision += 1
        self.heartbeat += 1

    def chatter(self):
        """Traffic that touches the session but carries no measurement —
        a stream chunk, a command result, a bare heartbeat."""
        self.heartbeat += 1

    def peek_runtime_snapshot(self, provider_id: int):  # noqa: ARG002
        return {
            "runtime": {"lanes": self.lanes},
            "runtime_revision": self.runtime_revision,
            "last_heartbeat": str(self.heartbeat),
        }

    def is_provider_online(self, provider_id: int) -> bool:  # noqa: ARG002
        return True


def _provider(monkeypatch, lanes, *, with_registry=True, provider_id=13, model_name="m", config=None, model_names=None):

    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._load_provider_config",
        lambda self: dict(config or {}),
    )
    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._fetch_ps_data",
        lambda self: {"models": []},
    )

    facade = LogosNodeSchedulingDataFacade(
        PriorityQueueManager(), runtime_registry=_FakeRegistry(lanes) if with_registry else None
    )
    for model_id, name in (model_names or {1: model_name}).items():
        facade.register_model(model_id, "logosnode", "http://fake", name, 65536, provider_id=provider_id)
    return facade._providers[provider_id]


# ---------------------------------------------------------------------------
# Dispatch step size
# ---------------------------------------------------------------------------


def test_an_idle_lane_offers_its_guaranteed_concurrency_as_a_batch(monkeypatch):
    provider = _provider(monkeypatch, [_lane(num_parallel=10)])
    decision = provider.evaluate_admission(1)
    assert decision.can_admit is True
    assert decision.batch_limit == 10


def test_the_batch_shrinks_as_the_kv_cache_fills(monkeypatch):
    """The step size follows the free KV fraction — the same figure the
    lane-health panel shows as the floating capacity."""
    provider = _provider(monkeypatch, [_lane(num_parallel=10, gpu_cache_usage_percent=70.0)])
    assert provider.evaluate_admission(1).batch_limit == 3


def test_the_batch_sums_across_lanes_of_the_same_model(monkeypatch):
    provider = _provider(
        monkeypatch,
        [
            _lane(num_parallel=10, lane_id="a"),
            _lane(num_parallel=4, lane_id="b"),
        ],
    )
    assert provider.evaluate_admission(1).batch_limit == 14


def test_a_backlogged_lane_does_not_mask_an_idle_sibling(monkeypatch):
    """One saturated lane must not block a model that has a free lane."""
    provider = _provider(
        monkeypatch,
        [
            _lane(num_parallel=4, queue_waiting=3, lane_id="backlogged"),
            _lane(num_parallel=4, lane_id="free"),
        ],
    )
    decision = provider.evaluate_admission(1)
    assert decision.can_admit is True
    assert decision.batch_limit == 4


def test_stopped_and_error_lanes_are_not_counted(monkeypatch):
    provider = _provider(
        monkeypatch,
        [
            _lane(num_parallel=8, runtime_state="stopped"),
            _lane(num_parallel=8, runtime_state="error"),
        ],
    )
    decision = provider.evaluate_admission(1)
    # No routable lane at all → no opinion, capacity gate decides.
    assert decision.can_admit is True
    assert decision.batch_limit is None


# ---------------------------------------------------------------------------
# Hold reasons
# ---------------------------------------------------------------------------


def test_engine_backlog_holds_the_request_at_orchestrator_level(monkeypatch):
    """Anything already waiting inside the engine means a forwarded request
    would only queue behind it — keep it where it can still be reordered."""
    provider = _provider(monkeypatch, [_lane(num_parallel=10, requests_running=2, queue_waiting=1)])
    decision = provider.evaluate_admission(1)
    assert decision.can_admit is False
    assert decision.reason == "backend_queue"


def test_kv_cache_pressure_holds_the_request(monkeypatch):
    """Past the KV threshold vLLM preempts and recomputes, which also evicts
    the prefix-cache blocks sticky routing depends on."""
    provider = _provider(monkeypatch, [_lane(num_parallel=10, requests_running=2, gpu_cache_usage_percent=95.0)])
    decision = provider.evaluate_admission(1)
    assert decision.can_admit is False
    assert decision.reason == "kv_cache_pressure"


def test_kv_cache_below_threshold_still_admits(monkeypatch):
    provider = _provider(monkeypatch, [_lane(num_parallel=10, requests_running=2, gpu_cache_usage_percent=60.0)])
    assert provider.evaluate_admission(1).can_admit is True


def test_a_lane_running_far_past_num_parallel_is_still_admissible(monkeypatch):
    """`num_parallel` is the concurrency vLLM guarantees at *full context*,
    not a ceiling. Production runs this exact lane at 8 concurrent requests
    with num_parallel=1; treating it as a ceiling would throttle it 8x."""
    provider = _provider(monkeypatch, [_lane(num_parallel=1, requests_running=8, gpu_cache_usage_percent=78.0)])
    decision = provider.evaluate_admission(1)
    assert decision.can_admit is True
    assert decision.reason is None


# ---------------------------------------------------------------------------
# "No opinion" fallbacks — the gate must never be stricter than the signals
# ---------------------------------------------------------------------------


def test_a_lane_without_a_reported_limit_still_takes_one_at_a_time(monkeypatch):
    """num_parallel=0 means the worker has not reported yet (older worker or
    a lane still starting). Admit, but step conservatively."""
    provider = _provider(monkeypatch, [_lane(num_parallel=0)])
    decision = provider.evaluate_admission(1)
    assert decision.can_admit is True
    assert decision.batch_limit == 1


def test_no_runtime_registry_gives_no_opinion(monkeypatch):
    provider = _provider(monkeypatch, [], with_registry=False)
    decision = provider.evaluate_admission(1)
    assert decision.can_admit is True
    assert decision.batch_limit is None


# ---------------------------------------------------------------------------
# Reservation path
# ---------------------------------------------------------------------------


def test_reserve_is_refused_while_the_engine_has_a_backlog(monkeypatch):
    provider = _provider(monkeypatch, [_lane(num_parallel=10, queue_waiting=1)])
    assert provider.try_reserve_capacity(1, "r1") is False
    assert provider.get_active_count(1) == 0


def test_reserve_is_refused_under_kv_pressure(monkeypatch):
    provider = _provider(monkeypatch, [_lane(num_parallel=10, gpu_cache_usage_percent=92.0)])
    assert provider.try_reserve_capacity(1, "r1") is False


def test_reserve_succeeds_while_the_engine_has_headroom(monkeypatch):
    provider = _provider(monkeypatch, [_lane(num_parallel=10, requests_running=3)])
    assert provider.try_reserve_capacity(1, "r1") is True
    assert provider.get_active_count(1) == 1


def test_reserve_succeeds_on_a_lane_running_past_num_parallel(monkeypatch):
    """Mirrors production: num_parallel=1 while the engine happily runs 8.
    As long as nothing is queued there, the lane is keeping up."""
    provider = _provider(monkeypatch, [_lane(num_parallel=1, requests_running=8)])
    assert provider.try_reserve_capacity(1, "r1") is True


def test_debug_state_exposes_the_admission_decision(monkeypatch):
    provider = _provider(monkeypatch, [_lane(num_parallel=10, requests_running=2)])
    admission = provider.get_debug_state()[1]["admission"]
    assert admission == {"can_admit": True, "batch_limit": 10, "reason": None}


def test_facade_exposes_admission_for_the_queue_dispatcher(monkeypatch):
    provider = _provider(monkeypatch, [_lane(num_parallel=6, requests_running=2)])
    facade = LogosNodeSchedulingDataFacade(PriorityQueueManager())
    facade._providers[provider.provider_id] = provider
    facade._model_to_provider[1] = {provider.provider_id}
    assert facade.evaluate_admission(1, provider.provider_id).batch_limit == 6


# ---------------------------------------------------------------------------
# The production lane that motivated the design
# ---------------------------------------------------------------------------


def test_the_production_lane_behaves_as_the_operator_expects(monkeypatch):
    """deimama/Qwen3.8-27B, observed live: num_parallel=1, running=8, kv=78%.

    The lane-health panel shows this as "8 / 8 (min. 1)" and the number keeps
    climbing as requests arrive — which is correct, because vLLM admits on
    actual KV block occupancy, not on the full-context guarantee. The gate
    must follow the engine, not the guarantee: hold only once the engine
    itself starts parking work.
    """
    keeping_up = _provider(monkeypatch, [_lane(num_parallel=1, requests_running=8, gpu_cache_usage_percent=78.0)])
    assert keeping_up.evaluate_admission(1).can_admit is True

    # Same lane, one request now waiting: the engine said it could not start
    # it, so the next one stays at orchestrator level.
    parking = _provider(
        monkeypatch,
        [_lane(num_parallel=1, requests_running=8, queue_waiting=1, gpu_cache_usage_percent=78.0)],
    )
    decision = parking.evaluate_admission(1)
    assert decision.can_admit is False
    assert decision.reason == "backend_queue"


def test_the_engine_side_queue_is_held_at_about_one(monkeypatch):
    """The policy in one line: forward while nothing waits, stop at the first
    observed waiter. That leaves the engine one request of lookahead — enough
    to never idle between generations, few enough that essentially everything
    stays re-prioritisable."""
    for waiting, expected in ((0, True), (1, False), (5, False)):
        provider = _provider(monkeypatch, [_lane(num_parallel=8, queue_waiting=waiting)])
        assert provider.evaluate_admission(1).can_admit is expected, f"queue_waiting={waiting}"


def test_the_local_ledger_bounds_what_the_sampled_gate_lets_through(monkeypatch):
    """The engine's view is sampled, so several arrivals inside one heartbeat
    all read the same "nothing waiting". The orchestrator's own count is what
    stops that from becoming unbounded: it is exact and updates per
    reservation, so the snapshot never has to be fresh for the ceiling to
    hold."""
    provider = _provider(monkeypatch, [_lane(num_parallel=8)], config={"parallel_capacity": 3})

    # The snapshot never changes — every call sees an idle-looking engine.
    assert [provider.try_reserve_capacity(1, f"r{i}") for i in range(5)] == [True, True, True, False, False]
    assert provider.get_active_count(1) == 3


# ---------------------------------------------------------------------------
# The between-snapshot forward budget
#
# The engine signals are sampled. Every request arriving inside one sampling
# window reads the same "nothing waiting", so a burst passes the gate
# untouched — measured on logos-dev: 60 concurrent requests, zero holds. The
# orchestrator therefore counts what it has sent since the last report and
# spends the step down by it, restoring the budget when the worker reports
# back. Measured feedback latency on dev: 0.21-1.11s, median ~0.9s.
# ---------------------------------------------------------------------------


def _registry_of(provider):
    return provider._runtime_registry


def test_a_burst_cannot_outrun_the_signal(monkeypatch):
    """Without the budget all of these pass: they all read the same snapshot."""
    provider = _provider(monkeypatch, [_lane(num_parallel=4)])
    granted = [provider.try_reserve_capacity(1, f"r{i}") for i in range(10)]
    assert granted == [True] * 4 + [False] * 6


def test_the_hold_says_it_is_waiting_for_the_signal(monkeypatch):
    provider = _provider(monkeypatch, [_lane(num_parallel=1)])
    provider.try_reserve_capacity(1, "r0")
    decision = provider.evaluate_admission(1)
    assert decision.can_admit is False
    assert decision.reason == "awaiting_signal"


def test_the_next_worker_report_restores_the_budget(monkeypatch):
    """This is what keeps the ramp moving: each report is worth another step,
    and reports arrive within about a second of a request being taken up."""
    provider = _provider(monkeypatch, [_lane(num_parallel=2)])
    assert [provider.try_reserve_capacity(1, f"a{i}") for i in range(3)] == [True, True, False]

    _registry_of(provider).new_report()
    assert [provider.try_reserve_capacity(1, f"b{i}") for i in range(3)] == [True, True, False]
    assert provider.get_active_count(1) == 4


def test_the_budget_shrinks_as_the_cache_fills(monkeypatch):
    """Approaching saturation, each round admits fewer — the step is the
    guaranteed concurrency scaled by the free KV fraction."""
    roomy = _provider(monkeypatch, [_lane(num_parallel=8, gpu_cache_usage_percent=0.0)])
    tight = _provider(monkeypatch, [_lane(num_parallel=8, gpu_cache_usage_percent=75.0)])
    assert roomy.evaluate_admission(1).batch_limit == 8
    assert tight.evaluate_admission(1).batch_limit == 2


def test_a_worker_reporting_nothing_usable_is_not_budgeted(monkeypatch):
    """No signals means no evidence to spend — fall back to the ledger
    rather than inventing a limit."""
    provider = _provider(monkeypatch, [], with_registry=False)
    assert [provider.try_reserve_capacity(1, f"r{i}") for i in range(5)] == [True] * 5


def test_the_budget_is_tracked_per_model(monkeypatch):
    """Two models on one worker must not spend each other's step."""
    provider = _provider(
        monkeypatch,
        [_lane("m", num_parallel=1, lane_id="a"), _lane("other", num_parallel=1, lane_id="b")],
        model_names={1: "m", 2: "other"},
    )
    assert provider.try_reserve_capacity(1, "r1") is True
    assert provider.try_reserve_capacity(1, "r2") is False
    assert provider.try_reserve_capacity(2, "r3") is True


def test_session_chatter_does_not_pass_for_a_measurement(monkeypatch):
    """The budget must key on an actual runtime report. `last_heartbeat` is
    bumped by stream chunks and command results too, so keying on it would
    reset the budget on every chunk — disabling the gate under exactly the
    streaming load it exists for.
    """
    provider = _provider(monkeypatch, [_lane(num_parallel=1)])
    assert provider.try_reserve_capacity(1, "r0") is True
    assert provider.try_reserve_capacity(1, "r1") is False

    _registry_of(provider).chatter()
    assert provider.try_reserve_capacity(1, "r2") is False, "chatter is not a measurement"

    _registry_of(provider).new_report()
    assert provider.try_reserve_capacity(1, "r3") is True
