"""Tests for the planner's per-(provider, model) engine-cache metric refresh (issue 819).

The planner aggregates the workers' lane backend metrics into
``(model, provider, prefix_cache_hit_rate, mtp_acceptance_rate)`` entries and
hands them to ``prom.update_engine_cache_metrics``. The publish function is
replaced with a recorder so these tests only cover the aggregation.
"""

import pytest

from logos import CapacityPlanner
from logos.monitoring import prometheus_metrics as prom


def _lane(model, *, prefix=None, draft=None, accepted=None):
    backend_metrics = {}
    if prefix is not None:
        backend_metrics["prefix_cache_hit_rate"] = prefix
    if draft is not None:
        backend_metrics["mtp_draft_tokens_total"] = draft
    if accepted is not None:
        backend_metrics["mtp_accepted_tokens_total"] = accepted
    return {"model": model, "backend_metrics": backend_metrics}


def _snapshot(lanes):
    return {"runtime": {"lanes": lanes}}


def _make_planner(provider_lanes, provider_names):
    class _Registry:
        def peek_runtime_snapshot(self, pid):
            return provider_lanes.get(pid)

    class _Facade:
        def get_provider_name(self, pid):
            return provider_names.get(pid, str(pid))

    return CapacityPlanner(
        logosnode_facade=_Facade(),
        logosnode_registry=_Registry(),
        demand_tracker=None,
    )


def _run_refresh(monkeypatch, planner, provider_ids):
    calls = []
    monkeypatch.setattr(prom, "update_engine_cache_metrics", lambda entries: calls.append(entries))
    planner._refresh_engine_cache_metrics(provider_ids)
    return calls[0] if calls else []


def test_aggregates_prefix_mean_and_token_weighted_mtp_per_pair(monkeypatch):
    planner = _make_planner(
        {
            1: _snapshot(
                [
                    _lane("model-a", prefix=0.6, draft=100, accepted=60),
                    _lane("model-a", prefix=0.8, draft=300, accepted=90),
                ]
            ),
            2: _snapshot([_lane("model-a", prefix=0.4)]),
        },
        {1: "node-a", 2: "node-b"},
    )

    entries = _run_refresh(monkeypatch, planner, [1, 2])

    # Same model on two providers: two independent (model, provider) pairs.
    by_pair = {(model, provider): (prefix, mtp) for model, provider, prefix, mtp in entries}
    assert set(by_pair) == {("model-a", "node-a"), ("model-a", "node-b")}

    prefix, mtp = by_pair[("model-a", "node-a")]
    # Prefix: plain mean of the per-lane rates (0.6 + 0.8) / 2.
    assert prefix == pytest.approx(0.7)
    # MTP: token-weighted across lanes — (60 + 90) / (100 + 300), NOT the
    # unweighted mean of the per-lane rates ((0.6 + 0.3) / 2 = 0.45).
    assert mtp == pytest.approx(150 / 400)

    prefix, mtp = by_pair[("model-a", "node-b")]
    assert prefix == pytest.approx(0.4)
    # No speculative decoding on this lane: rate absent, not zero.
    assert mtp is None


def test_lane_without_any_metrics_yields_pair_with_none_rates(monkeypatch):
    """An ollama lane (or a failed vLLM scrape) still claims its pair."""
    planner = _make_planner(
        {1: _snapshot([_lane("model-b")])},
        {1: "node-a"},
    )

    entries = _run_refresh(monkeypatch, planner, [1])

    assert entries == [("model-b", "node-a", None, None)]


def test_offline_provider_contributes_no_entries(monkeypatch):
    planner = _make_planner(
        {1: _snapshot([_lane("model-a", prefix=0.5, draft=10, accepted=5)]), 2: None},
        {1: "node-a", 2: "node-b"},
    )

    entries = _run_refresh(monkeypatch, planner, [1, 2])

    assert entries == [("model-a", "node-a", 0.5, 0.5)]


def test_unnamed_provider_falls_back_to_id(monkeypatch):
    planner = _make_planner(
        {7: _snapshot([_lane("model-a", prefix=0.25)])},
        {},
    )

    entries = _run_refresh(monkeypatch, planner, [7])

    assert entries == [("model-a", "7", 0.25, None)]


def test_prefix_average_ignores_lanes_without_a_rate(monkeypatch):
    """A lane whose scrape dropped the rate must not skew the model mean."""
    planner = _make_planner(
        {1: _snapshot([_lane("model-a", prefix=0.8), _lane("model-a")])},
        {1: "node-a"},
    )

    entries = _run_refresh(monkeypatch, planner, [1])

    assert entries == [("model-a", "node-a", 0.8, None)]
