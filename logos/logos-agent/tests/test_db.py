"""Workspace deletion racing session creation.

The delete counts a workspace's active sessions and then deletes it, and the
create inserts a queued session. Both take the same workspace row lock first
(FOR UPDATE on the agent_workspaces row), so the race resolves one of two
ways: the delete runs first and the create fails cleanly, or the create
commits first and the delete's count sees the session and refuses. A session
that is accepted must never be cascade-deleted by a count that ran before it
existed — the fake below executes the two statement sequences against a
shared in-memory model and honours that one row lock.
"""

from __future__ import annotations

import asyncio

import pytest
from app import db

WORKSPACE = {"id": 1, "name": "feature-work"}


class _Result:
    def __init__(self, value=None, rowcount=0):
        self._value = value
        self.rowcount = rowcount

    def scalar_one(self):
        if self._value is None:
            raise LookupError("no row")
        return self._value

    def scalar_one_or_none(self):
        return self._value


class _Connection:
    """One db session over the shared model, honouring the row lock.

    The workspace row lock is what the fix adds to both transactions, so the
    fake models it as a real asyncio lock held until the transaction's
    commit or rollback.
    """

    def __init__(self, model: "_Model"):
        self.model = model
        self.holding_lock = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, *_):
        if exc_type is not None:
            await self.rollback()
        return False

    async def execute(self, sql, params=None):
        sql = str(sql).strip()
        params = params or {}
        if "FOR UPDATE" in sql and "agent_workspaces" in sql:
            workspace_id = params.get("id", params.get("workspace_id"))
            await self.model.lock.acquire()
            self.holding_lock = True
            return _Result(self.model.workspaces.get(workspace_id))
        if sql.startswith("SELECT COUNT(*) FROM agent_sessions"):
            active = {s.value for s in db.ACTIVE_STATUSES}
            count = sum(1 for s in self.model.sessions if s["workspace_id"] == params["id"] and s["status"] in active)
            return _Result(count)
        if sql.startswith("DELETE FROM agent_workspaces"):
            deleted = self.model.workspaces.pop(params["id"], None) is not None
            # The foreign key cascades: sessions lose their workspace. The
            # rowcount is the workspace rows deleted, as the statement says.
            self.model.sessions = [s for s in self.model.sessions if s["workspace_id"] != params["id"]]
            return _Result(rowcount=1 if deleted else 0)
        if sql.startswith("INSERT INTO agent_sessions"):
            session_id = max((s["id"] for s in self.model.sessions), default=0) + 1
            self.model.sessions.append({"id": session_id, "workspace_id": params["workspace_id"], "status": "queued"})
            self.model.inserted.set()
            return _Result(session_id)
        raise AssertionError(f"unexpected statement in test: {sql}")

    async def commit(self):
        # Yield so other transactions can observe the committed state, then
        # release the row lock — as Postgres does at commit.
        await asyncio.sleep(0)
        self._release()

    async def rollback(self):
        await asyncio.sleep(0)
        self._release()

    def _release(self):
        if self.holding_lock:
            self.holding_lock = False
            self.model.lock.release()


class _Model:
    def __init__(self):
        self.workspaces: dict[int, dict] = {1: dict(WORKSPACE)}
        self.sessions: list[dict] = []
        self.lock = asyncio.Lock()
        self.inserted = asyncio.Event()


def _patch_db(monkeypatch, model: _Model) -> None:
    def fake_sessionmaker():
        def factory():
            return _Connection(model)

        return factory

    monkeypatch.setattr(db, "sessionmaker", fake_sessionmaker)


def _create_kwargs() -> dict:
    return {
        "workspace_id": 1,
        "task": "a long enough task description",
        "model": None,
        "created_by": "alice",
        "open_pull_request": False,
        "deploy_to_dev": False,
        "screenshot_paths": [],
    }


async def test_a_delete_that_wins_the_race_makes_the_create_fail(monkeypatch):
    # The delete sees zero active sessions and removes the workspace,
    # cascading its sessions. A create that arrives afterwards must fail
    # cleanly at the row lock — no session row is ever written without a
    # workspace to belong to.
    model = _Model()
    _patch_db(monkeypatch, model)

    assert await db.delete_workspace(1) is True
    assert model.workspaces == {}

    with pytest.raises(ValueError, match="does not exist"):
        await db.create_session(**_create_kwargs())
    assert model.sessions == []


async def test_a_create_that_wins_the_race_keeps_its_session_from_the_delete(monkeypatch):
    # The create locks the workspace row and inserts the queued session
    # before the delete's count can run. Held between its insert and its
    # commit — exactly the window the unserialized delete used to run in —
    # the delete must then see the session and refuse, not cascade it away.
    model = _Model()
    _patch_db(monkeypatch, model)

    create = asyncio.create_task(db.create_session(**_create_kwargs()))
    await asyncio.wait_for(model.inserted.wait(), 5)

    results = await asyncio.gather(create, db.delete_workspace(1), return_exceptions=True)
    session_id, delete = results

    # The create succeeded; the delete lost to it and refused.
    assert isinstance(session_id, int)
    assert isinstance(delete, ValueError)
    assert "active session" in str(delete)
    # The accepted session survived: still queued, still in its workspace.
    assert model.sessions == [{"id": session_id, "workspace_id": 1, "status": "queued"}]
    assert model.workspaces == {1: dict(WORKSPACE)}


class TestStatementTypes:
    """Guards on typing the database cannot infer for us.

    PostgreSQL resolves a CASE over bare parameters to text, and then
    refuses to write it into an integer column. It cost a production runner
    its session limit: every attempt failed with "column max_parallel is of
    type integer but expression is of type text", for every value, and the
    unit tests could not see it because they never speak to a database.
    """

    def test_the_session_limit_is_written_as_a_number(self):
        import inspect

        source = inspect.getsource(db.set_controls)

        assert "CAST(:max_parallel AS INTEGER)" in source
        assert "CASE WHEN :clear THEN NULL ELSE :max_parallel END" not in source

    def test_the_retry_bound_is_written_as_a_number(self):
        import inspect

        source = inspect.getsource(db.handled_trigger_refs)

        assert "CAST(:attempts AS INTEGER)" in source
