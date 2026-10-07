"""Tests for LogosNodeDataProvider parallel capacity.

This is the orchestrator's *local ledger* — how many requests it will hold
against one (model, worker) at a time. It is not the forwarding gate; that
lives in `evaluate_admission` and reads the live engine signals (see
`test_logosnode_admission.py`).

The two differ on `num_parallel`. The worker guarantees this concurrency at
*full context*, so it is a lower bound rather than a hard ceiling.
Measured: a dev lane reporting `num_parallel=4` served 23 concurrent
requests at 47% KV; a production lane reporting 1 served 8 at 78%. Used as a
ceiling it throttles by 5-8x. So the ledger keeps a loose ceiling and lets
admission do the real gating.
"""

from logos.queue import PriorityQueueManager
from logos.sdi.logosnode_facade import LogosNodeSchedulingDataFacade


def _lane(model: str, num_parallel: int, *, runtime_state: str = "loaded", queue_waiting: float = 0):
    return {
        "lane_id": f"lane-{model}-{num_parallel}",
        "model": model,
        "runtime_state": runtime_state,
        "vllm": True,
        "num_parallel": num_parallel,
        "backend_metrics": {"queue_waiting": queue_waiting, "requests_running": 0},
    }


def _facade_and_provider(
    monkeypatch,
    lanes,
    *,
    config=None,
    with_registry=True,
    model_ids=None,
    provider_id=13,
    model_name="m",
):
    """Build a facade + registered provider backed by a fake runtime registry."""

    class _FakeRegistry:
        @staticmethod
        def peek_runtime_snapshot(provider_id: int):  # noqa: ARG004
            return {"runtime": {"lanes": lanes}}

        @staticmethod
        def is_provider_online(provider_id: int) -> bool:  # noqa: ARG004
            return True

    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._load_provider_config",
        lambda self: dict(config or {}),
    )
    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._fetch_ps_data",
        lambda self: {"models": []},
    )

    facade = LogosNodeSchedulingDataFacade(
        PriorityQueueManager(), runtime_registry=_FakeRegistry() if with_registry else None
    )
    for model_id in model_ids or [1]:
        facade.register_model(model_id, "logosnode", "http://fake", model_name, 65536, provider_id=provider_id)
    return facade, facade._providers[provider_id]


def _provider(monkeypatch, lanes, *, config=None, with_registry=True, model_ids=None, provider_id=13, model_name="m"):
    """Build a registered provider backed by a fake runtime registry."""
    return _facade_and_provider(
        monkeypatch,
        lanes,
        config=config,
        with_registry=with_registry,
        model_ids=model_ids,
        provider_id=provider_id,
        model_name=model_name,
    )[1]


def test_a_vllm_lane_does_not_cap_the_ledger_at_its_full_context_guarantee(monkeypatch):
    """The number the lane reports is what it can guarantee with every
    request at full context. Real traffic runs far past it, so binding the
    ledger to it would throttle the lane rather than protect it."""
    provider = _provider(monkeypatch, [_lane("m", 4)])
    capacity, source = provider.get_parallel_capacity(1)
    assert capacity > 4
    assert source == "runtime"


def test_the_vllm_ledger_ceiling_is_the_same_whatever_the_lane_reports(monkeypatch):
    """Reporting 1 or 500 must not change the ledger — neither is a
    statement about how many requests the engine can actually hold."""
    tiny = _provider(monkeypatch, [_lane("m", 1)])
    huge = _provider(monkeypatch, [_lane("m", 500)])
    assert tiny.get_parallel_capacity(1) == huge.get_parallel_capacity(1)


def test_runtime_capacity_sums_across_matching_lanes(monkeypatch):
    """Two lanes hold more than one, whatever each reports."""
    one = _provider(monkeypatch, [_lane("m", 10)])
    two = _provider(monkeypatch, [_lane("m", 10), _lane("m", 10)])
    assert two.get_parallel_capacity(1)[0] == 2 * one.get_parallel_capacity(1)[0]


def test_an_unreported_vllm_lane_is_treated_like_any_other(monkeypatch):
    """0 means the worker has not parsed its startup line yet. Since the
    reported value is not used as a ceiling anyway, this is not a special
    case any more."""
    unreported = _provider(monkeypatch, [_lane("m", 0)])
    reported = _provider(monkeypatch, [_lane("m", 8)])
    assert unreported.get_parallel_capacity(1) == reported.get_parallel_capacity(1)


def test_runtime_capacity_skips_stopped_and_error_lanes(monkeypatch):
    provider = _provider(
        monkeypatch,
        [_lane("m", 10, runtime_state="stopped"), _lane("m", 10, runtime_state="error")],
    )
    assert provider._get_runtime_parallel_capacity(1) == (None, "config")
    assert provider.get_parallel_capacity(1) == (200, "default")


def test_parallel_capacity_without_runtime_registry_defaults(monkeypatch):
    provider = _provider(monkeypatch, [], with_registry=False)
    assert provider.get_parallel_capacity(1) == (200, "default")


def test_explicit_provider_config_parallel_capacity_still_wins(monkeypatch):
    provider = _provider(monkeypatch, [_lane("m", 10)], config={"parallel_capacity": 16})
    assert provider.get_parallel_capacity(1) == (16, "config")


def test_reserve_capacity_enforces_the_configured_ledger_limit(monkeypatch):
    """The ledger still bounds what one worker may hold — it is what caps a
    burst, since the engine signals are sampled and cannot. It is just no
    longer sourced from num_parallel for vLLM."""
    provider = _provider(monkeypatch, [_lane("m", 500)], config={"parallel_capacity": 2})
    assert provider.try_reserve_capacity(1, "r1") is True
    assert provider.try_reserve_capacity(1, "r2") is True
    assert provider.try_reserve_capacity(1, "r3") is False
    assert provider.get_active_count(1) == 2

    provider.decrement_active(1, request_id="r1")
    assert provider.try_reserve_capacity(1, "r3") is True
    assert provider.get_active_count(1) == 2


def test_the_ledger_ceiling_does_not_follow_a_low_reported_concurrency(monkeypatch):
    """Regression for the 5-8x throttle: the exact production shape, where
    the lane reports 1 and the engine happily runs 8.

    Concerns the ledger only. What paces those 8 out is the between-snapshot
    forward budget, which releases on each worker report — see
    `test_logosnode_admission.py`.
    """
    provider = _provider(monkeypatch, [_lane("m", 1)])
    assert provider.get_parallel_capacity(1)[0] >= 8


def test_reserve_capacity_refuses_on_backend_queue_pressure(monkeypatch):
    # Worker limit not yet reached, but the engine queue is saturated:
    # refuse here so the request waits at orchestrator level.
    provider = _provider(monkeypatch, [_lane("m", 10, queue_waiting=9)])
    assert provider.try_reserve_capacity(1, "r1") is False
    assert provider.get_active_count(1) == 0


# ---------------------------------------------------------------------------
# The in-flight ledger, split by caller key
# ---------------------------------------------------------------------------


def test_the_in_flight_ledger_is_split_by_caller_key(monkeypatch):
    """`active` says how busy a model is; the split says *who* is keeping it
    busy. A key whose sessions fan out into several concurrent requests
    holds several of the model's slots, and the total alone cannot say so."""
    provider = _provider(monkeypatch, [_lane("m", 8)])
    provider.increment_active(1, request_id="r1", api_key_id=7)
    provider.increment_active(1, request_id="r2", api_key_id=7)
    provider.increment_active(1, request_id="r3", api_key_id=9)

    assert provider.get_active_count(1) == 3
    assert provider.get_debug_state()[1]["active_by_api_key"] == {"7": 2, "9": 1}


def test_the_split_cannot_outrun_the_total(monkeypatch):
    """A request that starts without a key still counts for the model; the
    split is a slice of the total, never something that can push it past
    what the model itself reports."""
    provider = _provider(monkeypatch, [_lane("m", 8)])
    provider.increment_active(1, request_id="r1", api_key_id=7)
    provider.increment_active(1, request_id="r2")

    state = provider.get_debug_state()[1]
    assert state["active"] == 2
    assert sum(state["active_by_api_key"].values()) <= state["active"]
    assert state["active_by_api_key"] == {"7": 1}


def test_a_completion_uncounts_the_key_that_started_it(monkeypatch):
    """The key is recorded with the request at the start, so a completion
    that arrives without one still un-counts the right key — and the split
    empties with the total."""
    provider = _provider(monkeypatch, [_lane("m", 8)])
    provider.increment_active(1, request_id="r1", api_key_id=7)
    provider.decrement_active(1, request_id="r1")

    assert provider.get_active_count(1) == 0
    assert provider.get_debug_state()[1]["active_by_api_key"] == {}


def test_a_completion_without_a_recorded_key_uses_the_callers(monkeypatch):
    provider = _provider(monkeypatch, [_lane("m", 8)])
    provider.increment_active(1, request_id="r1")
    provider.decrement_active(1, request_id="r1", api_key_id=9)

    assert provider.get_active_count(1) == 0
    assert provider.get_debug_state()[1]["active_by_api_key"] == {}


def test_a_stray_completion_cannot_run_the_split_negative(monkeypatch):
    """The clamp the total has always had: a completion with no matching
    start reads as zero, for the model and for every key on it."""
    provider = _provider(monkeypatch, [_lane("m", 8)])
    provider.decrement_active(1, api_key_id=7)

    assert provider.get_active_count(1) == 0
    assert provider.get_debug_state()[1]["active_by_api_key"] == {}


def test_track_active_request_counts_the_key_only_when_it_said_to(monkeypatch):
    provider = _provider(monkeypatch, [_lane("m", 8)])
    provider.track_active_request("r1", 1, increment_active=True, api_key_id=7)
    provider.track_active_request("r2", 1, increment_active=False, api_key_id=9)

    state = provider.get_debug_state()[1]
    assert state["active"] == 1
    assert state["active_by_api_key"] == {"7": 1}


def test_a_reserved_request_still_attributes_its_caller_key(monkeypatch):
    """Reservation books the model total before the key is known.

    ``track_active_request`` must still record the key without bumping the
    total again — otherwise the runner discounts none of its in-flight load.
    """
    provider = _provider(monkeypatch, [_lane("m", 8)])
    assert provider.try_reserve_capacity(1, "r1") is True
    assert provider.get_active_count(1) == 1
    assert provider.get_debug_state()[1]["active_by_api_key"] == {}

    provider.track_active_request("r1", 1, increment_active=False, api_key_id=7)

    state = provider.get_debug_state()[1]
    assert state["active"] == 1
    assert state["active_by_api_key"] == {"7": 1}

    provider.decrement_active(1, request_id="r1")
    assert provider.get_active_count(1) == 0
    assert provider.get_debug_state()[1]["active_by_api_key"] == {}


def test_queued_ownership_is_split_by_caller_key(monkeypatch):
    provider = _provider(monkeypatch, [_lane("m", 8)])
    provider.queue_manager.enqueue(object(), model_id=1, api_key_id=7)
    provider.queue_manager.enqueue(object(), model_id=1, api_key_id=7)
    provider.queue_manager.enqueue(object(), model_id=1, api_key_id=9)
    provider.queue_manager.enqueue(object(), model_id=1)  # unknown caller

    state = provider.get_debug_state()[1]
    assert state["queue_depth"] == 4
    assert state["queued_by_api_key"] == {"7": 2, "9": 1}


def test_removing_a_model_drops_its_split(monkeypatch):
    provider = _provider(monkeypatch, [_lane("m", 8)], model_ids=[1, 2])
    provider.increment_active(1, request_id="r1", api_key_id=7)
    provider.set_registered_models({2: "m"})

    assert 1 not in provider.get_debug_state()
    assert provider.get_debug_state()[2]["active_by_api_key"] == {}


def test_request_events_carry_the_key_from_start_to_completion(monkeypatch):
    """The split is built from what the request's start recorded, and the
    key travels with the request: the start stores it, the processing start
    counts it, and the completion un-counts it — no caller has to remember
    it in between."""
    facade, provider = _facade_and_provider(monkeypatch, [_lane("m", 8)])

    facade.on_request_start("r1", 1, 13, priority="normal", api_key_id=7)
    facade.on_request_begin_processing("r1", increment_active=True, provider_id=13)
    assert provider.get_debug_state()[1]["active_by_api_key"] == {"7": 1}

    facade.on_request_complete("r1", was_cold_start=False, duration_ms=10.0, provider_id=13)
    assert provider.get_active_count(1) == 0
    assert provider.get_debug_state()[1]["active_by_api_key"] == {}
