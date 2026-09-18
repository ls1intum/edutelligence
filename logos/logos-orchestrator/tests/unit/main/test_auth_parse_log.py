"""auth_parse_log (#980): log insert, deployment lookup, and proxy-mode
model resolution share one session.

The log row carries request_id and timeout_s from the INSERT (no follow-up
metrics UPDATE), and the deployment lookup — plus, when the body names a
model, the proxy-mode resolution that the auth context carries to
_execute_proxy_mode — runs in the same DBManager session, so the hot path
check
s out the pool once for all of it.

Resolution routing (#980 O17): non-admin keys resolve in memory over the
deployment rows just fetched (same row set as the SQL non-admin branch —
same permission CTEs), so the DB resolver is never called; admin keys keep
the SQL query, whose bypass sees every model, not just the permitted set.
"""

from __future__ import annotations

import json as _json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

import logos as main

_DEPLOYMENT_ROW = {"model_id": 1, "provider_id": 2, "model_name": "m", "aliases": None}


def _request(body: dict) -> Request:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/chat/completions",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 1234),
            "server": ("logos.test", 80),
            "scheme": "http",
        }
    )
    request.json = AsyncMock(return_value=body)
    return request


class _RecordingDB:
    def __init__(self):
        self.log_usage_kwargs = None
        self.deployments_calls = 0
        self.resolve_calls = 0
        # The DBManager context is entered exactly once per request: the log
        # insert, the deployment lookup, and (for admin keys) the proxy-mode
        # resolution must all run inside that single checkout.
        self.entries = 0

    def __enter__(self):
        self.entries += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get_team(self, team_id):
        return None

    def log_usage(self, **kwargs):
        self.log_usage_kwargs = kwargs
        return {"log-id": 42}, 200

    def get_deployments_for_api_key(self, api_key_id):
        self.deployments_calls += 1
        return [_DEPLOYMENT_ROW]

    def resolve_proxy_model(self, api_key_id, requested_name):
        self.resolve_calls += 1
        return (7, requested_name)


@pytest.fixture
def _profile_auth(monkeypatch):
    def _install(role=None):
        db = _RecordingDB()
        monkeypatch.setattr(main, "DBManager", lambda: db)

        auth = SimpleNamespace(
            key_value="lg-test",
            api_key_id=7,
            team_id=None,
            user_id=None,
            environment="test",
            log_level="BILLING",
            settings={},
            resolved_proxy_model=None,
            role=role,
        )
        monkeypatch.setattr(main, "authenticate_api_key", lambda headers: auth)

        def fake_request_setup(headers, api_key_id, db=None):
            return (db.get_deployments_for_api_key(api_key_id), [1])

        monkeypatch.setattr(main, "request_setup", fake_request_setup)
        return db, auth

    return _install


@pytest.mark.asyncio
async def test_log_insert_carries_request_id_and_timeout(_profile_auth):
    db, _ = _profile_auth()
    result = await main.auth_parse_log(
        _request({"model": "m", "timeout_s": 25.5}), use_profile_auth=True, request_id="req-1"
    )

    log_id = result[4]
    assert log_id == 42
    assert db.log_usage_kwargs["request_id"] == "req-1"
    assert db.log_usage_kwargs["timeout_s"] == 25.5


@pytest.mark.asyncio
async def test_missing_timeout_defaults_to_none(_profile_auth):
    db, _ = _profile_auth()
    await main.auth_parse_log(_request({"model": "m"}), use_profile_auth=True, request_id="req-1")

    assert db.log_usage_kwargs["timeout_s"] is None


@pytest.mark.asyncio
async def test_deployments_are_read_fresh_per_request(_profile_auth):
    """Deployment rows are permission data: one DB read per request, never
    served from the ref cache — a removed permission must not wait for a TTL
    (#980 review)."""
    db, _ = _profile_auth()
    _, _, _, _, _, raw_deployments = await main.auth_parse_log(
        _request({"model": "m"}), use_profile_auth=True, request_id="req-1"
    )
    assert raw_deployments == [_DEPLOYMENT_ROW]
    assert db.deployments_calls == 1

    _, _, _, _, _, raw_deployments_again = await main.auth_parse_log(
        _request({"model": "m"}), use_profile_auth=True, request_id="req-2"
    )
    assert raw_deployments_again == [_DEPLOYMENT_ROW]
    assert db.deployments_calls == 2  # fresh read, no cache


@pytest.mark.asyncio
async def test_non_admin_resolution_is_in_memory_over_the_fetched_rows(_profile_auth):
    """Non-admin keys resolve over the deployment rows fetched in the same
    session (#980 O17): same row set as the SQL non-admin branch, so the DB
    resolver is never called and one checkout serves log + deployments +
    resolution."""
    db, auth = _profile_auth(role="developer")
    headers, _, body, client_ip, log_id, _ = await main.auth_parse_log(
        _request({"model": "m"}), use_profile_auth=True, request_id="req-1"
    )

    assert log_id == 42
    assert db.deployments_calls == 1
    assert db.resolve_calls == 0  # in-memory twin, no SQL round-trip
    assert auth.resolved_proxy_model == (1, "m")
    # One checkout served the log insert, the deployments, and the resolve.
    assert db.entries == 1


@pytest.mark.asyncio
async def test_admin_key_keeps_sql_resolution(_profile_auth):
    """Admin keys must keep the SQL resolver: its bypass sees every model,
    while the deployment rows carry only the permitted set (#980 O17)."""
    db, auth = _profile_auth(role="logos_admin")
    _, _, _, _, _, _ = await main.auth_parse_log(_request({"model": "m"}), use_profile_auth=True, request_id="req-1")

    assert db.resolve_calls == 1
    assert auth.resolved_proxy_model == (7, "m")
    assert db.entries == 1


@pytest.mark.asyncio
async def test_app_admin_key_keeps_sql_resolution(_profile_auth):
    db, auth = _profile_auth(role="app_admin")
    await main.auth_parse_log(_request({"model": "m"}), use_profile_auth=True, request_id="req-1")

    assert db.resolve_calls == 1
    assert auth.resolved_proxy_model == (7, "m")


@pytest.mark.asyncio
async def test_null_role_routes_to_in_memory_resolution(_profile_auth):
    """A key with no user row (role NULL) is a non-admin: in-memory
    resolution, matching what the SQL branch computes for it."""
    db, auth = _profile_auth(role=None)
    await main.auth_parse_log(_request({"model": "m"}), use_profile_auth=True, request_id="req-1")

    assert db.resolve_calls == 0
    assert auth.resolved_proxy_model == (1, "m")


@pytest.mark.asyncio
async def test_body_without_model_does_not_resolve(_profile_auth):
    """Resource-mode bodies (no 'model' key) skip the resolution entirely."""
    db, auth = _profile_auth()
    await main.auth_parse_log(
        _request({"messages": [{"role": "user", "content": "hi"}]}), use_profile_auth=True, request_id="req-1"
    )

    assert db.resolve_calls == 0
    assert auth.resolved_proxy_model is None


@pytest.mark.asyncio
async def test_non_profile_path_returns_six_element_tuple(monkeypatch):
    result = await main.auth_parse_log(_request({"model": "m"}), use_profile_auth=False)

    assert result == ({}, None, {"model": "m"}, "127.0.0.1", None, [])


@pytest.mark.asyncio
async def test_bad_json_is_rejected_before_any_db_access(monkeypatch):
    request = _request({})
    request.json = AsyncMock(side_effect=_json.JSONDecodeError("bad", "doc", 0))

    def _no_db():
        raise AssertionError("no db access expected for a parse error")

    monkeypatch.setattr(main, "DBManager", _no_db)
    # Auth runs before body parsing; stub it so the 400 comes from the parse.
    monkeypatch.setattr(main, "authenticate_api_key", lambda headers: SimpleNamespace(settings={}))

    with pytest.raises(main.HTTPException) as exc:
        await main.auth_parse_log(request, use_profile_auth=True, request_id="req-1")

    assert exc.value.status_code == 400
