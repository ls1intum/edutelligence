"""Short-lived Logos session keys for the agent runner."""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest
from app import capacity, session_api_keys, sessions


def test_session_key_ttl_uses_timeout_plus_margin_and_cap(monkeypatch):
    monkeypatch.setattr(
        session_api_keys,
        "settings",
        replace(
            session_api_keys.settings,
            session_timeout_s=600,
            session_api_key_ttl_margin_s=300,
            session_api_key_ttl_cap_s=86400,
        ),
    )
    assert session_api_keys.session_key_ttl_s() == 900


def test_session_key_ttl_uses_cap_when_no_session_timeout(monkeypatch):
    monkeypatch.setattr(
        session_api_keys,
        "settings",
        replace(
            session_api_keys.settings,
            session_timeout_s=0,
            session_api_key_ttl_margin_s=300,
            session_api_key_ttl_cap_s=3600,
        ),
    )
    assert session_api_keys.session_key_ttl_s() == 3600


@pytest.mark.asyncio
async def test_mint_posts_to_webservice_without_logging_key(monkeypatch, caplog):
    captured = {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "key_value": "lg-session-secret",
                    "expires_at": "2099-01-01T00:00:00Z",
                    "parent_api_key_id": 7,
                },
            )

    monkeypatch.setattr(session_api_keys.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(
        session_api_keys,
        "settings",
        replace(
            session_api_keys.settings,
            webservice_url="http://webservice:8081",
            internal_secret="secret",
            agent_api_key="lg-parent",
            session_timeout_s=100,
            session_api_key_ttl_margin_s=10,
            session_api_key_ttl_cap_s=86400,
        ),
    )

    with caplog.at_level("INFO"):
        minted = await session_api_keys.mint(session_id=9, parent_key_value="lg-parent")

    assert minted.id == 42
    assert minted.key_value == "lg-session-secret"
    assert captured["url"].endswith("/internal/session_api_keys")
    assert captured["json"]["parent_key_value"] == "lg-parent"
    assert "lg-session-secret" not in caplog.text


def test_capacity_sums_minted_key_ids_with_standing_key():
    payload = {
        "logosnode": {
            "providers": {
                "1": {
                    "models": {
                        "10": {
                            "model_name": "local-model",
                            "loaded": True,
                            "max_capacity": 10,
                            "active": 5,
                            "queue_depth": 0,
                            "queue_waiting_current": 0,
                            "active_by_api_key": {"7": 1, "42": 2},
                            "queued_by_api_key": {},
                        }
                    }
                }
            }
        },
        "queue_total": 0,
    }
    reading = capacity.parse_scheduler_state(
        payload,
        lane=frozenset({("1", "10")}),
        ours={"local-model": 1},
        own_api_key_id=7,
        own_api_key_ids=frozenset({42}),
    )
    # 5 active minus (1+2) own = 2 user busy on 10 slots → 0.2
    assert reading.ok
    assert reading.busy_slots == 2


def test_session_env_uses_minted_key_not_standing(monkeypatch):
    class _Policy:
        def resolve(self, model):
            return "local-model"

    manager = sessions.SessionManager()
    manager._session_logos_keys[1] = "lg-session-minted"
    monkeypatch.setattr(
        sessions,
        "settings",
        replace(sessions.settings, agent_api_key="lg-standing", session_model_url="http://gw"),
    )
    monkeypatch.setattr(sessions.model_policy, "current", lambda: _Policy())

    env = manager._session_env({"id": 1, "task": "t", "model": None}, "logos/agent/1")
    assert env["ANTHROPIC_AUTH_TOKEN"] == "lg-session-minted"
    assert "lg-standing" not in env.values()


@pytest.mark.asyncio
async def test_mint_failure_without_fallback_raises(monkeypatch):
    manager = sessions.SessionManager()
    monkeypatch.setattr(
        sessions,
        "settings",
        replace(
            sessions.settings,
            session_api_key_mint=True,
            session_api_key_fallback=False,
            agent_api_key="lg-parent",
            internal_secret="s",
        ),
    )

    async def boom(**kwargs):
        raise session_api_keys.SessionApiKeyError("webservice down")

    monkeypatch.setattr(sessions.session_api_keys, "mint", boom)
    with pytest.raises(session_api_keys.SessionApiKeyError):
        await manager._mint_session_logos_key(11)


@pytest.mark.asyncio
async def test_mint_failure_with_fallback_returns_none(monkeypatch):
    manager = sessions.SessionManager()
    monkeypatch.setattr(
        sessions,
        "settings",
        replace(
            sessions.settings,
            session_api_key_mint=True,
            session_api_key_fallback=True,
            agent_api_key="lg-parent",
            internal_secret="s",
        ),
    )

    async def boom(**kwargs):
        raise session_api_keys.SessionApiKeyError("webservice down")

    monkeypatch.setattr(sessions.session_api_keys, "mint", boom)
    assert await manager._mint_session_logos_key(12) is None
