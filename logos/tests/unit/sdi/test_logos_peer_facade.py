"""Unit tests for `LogosPeerSchedulingDataFacade`.

The facade is exercised without spawning polling threads — `poll_once()` is
called directly and a fake HTTP client is injected so the tests never touch
the network.
"""

from __future__ import annotations

import pytest

from logos.sdi.logos_peer_facade import LogosPeerSchedulingDataFacade


class _FakeResponse:
    def __init__(self, *, status_code: int, body: dict | None = None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body


class _FakeClient:
    """Sequence-driven httpx.Client stand-in. Each `get` call pops the next response."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []

    def get(self, url, headers=None):
        self.requests.append((url, dict(headers or {})))
        if not self._responses:
            raise RuntimeError("no fake responses left")
        return self._responses.pop(0)

    def close(self):
        pass


def _make_facade(responses, **kwargs):
    client = _FakeClient(responses)
    facade = LogosPeerSchedulingDataFacade(
        http_client_factory=lambda: client,
        unhealthy_failure_threshold=3,
        healthy_success_threshold=2,
        **kwargs,
    )
    facade.register_model(
        model_id=12,
        provider_name="test-peer",
        base_url="https://peer.example",
        api_key="lg-secret",
        model_name="gpt-4o",
        provider_id=99,
    )
    return facade, client


def _ok_body(*, free_slots=4, queue_depth=0, available=True, loaded=True):
    return {
        "status": "healthy",
        "models": [
            {
                "id": "gpt-4o",
                "available": available,
                "loaded": loaded,
                "queue_depth": queue_depth,
            }
        ],
        "capacity": {"free_slots": free_slots, "total_models": 1},
    }


def test_register_starts_unhealthy_until_first_successful_poll():
    facade, _ = _make_facade([])
    cap = facade.get_capacity_info(99)
    assert cap.is_healthy is False
    assert cap.has_capacity is False
    assert cap.last_poll_at is None


def test_polling_targets_v1_peer_status_with_bearer_token():
    facade, client = _make_facade(
        [_FakeResponse(status_code=200, body=_ok_body())]
    )
    facade.poll_once(99)
    url, headers = client.requests[0]
    assert url == "https://peer.example/v1/peer/status"
    assert headers.get("Authorization") == "Bearer lg-secret"


def test_two_consecutive_successes_mark_peer_healthy():
    facade, _ = _make_facade(
        [
            _FakeResponse(status_code=200, body=_ok_body(free_slots=2)),
            _FakeResponse(status_code=200, body=_ok_body(free_slots=2)),
        ]
    )
    facade.poll_once(99)
    assert facade.is_healthy(99) is False  # first success only
    facade.poll_once(99)
    assert facade.is_healthy(99) is True

    cap = facade.get_model_capacity(model_id=12, provider_id=99)
    assert cap is not None
    assert cap.has_capacity is True
    assert cap.free_slots == 2

    status = facade.get_model_status(model_id=12, provider_id=99)
    assert status.is_loaded is True
    assert status.provider_type == "logos_peer"


def test_three_failures_open_circuit_after_being_healthy():
    facade, _ = _make_facade(
        [
            # Two successes -> healthy
            _FakeResponse(status_code=200, body=_ok_body()),
            _FakeResponse(status_code=200, body=_ok_body()),
            # Three failures -> unhealthy
            _FakeResponse(status_code=503, body={}),
            _FakeResponse(status_code=503, body={}),
            _FakeResponse(status_code=503, body={}),
        ]
    )
    facade.poll_once(99)
    facade.poll_once(99)
    assert facade.is_healthy(99) is True

    facade.poll_once(99)
    assert facade.is_healthy(99) is True  # 1 failure, not yet
    facade.poll_once(99)
    assert facade.is_healthy(99) is True  # 2 failures, threshold is 3
    facade.poll_once(99)
    assert facade.is_healthy(99) is False  # 3rd failure -> unhealthy

    # Capacity reflects unhealthy state
    cap = facade.get_model_capacity(model_id=12, provider_id=99)
    assert cap is not None
    assert cap.has_capacity is False
    assert cap.is_healthy is False
    assert cap.last_error == "HTTP 503"

    status = facade.get_model_status(model_id=12, provider_id=99)
    assert status.is_loaded is False  # circuit open masks model loaded state


def test_recovery_requires_two_consecutive_successes():
    facade, _ = _make_facade(
        [
            _FakeResponse(status_code=503, body={}),
            _FakeResponse(status_code=503, body={}),
            _FakeResponse(status_code=503, body={}),
            _FakeResponse(status_code=200, body=_ok_body()),
            _FakeResponse(status_code=200, body=_ok_body()),
        ]
    )
    # Three failures while still in initial unhealthy state -> stays unhealthy.
    for _ in range(3):
        facade.poll_once(99)
    assert facade.is_healthy(99) is False

    facade.poll_once(99)
    assert facade.is_healthy(99) is False  # 1 success of 2 needed
    facade.poll_once(99)
    assert facade.is_healthy(99) is True


def test_no_capacity_when_remote_reports_zero_free_slots():
    facade, _ = _make_facade(
        [
            _FakeResponse(status_code=200, body=_ok_body(free_slots=0, queue_depth=5)),
            _FakeResponse(status_code=200, body=_ok_body(free_slots=0, queue_depth=5)),
        ]
    )
    facade.poll_once(99)
    facade.poll_once(99)
    cap = facade.get_model_capacity(model_id=12, provider_id=99)
    assert cap is not None
    assert cap.is_healthy is True
    assert cap.has_capacity is False
    assert cap.queue_depth == 5


def test_unknown_model_returns_none_capacity():
    facade, _ = _make_facade(
        [_FakeResponse(status_code=200, body=_ok_body())]
    )
    facade.poll_once(99)
    assert facade.get_model_capacity(model_id=999, provider_id=99) is None


def test_replace_registrations_drops_stale_peer():
    facade, _ = _make_facade(
        [_FakeResponse(status_code=200, body=_ok_body())]
    )
    facade.poll_once(99)
    facade.replace_registrations([])
    assert facade.list_provider_ids() == []
    with pytest.raises(KeyError):
        facade.get_capacity_info(99)


def test_exception_during_poll_counts_as_failure():
    class _ExplodingClient:
        def get(self, *_a, **_kw):
            raise RuntimeError("boom")

        def close(self):
            pass

    facade = LogosPeerSchedulingDataFacade(
        http_client_factory=lambda: _ExplodingClient(),
        unhealthy_failure_threshold=1,
        healthy_success_threshold=1,
    )
    facade.register_model(
        model_id=1,
        provider_name="bad",
        base_url="https://bad.example",
        api_key="",
        model_name="m",
        provider_id=7,
    )
    facade.poll_once(7)
    cap = facade.get_capacity_info(7)
    assert cap.is_healthy is False
    assert cap.last_error and "RuntimeError" in cap.last_error
