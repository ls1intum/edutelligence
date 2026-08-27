"""Requests during a redeploy must wait for workers to reconnect.

While no worker node is connected, every logosnode deployment is filtered out
and the request 404s with "No available model deployments" — enough to kill a
running consumer mid-task. Two windows protect requests instead: the first
120 seconds after the orchestrator starts, and the 120 seconds after an
already-connected worker drops (reboot). Once a window has run out, the
request fails instantly again.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import logos as main

RAW = [{"provider_id": 7, "model_id": 42, "type": "logosnode"}]
MODEL_NAME = "qwen-27b"


class _Client:
    """Stand-in for the disconnect probe Starlette exposes on Request."""

    def __init__(self, *, leaves: bool = False):
        self._leaves = leaves
        self.probes = 0

    async def is_disconnected(self) -> bool:
        self.probes += 1
        return self._leaves


class _FakeDB:
    """Minimal stand-in for the DBManager context manager."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


@pytest.fixture(autouse=True)
def _fresh_server(monkeypatch):
    """Shrink the 120s window and pretend the orchestrator just started."""
    monkeypatch.setattr(main, "_WORKER_CONNECT_POLL_SECONDS", 0.001)
    monkeypatch.setattr(main, "_STARTUP_GRACE_PERIOD_S", 0.2)
    monkeypatch.setattr(main, "_SERVER_START_MONOTONIC", time.monotonic())


def _always_empty_filter():
    """A filter that never finds a worker; records how often it ran."""
    calls = []

    async def fake_filter(deployments, payload=None):
        calls.append(1)
        return []

    fake_filter.calls = calls
    return fake_filter


def _empty_then_raw_filter():
    """Empty on the first check (worker offline), then the worker re-attaches."""
    results = [[], RAW]

    async def fake_filter(deployments, payload=None):
        return results.pop(0) if results else deployments

    return fake_filter


def _stub_sync_path(monkeypatch, body, raw, filter_fn):
    async def fake_auth_parse_log(request, use_profile_auth=False):
        auth = MagicMock()
        auth.api_key_id = 88
        return {}, auth, body, "127.0.0.1", None

    monkeypatch.setattr(main, "auth_parse_log", fake_auth_parse_log)
    monkeypatch.setattr(main, "DBManager", _FakeDB)
    monkeypatch.setattr(main, "request_setup", lambda headers, api_key_id, db=None: (raw, [MODEL_NAME]))
    monkeypatch.setattr(main, "_filter_logosnode_deployments", filter_fn)


# ---------------------------------------------------------------------------
# _startup_grace_remaining_s / _client_timeout_s
# ---------------------------------------------------------------------------


def test_grace_window_starts_full_at_server_start():
    # The autouse fixture set the start time to "now".
    remaining = main._startup_grace_remaining_s()
    assert 0 < remaining <= main._STARTUP_GRACE_PERIOD_S


def test_grace_window_runs_out(monkeypatch):
    monkeypatch.setattr(main, "_SERVER_START_MONOTONIC", time.monotonic() - main._STARTUP_GRACE_PERIOD_S - 10)
    assert main._startup_grace_remaining_s() == 0.0


def test_late_request_only_sees_the_rest_of_the_window(monkeypatch):
    """The window is anchored to server start, not to each request."""
    elapsed = main._STARTUP_GRACE_PERIOD_S - 0.05
    monkeypatch.setattr(main, "_SERVER_START_MONOTONIC", time.monotonic() - elapsed)
    remaining = main._startup_grace_remaining_s()
    # ~0.05s left of the 0.2s window: well under half.
    assert remaining < 0.1


def test_client_timeout_parsing():
    assert main._client_timeout_s({"timeout_s": 5}) == 5.0
    assert main._client_timeout_s({"timeout_s": "10"}) == 10.0
    assert main._client_timeout_s({}) is None
    assert main._client_timeout_s({"timeout_s": None}) is None
    assert main._client_timeout_s({"timeout_s": "nope"}) is None
    assert main._client_timeout_s({"timeout_s": -3}) is None


# ---------------------------------------------------------------------------
# _wait_for_worker_connect
# ---------------------------------------------------------------------------


async def test_wait_returns_as_soon_as_a_worker_connects(monkeypatch):
    calls = []

    async def fake_filter(deployments, payload=None):
        calls.append(1)
        return [] if len(calls) < 3 else RAW

    monkeypatch.setattr(main, "_filter_logosnode_deployments", fake_filter)

    result = await main._wait_for_worker_connect(RAW, {"model": MODEL_NAME}, request=_Client())

    assert result == RAW
    assert len(calls) == 3


async def test_wait_gives_up_when_the_window_expires(monkeypatch):
    monkeypatch.setattr(main, "_filter_logosnode_deployments", _always_empty_filter())

    result = await main._wait_for_worker_connect(RAW, {"model": MODEL_NAME})

    assert result == []


async def test_no_wait_after_the_window_has_run_out(monkeypatch):
    monkeypatch.setattr(main, "_SERVER_START_MONOTONIC", time.monotonic() - main._STARTUP_GRACE_PERIOD_S - 10)
    empty = _always_empty_filter()
    monkeypatch.setattr(main, "_filter_logosnode_deployments", empty)

    result = await main._wait_for_worker_connect(RAW, {"model": MODEL_NAME})

    assert result == []
    assert empty.calls == []


async def test_late_request_only_waits_the_rest_of_the_window(monkeypatch):
    """A request arriving late must not get a fresh, full grace period."""
    empty = _always_empty_filter()
    monkeypatch.setattr(main, "_filter_logosnode_deployments", empty)
    monkeypatch.setattr(main, "_SERVER_START_MONOTONIC", time.monotonic() - (main._STARTUP_GRACE_PERIOD_S - 0.05))

    started = time.monotonic()
    result = await main._wait_for_worker_connect(RAW, {"model": MODEL_NAME})
    elapsed = time.monotonic() - started

    assert result == []
    # ~50ms left in the window: the wait must stop long before the full 0.2s.
    assert elapsed < 0.15
    assert len(empty.calls) < 100


# ---------------------------------------------------------------------------
# _worker_reconnect_grace_remaining_s (a worker that drops after startup)
# ---------------------------------------------------------------------------


def test_worker_reconnect_grace_ignores_cloud_deployments(monkeypatch):
    registry = MagicMock()
    monkeypatch.setattr(main, "_logosnode_registry", registry)
    deployments = [{"provider_id": 99, "model_id": 1, "type": "azure"}]

    assert main._worker_reconnect_grace_remaining_s(deployments) == 0.0
    registry.disconnect_grace_remaining_s.assert_not_called()


def test_worker_reconnect_grace_takes_the_freshest_drop(monkeypatch):
    registry = MagicMock()
    registry.disconnect_grace_remaining_s = lambda pid, grace: {7: 10.0, 8: 45.0}[pid]
    monkeypatch.setattr(main, "_logosnode_registry", registry)
    deployments = [
        {"provider_id": 7, "model_id": 1, "type": "logosnode"},
        {"provider_id": 8, "model_id": 1, "type": "logosnode"},
        {"provider_id": 99, "model_id": 1, "type": "azure"},
    ]

    assert main._worker_reconnect_grace_remaining_s(deployments) == 45.0


def test_worker_reconnect_grace_zero_when_nothing_dropped(monkeypatch):
    registry = MagicMock()
    registry.disconnect_grace_remaining_s = lambda pid, grace: 0.0
    monkeypatch.setattr(main, "_logosnode_registry", registry)

    assert main._worker_reconnect_grace_remaining_s(RAW) == 0.0


async def test_wait_covers_a_worker_drop_after_the_startup_window(monkeypatch):
    """A reboot of the only worker mid-service gets the same grace as a redeploy."""
    monkeypatch.setattr(main, "_SERVER_START_MONOTONIC", time.monotonic() - main._STARTUP_GRACE_PERIOD_S - 10)
    registry = MagicMock()
    registry.disconnect_grace_remaining_s = lambda pid, grace: 0.1
    monkeypatch.setattr(main, "_logosnode_registry", registry)
    monkeypatch.setattr(main, "_filter_logosnode_deployments", _empty_then_raw_filter())

    result = await main._wait_for_worker_connect(RAW, {"model": MODEL_NAME})

    assert result == RAW


async def test_wait_expires_with_the_disconnect_window(monkeypatch):
    monkeypatch.setattr(main, "_SERVER_START_MONOTONIC", time.monotonic() - main._STARTUP_GRACE_PERIOD_S - 10)
    registry = MagicMock()
    registry.disconnect_grace_remaining_s = lambda pid, grace: 0.05
    monkeypatch.setattr(main, "_logosnode_registry", registry)
    monkeypatch.setattr(main, "_filter_logosnode_deployments", _always_empty_filter())

    result = await main._wait_for_worker_connect(RAW, {"model": MODEL_NAME})

    assert result == []


async def test_no_wait_once_both_windows_are_gone(monkeypatch):
    monkeypatch.setattr(main, "_SERVER_START_MONOTONIC", time.monotonic() - main._STARTUP_GRACE_PERIOD_S - 10)
    registry = MagicMock()
    registry.disconnect_grace_remaining_s = lambda pid, grace: 0.0
    monkeypatch.setattr(main, "_logosnode_registry", registry)
    empty = _always_empty_filter()
    monkeypatch.setattr(main, "_filter_logosnode_deployments", empty)

    result = await main._wait_for_worker_connect(RAW, {"model": MODEL_NAME})

    assert result == []
    assert empty.calls == []


async def test_client_disconnect_ends_the_wait(monkeypatch):
    monkeypatch.setattr(main, "_filter_logosnode_deployments", _always_empty_filter())

    client = _Client(leaves=True)
    result = await main._wait_for_worker_connect(RAW, {"model": MODEL_NAME}, request=client)

    assert result == []
    assert client.probes >= 1


async def test_client_timeout_caps_the_grace_wait(monkeypatch):
    monkeypatch.setattr(main, "_filter_logosnode_deployments", _always_empty_filter())

    started = time.monotonic()
    result = await main._wait_for_worker_connect(RAW, {"model": MODEL_NAME}, client_timeout_s=0.05)
    elapsed = time.monotonic() - started

    assert result == []
    # The 0.2s window must not outlive the 50ms the client is willing to wait.
    assert elapsed < 0.1


# ---------------------------------------------------------------------------
# handle_sync_request
# ---------------------------------------------------------------------------


async def test_sync_request_waits_for_the_worker_to_reconnect(monkeypatch):
    """The reported failure: no worker connected for a moment during a redeploy."""
    # First check (before the wait) finds no worker; the re-check inside the
    # wait finds the worker that just re-attached.
    _stub_sync_path(monkeypatch, {"model": MODEL_NAME}, RAW, _empty_then_raw_filter())

    guarded = []

    async def fake_guard(request, **kwargs):
        guarded.append(kwargs)
        return "ok"

    monkeypatch.setattr(main, "_execute_cancelling_on_disconnect", fake_guard)

    result = await main.handle_sync_request("chat/completions", _Client())

    assert result == "ok"
    assert guarded[0]["deployments"] == RAW


async def test_sync_request_fails_after_the_window_expires(monkeypatch):
    _stub_sync_path(monkeypatch, {"model": MODEL_NAME}, RAW, _always_empty_filter())

    with pytest.raises(HTTPException) as excinfo:
        await main.handle_sync_request("chat/completions", _Client())

    assert excinfo.value.status_code == 404
    assert "No available model deployments" in excinfo.value.detail


async def test_sync_request_fails_immediately_when_the_key_has_no_deployments(monkeypatch):
    """Nothing can connect that the DB does not grant, so no waiting."""
    empty = _always_empty_filter()
    _stub_sync_path(monkeypatch, {"model": MODEL_NAME}, [], empty)

    with pytest.raises(HTTPException) as excinfo:
        await main.handle_sync_request("chat/completions", _Client())

    assert excinfo.value.status_code == 404
    # Only the initial filter ran; the grace-period loop was never entered.
    assert len(empty.calls) == 1


async def test_sync_request_fails_immediately_once_the_window_is_gone(monkeypatch):
    """After the first 120s, a missing worker is a failure, not a redeploy."""
    monkeypatch.setattr(main, "_SERVER_START_MONOTONIC", time.monotonic() - main._STARTUP_GRACE_PERIOD_S - 10)
    empty = _always_empty_filter()
    _stub_sync_path(monkeypatch, {"model": MODEL_NAME}, RAW, empty)

    with pytest.raises(HTTPException) as excinfo:
        await main.handle_sync_request("chat/completions", _Client())

    assert excinfo.value.status_code == 404
    assert len(empty.calls) == 1


# ---------------------------------------------------------------------------
# execute_proxy_job
# ---------------------------------------------------------------------------


async def test_job_waits_for_the_worker_to_reconnect(monkeypatch):
    _stub_sync_path(monkeypatch, {"model": MODEL_NAME}, RAW, _empty_then_raw_filter())

    routed = []

    async def fake_route_and_execute(**kwargs):
        routed.append(kwargs)
        return {"status_code": 200, "data": {}}

    monkeypatch.setattr(main, "route_and_execute", fake_route_and_execute)

    auth = MagicMock()
    auth.api_key_id = 88
    result = await main.execute_proxy_job("chat/completions", {}, {"model": MODEL_NAME}, "127.0.0.1", auth, None)

    assert result == {"status_code": 200, "data": {}}
    assert routed[0]["deployments"] == RAW


# ---------------------------------------------------------------------------
# LogosNodeRuntimeRegistry: a dropped session opens the reconnect window
# ---------------------------------------------------------------------------


def _registry_with_session(provider_id: int = 7):
    from logos.logosnode_registry import LogosNodeRuntimeRegistry, ProviderSession

    registry = LogosNodeRuntimeRegistry()
    registry._sessions[provider_id] = ProviderSession(
        provider_id=provider_id, worker_id="worker-1", websocket=MagicMock()
    )
    return registry


async def test_detach_records_the_drop_for_the_grace_window():
    registry = _registry_with_session()
    assert registry.disconnect_grace_remaining_s(7, 120.0) == 0.0

    await registry.detach_session(7)

    remaining = registry.disconnect_grace_remaining_s(7, 120.0)
    assert 0 < remaining <= 120.0


async def test_a_drop_longer_ago_no_longer_extends_the_window():
    registry = _registry_with_session()
    await registry.detach_session(7)
    registry._recently_disconnected[7] = time.monotonic() - 200

    assert registry.disconnect_grace_remaining_s(7, 120.0) == 0.0


async def test_a_provider_that_never_connected_has_no_window():
    registry = _registry_with_session()
    assert registry.disconnect_grace_remaining_s(99, 120.0) == 0.0
