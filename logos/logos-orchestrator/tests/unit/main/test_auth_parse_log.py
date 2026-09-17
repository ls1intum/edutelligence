"""auth_parse_log (#980): log insert and deployment lookup share one session.

The log row now carries request_id and timeout_s from the INSERT (no
follow-up metrics UPDATE), and the deployment lookup runs in the same
DBManager session, so the hot path checks out the pool once instead of
twice.
"""

from __future__ import annotations

import json as _json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

import logos as main


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

    def __enter__(self):
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
        return [{"model_id": 1, "provider_id": 2}]


@pytest.fixture
def _profile_auth(monkeypatch):
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
    )
    monkeypatch.setattr(main, "authenticate_api_key", lambda headers: auth)

    def fake_request_setup(headers, api_key_id, db=None):
        return (db.get_deployments_for_api_key(api_key_id), [1])

    monkeypatch.setattr(main, "request_setup", fake_request_setup)
    return db


@pytest.mark.asyncio
async def test_log_insert_carries_request_id_and_timeout(_profile_auth):
    result = await main.auth_parse_log(
        _request({"model": "m", "timeout_s": 25.5}), use_profile_auth=True, request_id="req-1"
    )

    log_id = result[4]
    assert log_id == 42
    assert _profile_auth.log_usage_kwargs["request_id"] == "req-1"
    assert _profile_auth.log_usage_kwargs["timeout_s"] == 25.5


@pytest.mark.asyncio
async def test_missing_timeout_defaults_to_none(_profile_auth):
    await main.auth_parse_log(_request({"model": "m"}), use_profile_auth=True, request_id="req-1")

    assert _profile_auth.log_usage_kwargs["timeout_s"] is None


@pytest.mark.asyncio
async def test_deployments_are_read_fresh_per_request(_profile_auth):
    """Deployment rows are permission data: one DB read per request, never
    served from the ref cache — a removed permission must not wait for a TTL
    (#980 review)."""
    _, _, _, _, _, raw_deployments = await main.auth_parse_log(
        _request({"model": "m"}), use_profile_auth=True, request_id="req-1"
    )
    assert raw_deployments == [{"model_id": 1, "provider_id": 2}]
    assert _profile_auth.deployments_calls == 1

    _, _, _, _, _, raw_deployments_again = await main.auth_parse_log(
        _request({"model": "m"}), use_profile_auth=True, request_id="req-2"
    )
    assert raw_deployments_again == [{"model_id": 1, "provider_id": 2}]
    assert _profile_auth.deployments_calls == 2  # fresh read, no cache


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
