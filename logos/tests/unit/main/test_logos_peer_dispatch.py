"""Behavioural tests for the `logos_peer` provider type integration.

Covers:
- normalize_provider_type recognises `logos_peer` (and dashed/joined variants)
- ContextResolver injects the `model` name into the payload for `logos_peer`
- classify_peer maps PeerCapacity to the correct ReadinessTier
- SimpleScheduler routes a request to a healthy peer when local is unavailable
  and avoids the peer when its circuit breaker is open
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from logos.dbutils.types import normalize_provider_type
from logos.pipeline.context_resolver import ContextResolver, ExecutionContext
from logos.pipeline.ettft_estimator import ReadinessTier, classify_peer
from logos.pipeline.scheduler_interface import SchedulingRequest
from logos.pipeline.simple_scheduler import SimpleScheduler
from logos.queue.priority_queue import PriorityQueueManager
from logos.sdi.logos_peer_facade import LogosPeerSchedulingDataFacade, PeerCapacity


# ---------------------------------------------------------------------------
# normalize_provider_type
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw", ["logos_peer", "LOGOS_PEER", "logos-peer", "logospeer"])
def test_normalize_recognises_logos_peer_variants(raw):
    assert normalize_provider_type(raw) == "logos_peer"


# ---------------------------------------------------------------------------
# ContextResolver payload injection
# ---------------------------------------------------------------------------

def test_context_resolver_injects_model_for_logos_peer():
    ctx = ExecutionContext(
        model_id=1,
        provider_id=2,
        provider_name="test-peer",
        provider_type="logos_peer",
        forward_url="https://peer.example/v1/chat/completions",
        auth_header="Authorization",
        auth_value="Bearer lg-secret",
        model_name="gpt-4o",
    )
    headers, payload = ContextResolver.prepare_headers_and_payload(
        ctx, {"messages": [{"role": "user", "content": "hi"}]}
    )
    assert headers["Authorization"] == "Bearer lg-secret"
    assert payload["model"] == "gpt-4o"


# ---------------------------------------------------------------------------
# classify_peer
# ---------------------------------------------------------------------------

def _cap(*, healthy=True, has_capacity=True, queue_depth=0, free_slots=4):
    return PeerCapacity(
        provider_id=1,
        is_healthy=healthy,
        has_capacity=has_capacity,
        queue_depth=queue_depth,
        free_slots=free_slots,
        last_poll_at=None,
        last_error=None,
    )


def test_classify_peer_unhealthy_is_unavailable():
    sig = classify_peer(_cap(healthy=False, has_capacity=False))
    assert sig.tier == ReadinessTier.UNAVAILABLE


def test_classify_peer_healthy_with_free_slots_is_ready():
    sig = classify_peer(_cap(healthy=True, has_capacity=True, queue_depth=0))
    assert sig.tier == ReadinessTier.READY


def test_classify_peer_healthy_but_full_is_queueing():
    sig = classify_peer(_cap(healthy=True, has_capacity=False, queue_depth=3))
    assert sig.tier == ReadinessTier.QUEUEING


def test_classify_peer_none_is_unavailable():
    sig = classify_peer(None)
    assert sig.tier == ReadinessTier.UNAVAILABLE


# ---------------------------------------------------------------------------
# SimpleScheduler dispatch
# ---------------------------------------------------------------------------

def _make_scheduler(peer_facade):
    qmgr = PriorityQueueManager()
    logosnode = MagicMock()
    logosnode.get_provider_name.return_value = "logosnode-mock"
    azure = MagicMock()
    return SimpleScheduler(
        queue_manager=qmgr,
        logosnode_facade=logosnode,
        azure_facade=azure,
        peer_facade=peer_facade,
        model_registry={(5, 99): "logos_peer"},
    )


@pytest.mark.asyncio
async def test_scheduler_routes_to_healthy_peer():
    peer = LogosPeerSchedulingDataFacade(
        http_client_factory=lambda: _StaticOkClient(),
        unhealthy_failure_threshold=1,
        healthy_success_threshold=1,
    )
    peer.register_model(
        model_id=5,
        provider_name="test-peer",
        base_url="https://peer.example",
        api_key="lg-secret",
        model_name="gpt-4o",
        provider_id=99,
    )
    peer.poll_once(99)
    assert peer.is_healthy(99) is True

    scheduler = _make_scheduler(peer)
    deployments = [{"model_id": 5, "provider_id": 99, "type": "logos_peer"}]
    request = SchedulingRequest(
        request_id="req-1",
        payload={"messages": []},
        deployments=deployments,
        classified_models=[(5, 1.0, 0, 1)],
    )

    result = await scheduler.schedule(request)
    assert result is not None
    assert result.provider_id == 99
    assert result.provider_type == "logos_peer"


@pytest.mark.asyncio
async def test_scheduler_skips_unhealthy_peer():
    peer = LogosPeerSchedulingDataFacade(
        http_client_factory=lambda: _ErrorClient(),
        unhealthy_failure_threshold=1,
        healthy_success_threshold=1,
    )
    peer.register_model(
        model_id=5,
        provider_name="test-peer",
        base_url="https://peer.example",
        api_key="lg-secret",
        model_name="gpt-4o",
        provider_id=99,
    )
    peer.poll_once(99)
    assert peer.is_healthy(99) is False

    scheduler = _make_scheduler(peer)
    deployments = [{"model_id": 5, "provider_id": 99, "type": "logos_peer"}]
    request = SchedulingRequest(
        request_id="req-2",
        payload={"messages": []},
        deployments=deployments,
        classified_models=[(5, 1.0, 0, 1)],
    )

    result = await scheduler.schedule(request)
    # Only candidate is the unhealthy peer -> nothing viable -> None.
    assert result is None


# ---------------------------------------------------------------------------
# Test HTTP fixtures
# ---------------------------------------------------------------------------

class _StaticOkClient:
    def get(self, url, headers=None):
        class _R:
            status_code = 200

            @staticmethod
            def json():
                return {
                    "status": "healthy",
                    "models": [
                        {
                            "id": "gpt-4o",
                            "available": True,
                            "loaded": True,
                            "queue_depth": 0,
                        }
                    ],
                    "capacity": {"free_slots": 2, "total_models": 1},
                }

        return _R()

    def close(self):
        pass


class _ErrorClient:
    def get(self, url, headers=None):
        class _R:
            status_code = 503

            @staticmethod
            def json():
                return {}

        return _R()

    def close(self):
        pass
