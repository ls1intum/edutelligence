"""Tests for prefix-cache affinity bias in SimpleScheduler (issue #530).

When two applications use the same model concurrently, requests from the same
caller must consistently land on the same provider so prefix caches stay warm.
The bias is "slight": load-comparable preferred providers win, but heavily
loaded preferred providers still lose to lightly loaded alternatives.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from logos.pipeline.scheduler_interface import SchedulingRequest
from logos.pipeline.simple_scheduler import (
    SimpleScheduler,
    _AFFINITY_LOAD_DISCOUNT,
    _affinity_score,
    _preferred_provider_id,
)
from logos.queue.priority_queue import PriorityQueueManager


def _make_scheduler(provider_type="logosnode", logosnode=None):
    """Build a scheduler with a fake facade so READY classification is forced."""
    qmgr = PriorityQueueManager()
    fake_logosnode = logosnode or MagicMock()
    fake_logosnode.get_provider_name.return_value = "logosnode-mock"
    return SimpleScheduler(
        queue_manager=qmgr,
        logosnode_facade=fake_logosnode,
        azure_facade=MagicMock(),
        peer_facade=None,
        model_registry={},
    )


def _make_request(*, request_id, deployments, weight=1.0, affinity_key=None):
    return SchedulingRequest(
        request_id=request_id,
        payload={"messages": []},
        deployments=deployments,
        classified_models=[(deployments[0]["model_id"], weight, 0, 1)],
        affinity_key=affinity_key,
    )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_affinity_score_is_deterministic_across_calls():
    a = _affinity_score("lg-app-a", 5, 100)
    b = _affinity_score("lg-app-a", 5, 100)
    assert a == b


def test_affinity_score_differs_per_caller():
    a = _affinity_score("lg-app-a", 5, 100)
    b = _affinity_score("lg-app-b", 5, 100)
    assert a != b


def test_preferred_provider_id_returns_one_of_the_candidates():
    candidates = [
        (5, 100, 1.0, None, 0, 0.0, None),
        (5, 200, 1.0, None, 0, 0.0, None),
        (5, 300, 1.0, None, 0, 0.0, None),
    ]
    preferred = _preferred_provider_id("lg-app-a", 5, candidates)
    assert preferred in {100, 200, 300}


def test_two_callers_can_resolve_to_different_preferred_providers():
    """The whole point of #530: different callers should distribute across
    providers so each cache stays warm for one caller."""
    candidates = [
        (5, 100, 1.0, None, 0, 0.0, None),
        (5, 200, 1.0, None, 0, 0.0, None),
        (5, 300, 1.0, None, 0, 0.0, None),
        (5, 400, 1.0, None, 0, 0.0, None),
    ]
    distinct = {
        _preferred_provider_id(f"lg-app-{i}", 5, candidates)
        for i in range(20)
    }
    # Across 20 different callers we must hit at least 2 different providers
    # (rendezvous hashing across 4 buckets makes >2 nearly certain).
    assert len(distinct) >= 2


# ---------------------------------------------------------------------------
# Scheduler integration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_same_caller_repeats_pin_to_same_provider(monkeypatch):
    """Repeat requests from one logos_key for one model land on one provider
    when load is equal."""
    scheduler = _make_scheduler()

    deployments = [
        {"model_id": 5, "provider_id": 100, "type": "logosnode"},
        {"model_id": 5, "provider_id": 200, "type": "logosnode"},
        {"model_id": 5, "provider_id": 300, "type": "logosnode"},
    ]

    # Force every candidate to classify as READY with zero load.
    from logos.pipeline.ettft_estimator import ReadinessSignal, ReadinessTier

    monkeypatch.setattr(
        scheduler,
        "_classify_candidate",
        lambda model_id, provider_id, provider_type: (
            ReadinessSignal(tier=ReadinessTier.READY, reasoning="test"),
            0.0,
        ),
    )
    monkeypatch.setattr(scheduler, "_get_provider_type", lambda *a, **k: "logosnode")

    chosen = set()
    for i in range(5):
        req = _make_request(
            request_id=f"r{i}", deployments=deployments, affinity_key="lg-app-a"
        )
        result = await scheduler.schedule(req)
        chosen.add(result.provider_id)

    assert len(chosen) == 1, f"expected single sticky provider, got {chosen}"


@pytest.mark.asyncio
async def test_no_affinity_falls_back_to_lowest_load(monkeypatch):
    """Without an affinity_key the legacy "lowest requests_running wins"
    behaviour is preserved."""
    scheduler = _make_scheduler()

    deployments = [
        {"model_id": 5, "provider_id": 100, "type": "logosnode"},
        {"model_id": 5, "provider_id": 200, "type": "logosnode"},
    ]

    from logos.pipeline.ettft_estimator import ReadinessSignal, ReadinessTier

    # provider 200 is less loaded -> should win.
    def _classify(model_id, provider_id, _ptype):
        load = 5.0 if provider_id == 100 else 1.0
        return (
            ReadinessSignal(tier=ReadinessTier.READY, reasoning="test"),
            load,
        )

    monkeypatch.setattr(scheduler, "_classify_candidate", _classify)
    monkeypatch.setattr(scheduler, "_get_provider_type", lambda *a, **k: "logosnode")

    req = _make_request(
        request_id="r1", deployments=deployments, affinity_key=None
    )
    result = await scheduler.schedule(req)
    assert result.provider_id == 200


@pytest.mark.asyncio
async def test_heavily_loaded_preferred_loses_to_lightly_loaded_alternative(
    monkeypatch,
):
    """The bias is "slight": once the preferred provider's load exceeds an
    alternative's by more than `_AFFINITY_LOAD_DISCOUNT`, the alternative wins."""
    scheduler = _make_scheduler()

    deployments = [
        {"model_id": 5, "provider_id": 100, "type": "logosnode"},
        {"model_id": 5, "provider_id": 200, "type": "logosnode"},
    ]

    # Pick an affinity_key that prefers provider 100, then load it heavily.
    candidates_for_pref = [
        (5, 100, 1.0, None, 0, 0.0, None),
        (5, 200, 1.0, None, 0, 0.0, None),
    ]
    # Try several keys until we find one that prefers 100, to make the test deterministic.
    affinity_key = next(
        k
        for k in (f"lg-test-{i}" for i in range(50))
        if _preferred_provider_id(k, 5, candidates_for_pref) == 100
    )

    from logos.pipeline.ettft_estimator import ReadinessSignal, ReadinessTier

    def _classify(model_id, provider_id, _ptype):
        # 100 (preferred) has 5 in flight; 200 has 1.  After the discount
        # 100's effective load is 4.0, still > 200's 1.0 -> 200 wins.
        load = 5.0 if provider_id == 100 else 1.0
        return (
            ReadinessSignal(tier=ReadinessTier.READY, reasoning="test"),
            load,
        )

    monkeypatch.setattr(scheduler, "_classify_candidate", _classify)
    monkeypatch.setattr(scheduler, "_get_provider_type", lambda *a, **k: "logosnode")

    req = _make_request(
        request_id="r1", deployments=deployments, affinity_key=affinity_key
    )
    result = await scheduler.schedule(req)
    assert result.provider_id == 200


@pytest.mark.asyncio
async def test_preferred_wins_when_load_difference_within_discount(monkeypatch):
    """Preferred provider with `_AFFINITY_LOAD_DISCOUNT` more load still wins."""
    scheduler = _make_scheduler()

    deployments = [
        {"model_id": 5, "provider_id": 100, "type": "logosnode"},
        {"model_id": 5, "provider_id": 200, "type": "logosnode"},
    ]

    candidates_for_pref = [
        (5, 100, 1.0, None, 0, 0.0, None),
        (5, 200, 1.0, None, 0, 0.0, None),
    ]
    affinity_key = next(
        k
        for k in (f"lg-test-{i}" for i in range(50))
        if _preferred_provider_id(k, 5, candidates_for_pref) == 100
    )

    from logos.pipeline.ettft_estimator import ReadinessSignal, ReadinessTier

    def _classify(model_id, provider_id, _ptype):
        # 100 has exactly DISCOUNT more load than 200 -> they tie after the
        # discount, sort stability picks first (provider 100 was added first).
        load = _AFFINITY_LOAD_DISCOUNT if provider_id == 100 else 0.0
        return (
            ReadinessSignal(tier=ReadinessTier.READY, reasoning="test"),
            load,
        )

    monkeypatch.setattr(scheduler, "_classify_candidate", _classify)
    monkeypatch.setattr(scheduler, "_get_provider_type", lambda *a, **k: "logosnode")

    req = _make_request(
        request_id="r1", deployments=deployments, affinity_key=affinity_key
    )
    result = await scheduler.schedule(req)
    assert result.provider_id == 100
