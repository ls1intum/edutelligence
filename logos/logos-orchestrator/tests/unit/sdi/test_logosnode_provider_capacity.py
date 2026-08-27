"""Tests for LogosNodeDataProvider parallel capacity gating.

The orchestrator must gate request forwarding on the *worker-reported*
per-worker limit (vLLM parses its own KV-budget-derived "Maximum
concurrency" startup line into lane `num_parallel`).  Requests that do not
fit stay in the orchestrator-level queue instead of piling up in the
vLLM-side queue, so whichever worker frees a slot first gets the request.
"""

from logos.queue import PriorityQueueManager
from logos.sdi.logosnode_facade import LogosNodeSchedulingDataFacade


def _lane(model: str, num_parallel: int, *, vllm: bool = True, runtime_state: str = "loaded", queue_waiting: float = 0):
    return {
        "lane_id": f"lane-{model}-{num_parallel}",
        "model": model,
        "runtime_state": runtime_state,
        "vllm": vllm,
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


def test_runtime_capacity_uses_vllm_reported_concurrency_as_is(monkeypatch):
    # No ×N oversubscription: the worker's KV-budget-derived limit is the gate.
    provider = _provider(monkeypatch, [_lane("m", 10)])
    assert provider.get_parallel_capacity(1) == (10, "runtime")


def test_runtime_capacity_sums_across_matching_lanes(monkeypatch):
    provider = _provider(monkeypatch, [_lane("m", 10), _lane("m", 10)])
    assert provider.get_parallel_capacity(1) == (20, "runtime")


def test_runtime_capacity_unreported_vllm_lane_defaults_to_256(monkeypatch):
    # Older worker or lane still starting: 0 means "not reported yet".
    provider = _provider(monkeypatch, [_lane("m", 0)])
    assert provider.get_parallel_capacity(1) == (256, "runtime")


def test_runtime_capacity_ollama_lane_is_explicit(monkeypatch):
    provider = _provider(monkeypatch, [_lane("m", 8, vllm=False)])
    assert provider.get_parallel_capacity(1) == (8, "runtime")


def test_runtime_capacity_skips_stopped_and_error_lanes(monkeypatch):
    provider = _provider(
        monkeypatch,
        [_lane("m", 10, runtime_state="stopped"), _lane("m", 10, runtime_state="error")],
    )
    assert provider._get_runtime_parallel_capacity(1) == (None, "config")
    assert provider.get_parallel_capacity(1) == (200, "default")


def test_parallel_capacity_is_not_capped_below_worker_report(monkeypatch):
    # The DB `parallel` column used to act as a hard ceiling; it no longer
    # exists in the orchestrator.  A worker reporting 500 slots must get 500.
    provider = _provider(monkeypatch, [_lane("m", 500)])
    assert provider.get_parallel_capacity(1) == (500, "runtime")


def test_parallel_capacity_without_runtime_registry_defaults(monkeypatch):
    provider = _provider(monkeypatch, [], with_registry=False)
    assert provider.get_parallel_capacity(1) == (200, "default")


def test_explicit_provider_config_parallel_capacity_still_wins(monkeypatch):
    provider = _provider(monkeypatch, [_lane("m", 10)], config={"parallel_capacity": 16})
    assert provider.get_parallel_capacity(1) == (16, "config")


def test_reserve_capacity_enforces_worker_reported_limit(monkeypatch):
    # The forward gate: requests stop at the worker's true limit and keep
    # queueing at orchestrator level until a slot frees.
    provider = _provider(monkeypatch, [_lane("m", 2)])
    assert provider.try_reserve_capacity(1, "r1") is True
    assert provider.try_reserve_capacity(1, "r2") is True
    assert provider.try_reserve_capacity(1, "r3") is False
    assert provider.get_active_count(1) == 2

    provider.decrement_active(1, request_id="r1")
    assert provider.try_reserve_capacity(1, "r3") is True
    assert provider.get_active_count(1) == 2


def test_reserve_capacity_refuses_on_backend_queue_pressure(monkeypatch):
    # Worker limit not yet reached, but the engine queue is saturated:
    # refuse here so the request waits at orchestrator level.
    provider = _provider(monkeypatch, [_lane("m", 10, queue_waiting=9)])
    assert provider.try_reserve_capacity(1, "r1") is False
    assert provider.get_active_count(1) == 0
