"""Requests during a redeploy must wait for workers to reconnect.

While no worker node is connected, every logosnode deployment is filtered out
and the request 404s with "No available model deployments" — enough to kill a
running consumer mid-task, which is exactly what a redeploy used to do. The
startup grace period re-checks the filter until a worker (re)attaches or the
period expires, so the outage becomes a delay instead of a failure.
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
def _fast_polling(monkeypatch):
    monkeypatch.setattr(main, "_WORKER_CONNECT_POLL_SECONDS", 0.001)


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
# _startup_grace_period_s / _client_timeout_s
# ---------------------------------------------------------------------------


def test_grace_period_env_parsing(monkeypatch):
    monkeypatch.delenv(main._STARTUP_GRACE_PERIOD_ENV, raising=False)
    assert main._startup_grace_period_s() == main._DEFAULT_STARTUP_GRACE_PERIOD_S

    monkeypatch.setenv(main._STARTUP_GRACE_PERIOD_ENV, "0")
    assert main._startup_grace_period_s() == 0.0

    monkeypatch.setenv(main._STARTUP_GRACE_PERIOD_ENV, "30")
    assert main._startup_grace_period_s() == 30.0

    monkeypatch.setenv(main._STARTUP_GRACE_PERIOD_ENV, "-5")
    assert main._startup_grace_period_s() == 0.0

    monkeypatch.setenv(main._STARTUP_GRACE_PERIOD_ENV, "garbage")
    assert main._startup_grace_period_s() == main._DEFAULT_STARTUP_GRACE_PERIOD_S


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
    monkeypatch.setenv(main._STARTUP_GRACE_PERIOD_ENV, "5")
    calls = []

    async def fake_filter(deployments, payload=None):
        calls.append(1)
        return [] if len(calls) < 3 else RAW

    monkeypatch.setattr(main, "_filter_logosnode_deployments", fake_filter)

    result = await main._wait_for_worker_connect(RAW, {"model": MODEL_NAME}, request=_Client())

    assert result == RAW
    assert len(calls) == 3


async def test_wait_gives_up_when_the_grace_period_expires(monkeypatch):
    monkeypatch.setenv(main._STARTUP_GRACE_PERIOD_ENV, "0.05")
    monkeypatch.setattr(main, "_filter_logosnode_deployments", _always_empty_filter())

    result = await main._wait_for_worker_connect(RAW, {"model": MODEL_NAME})

    assert result == []


async def test_zero_grace_period_never_polls(monkeypatch):
    monkeypatch.setenv(main._STARTUP_GRACE_PERIOD_ENV, "0")
    empty = _always_empty_filter()
    monkeypatch.setattr(main, "_filter_logosnode_deployments", empty)

    result = await main._wait_for_worker_connect(RAW, {"model": MODEL_NAME})

    assert result == []
    assert empty.calls == []


async def test_client_disconnect_ends_the_wait(monkeypatch):
    monkeypatch.setenv(main._STARTUP_GRACE_PERIOD_ENV, "5")
    monkeypatch.setattr(main, "_filter_logosnode_deployments", _always_empty_filter())

    client = _Client(leaves=True)
    result = await main._wait_for_worker_connect(RAW, {"model": MODEL_NAME}, request=client)

    assert result == []
    assert client.probes >= 1


async def test_client_timeout_caps_the_grace_wait(monkeypatch):
    monkeypatch.setenv(main._STARTUP_GRACE_PERIOD_ENV, "60")
    monkeypatch.setattr(main, "_filter_logosnode_deployments", _always_empty_filter())

    started = time.monotonic()
    result = await main._wait_for_worker_connect(RAW, {"model": MODEL_NAME}, client_timeout_s=0.05)
    elapsed = time.monotonic() - started

    assert result == []
    # The 60s grace period must not outlive the 50ms the client is willing to wait.
    assert elapsed < 5.0


# ---------------------------------------------------------------------------
# handle_sync_request
# ---------------------------------------------------------------------------


async def test_sync_request_waits_for_the_worker_to_reconnect(monkeypatch):
    """The reported failure: no worker connected for a moment during a redeploy."""
    monkeypatch.setenv(main._STARTUP_GRACE_PERIOD_ENV, "5")
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


async def test_sync_request_fails_after_the_grace_period(monkeypatch):
    monkeypatch.setenv(main._STARTUP_GRACE_PERIOD_ENV, "0.05")
    _stub_sync_path(monkeypatch, {"model": MODEL_NAME}, RAW, _always_empty_filter())

    with pytest.raises(HTTPException) as excinfo:
        await main.handle_sync_request("chat/completions", _Client())

    assert excinfo.value.status_code == 404
    assert "No available model deployments" in excinfo.value.detail


async def test_sync_request_fails_immediately_when_the_key_has_no_deployments(monkeypatch):
    """Nothing can connect that the DB does not grant, so no waiting."""
    monkeypatch.setenv(main._STARTUP_GRACE_PERIOD_ENV, "5")
    empty = _always_empty_filter()
    _stub_sync_path(monkeypatch, {"model": MODEL_NAME}, [], empty)

    with pytest.raises(HTTPException) as excinfo:
        await main.handle_sync_request("chat/completions", _Client())

    assert excinfo.value.status_code == 404
    # Only the initial filter ran; the grace-period loop was never entered.
    assert len(empty.calls) == 1


# ---------------------------------------------------------------------------
# execute_proxy_job
# ---------------------------------------------------------------------------


async def test_job_waits_for_the_worker_to_reconnect(monkeypatch):
    monkeypatch.setenv(main._STARTUP_GRACE_PERIOD_ENV, "5")
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
