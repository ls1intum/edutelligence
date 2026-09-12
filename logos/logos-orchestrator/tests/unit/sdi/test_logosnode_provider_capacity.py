"""Tests for LogosNodeDataProvider parallel capacity.

This is the orchestrator's *local ledger* — how many requests it will hold
against one (model, worker) at a time. It is not the forwarding gate; that
lives in `evaluate_admission` and reads the live engine signals (see
`test_logosnode_admission.py`).

The two differ on `num_parallel`. #781 read it as the worker's real limit,
but it is the concurrency vLLM guarantees at *full context* — a lower bound.
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


def _provider(monkeypatch, lanes, *, config=None, with_registry=True, model_ids=None, provider_id=13, model_name="m"):
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
    return facade._providers[provider_id]


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
