"""Logos session keys for the agent runner."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import httpx
import pytest
from app import capacity, session_api_keys, sessions
from app.schemas import SessionStatus
from app.sessions import _Helper


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
        ),
    )

    with caplog.at_level("INFO"):
        minted = await session_api_keys.mint(session_id=9, parent_key_value="lg-parent")

    assert minted.id == 42
    assert minted.key_value == "lg-session-secret"
    assert minted.parent_api_key_id == 7
    assert captured["url"].endswith("/internal/session_api_keys")
    assert captured["json"]["parent_key_value"] == "lg-parent"
    assert captured["json"]["session_id"] == 9
    assert "ttl_seconds" not in captured["json"]
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
async def test_mint_does_not_separately_update_session_row(monkeypatch):
    """Association is the webservice mint transaction; the runner must not link later."""
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

    async def fake_mint(*, session_id: int, parent_key_value: str):
        return session_api_keys.MintedSessionKey(id=55, key_value="lg-session-x", parent_api_key_id=1)

    updated: list = []

    async def capture_update(sid, **fields):
        updated.append((sid, fields))

    monkeypatch.setattr(sessions.session_api_keys, "mint", fake_mint)
    monkeypatch.setattr(sessions.db, "update_session", capture_update)

    assert await manager._mint_session_logos_key(13) == "lg-session-x"
    assert manager._minted_api_key_ids == {55}
    assert updated == []


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


@pytest.mark.asyncio
async def test_janitor_revokes_orphaned_minted_keys(monkeypatch):
    manager = sessions.SessionManager()
    manager._minted_api_key_ids.add(99)
    monkeypatch.setattr(
        sessions,
        "settings",
        replace(sessions.settings, session_api_key_mint=True),
    )

    async def orphans():
        return [99, 100]

    revoked: list[int] = []

    async def capture_revoke(key_id: int) -> None:
        revoked.append(key_id)

    monkeypatch.setattr(sessions.db, "orphaned_session_api_key_ids", orphans)
    monkeypatch.setattr(sessions.session_api_keys, "revoke", capture_revoke)

    await manager._janitor_session_api_keys()

    assert revoked == [99, 100]
    assert 99 not in manager._minted_api_key_ids


@pytest.mark.asyncio
async def test_janitor_runs_when_minting_disabled_with_existing_orphan(monkeypatch):
    """Orphans minted earlier must still be revoked after minting is turned off."""
    manager = sessions.SessionManager()
    manager._minted_api_key_ids.add(77)
    monkeypatch.setattr(
        sessions,
        "settings",
        replace(sessions.settings, session_api_key_mint=False),
    )
    revoked: list[int] = []

    async def orphans():
        return [77]

    async def capture_revoke(key_id: int) -> None:
        revoked.append(key_id)

    monkeypatch.setattr(sessions.db, "orphaned_session_api_key_ids", orphans)
    monkeypatch.setattr(sessions.session_api_keys, "revoke", capture_revoke)

    await manager._janitor_session_api_keys()

    assert revoked == [77]
    assert 77 not in manager._minted_api_key_ids


@pytest.mark.asyncio
async def test_reconcile_restores_minted_key_ids_before_capacity(monkeypatch, tmp_path):
    """After a runner restart, recovered sessions' key ids must discount capacity."""
    from app.sessions import branch_for

    monkeypatch.setattr(sessions, "settings", replace(sessions.settings, artifact_root=str(tmp_path)))
    monkeypatch.setattr(sessions.os, "chown", lambda *args, **kwargs: None)

    manager = sessions.SessionManager()
    assert manager._minted_api_key_ids == set()

    running_row = {
        "id": 7,
        "workspace_name": "feature-work",
        "container_id": "cid-x",
        "branch_name": branch_for(7, "feature-work"),
        "session_api_key_id": 42,
    }
    container = {
        "Id": "cid-x",
        "Labels": {"logos.agent.session": "7", "logos.agent.managed": "true"},
        "State": "running",
    }

    async def fake_in_status(status):
        if status is SessionStatus.RUNNING:
            return [running_row]
        return []

    async def fake_list():
        return [container]

    async def fake_transition(sid, target, **fields):
        return True

    supervised: list = []

    def fake_supervise(self, sid, cid):
        supervised.append((sid, cid))

    monkeypatch.setattr(sessions.db, "sessions_in_status", fake_in_status)
    monkeypatch.setattr(sessions.docker_engine, "list_managed_containers", fake_list)
    monkeypatch.setattr(sessions.db, "transition_session", fake_transition)
    monkeypatch.setattr(sessions.SessionManager, "_supervise", fake_supervise)

    await manager._reconcile()

    assert manager._minted_api_key_ids == {42}
    assert supervised == [(7, "cid-x")]
    assert 42 in manager._own_api_key_ids()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "terminal_path",
    ["settle_success", "settle_failure", "cancel", "settle_race_loss"],
)
async def test_terminal_paths_revoke_session_key(monkeypatch, terminal_path):
    manager = sessions.SessionManager()
    manager._session_logos_keys[7] = "lg-session"
    manager._minted_api_key_ids.add(42)
    revoked: list[tuple[int, int | None]] = []

    async def capture_revoke(session_id: int, key_id: int | None = None) -> None:
        revoked.append((session_id, key_id if key_id is None else int(key_id)))
        manager._session_logos_keys.pop(session_id, None)
        if key_id is not None:
            manager._minted_api_key_ids.discard(int(key_id))

    monkeypatch.setattr(manager, "_revoke_session_logos_key", capture_revoke)

    if terminal_path == "cancel":
        session = {"id": 7, "status": "running", "session_api_key_id": 42, "container_id": None}

        async def get_session(sid):
            return session if sid == 7 else None

        async def transition_session(sid, status, **fields):
            return True

        async def add_event(*args, **kwargs):
            return None

        monkeypatch.setattr(sessions.db, "get_session", get_session)
        monkeypatch.setattr(sessions.db, "transition_session", transition_session)
        monkeypatch.setattr(sessions.db, "add_event", add_event)
        assert await manager.cancel(7) is True
        assert revoked == [(7, 42)]
        return

    session = {"id": 7, "status": "running", "session_api_key_id": 42}

    async def get_session(sid):
        return dict(session)

    async def transition_session(sid, status, **fields):
        if terminal_path == "settle_race_loss":
            return False
        session["status"] = status.value
        return True

    async def add_event(*args, **kwargs):
        return None

    async def cleanup(sid):
        return None

    monkeypatch.setattr(sessions.db, "get_session", get_session)
    monkeypatch.setattr(sessions.db, "transition_session", transition_session)
    monkeypatch.setattr(sessions.db, "add_event", add_event)
    monkeypatch.setattr(manager, "_cleanup_container", cleanup)
    monkeypatch.setattr(manager, "_read_result", lambda sid: {})
    monkeypatch.setattr(manager, "_finalize", lambda sid: _true())

    if terminal_path == "settle_success":
        await manager._settle(7, exit_code=0, error=None)
    elif terminal_path == "settle_failure":
        await manager._settle(7, exit_code=1, error="boom")
    else:
        # Non-zero exit skips finalization and races on the terminal transition.
        await manager._settle(7, exit_code=1, error="race")

    assert revoked == [(7, 42)]


@pytest.mark.asyncio
async def test_cancel_stops_helper_before_revoking_session_key(monkeypatch):
    """A slow webservice revoke must not leave the helper running after cancel."""
    manager = sessions.SessionManager()
    manager._session_logos_keys[7] = "lg-session"
    manager._minted_api_key_ids.add(42)

    helper = _Helper()
    helper.container_id = "cid-helper"
    helper.created.set()
    helper.started.set()
    manager._helpers[7] = helper

    order: list[str] = []
    revoke_started = asyncio.Event()
    revoke_release = asyncio.Event()

    async def delayed_revoke(session_id: int, key_id: int | None = None) -> None:
        order.append("revoke_start")
        revoke_started.set()
        await revoke_release.wait()
        order.append("revoke_done")
        manager._session_logos_keys.pop(session_id, None)
        if key_id is not None:
            manager._minted_api_key_ids.discard(int(key_id))

    async def fake_stop(cid, **_kwargs):
        order.append(f"stop:{cid}")

    async def fake_remove(cid, **_kwargs):
        order.append(f"remove:{cid}")

    async def get_session(sid):
        return {"id": 7, "status": "running", "session_api_key_id": 42, "container_id": None}

    async def transition_session(sid, status, **fields):
        return True

    async def add_event(*args, **kwargs):
        return None

    monkeypatch.setattr(manager, "_revoke_session_logos_key", delayed_revoke)
    monkeypatch.setattr(sessions.db, "get_session", get_session)
    monkeypatch.setattr(sessions.db, "transition_session", transition_session)
    monkeypatch.setattr(sessions.db, "add_event", add_event)
    monkeypatch.setattr(sessions.docker_engine, "stop_container", fake_stop)
    monkeypatch.setattr(sessions.docker_engine, "remove_container", fake_remove)

    cancel_task = asyncio.create_task(manager.cancel(7))
    await revoke_started.wait()
    # Helper must already be stopped before revoke awaits the webservice.
    assert order[:3] == ["stop:cid-helper", "remove:cid-helper", "revoke_start"]
    assert 7 not in manager._helpers
    revoke_release.set()
    assert await cancel_task is True
    assert order == ["stop:cid-helper", "remove:cid-helper", "revoke_start", "revoke_done"]


async def _true():
    return True
