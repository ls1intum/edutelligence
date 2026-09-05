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


class TestMovingInTheQueue:
    """What an operator can say about the order.

    Priority is derived from what a request is — a review outranks a fresh
    issue — and that is right most of the time. Which review is holding up a
    release is not something the rules can know.
    """

    @staticmethod
    def queue(*rows):
        """A fake database holding one queued list."""
        state = [dict(row) for row in rows]

        class _Rows:
            def __init__(self, values):
                self._values = values

            def mappings(self):
                return self

            def all(self):
                return list(self._values)

            def first(self):
                return self._values[0] if self._values else None

        class _Session:
            async def execute(self, statement, params=None):
                sql = str(statement)
                if "ORDER BY priority DESC" in sql:
                    # The production key: priority, then age, then id. A
                    # fake that ordered by id would accept a move that the
                    # database's own tie-break would undo.
                    return _Rows(
                        sorted(
                            state,
                            key=lambda row: (-row["priority"], row.get("created_at", ""), row["id"]),
                        )
                    )
                if sql.strip().startswith("UPDATE"):
                    for row in state:
                        if row["id"] == params["id"]:
                            row["priority"] = params["priority"]
                            # Mirrors the statement's CASE: the reason
                            # belongs to the row somebody moved, not to the
                            # ones renumbered around it.
                            if row["id"] == params.get("moved"):
                                row["priority_reason"] = params["reason"]
                    return _Rows([])
                return _Rows([row for row in state if row["id"] == params.get("id")])

            async def commit(self):
                return None

            async def rollback(self):
                return None

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc):
                return None

        return state, (lambda: _Session())

    @staticmethod
    def order(state):
        """The queue as the scheduler would read it."""
        return [
            row["id"] for row in sorted(state, key=lambda row: (-row["priority"], row.get("created_at", ""), row["id"]))
        ]

    async def test_moving_up_changes_the_order(self, monkeypatch):
        state, session = self.queue(
            {"id": 1, "priority": 80},
            {"id": 2, "priority": 60},
            {"id": 3, "priority": 60},
        )
        monkeypatch.setattr(db, "sessionmaker", lambda: session)

        await db.move_in_queue(3, "up", by="tobias")

        assert self.order(state) == [1, 3, 2]

    async def test_moving_to_the_front_changes_the_order(self, monkeypatch):
        state, session = self.queue({"id": 1, "priority": 80}, {"id": 2, "priority": 60})
        monkeypatch.setattr(db, "sessionmaker", lambda: session)

        await db.move_in_queue(2, "first", by="tobias")

        assert self.order(state) == [2, 1]

    async def test_moving_down_changes_the_order(self, monkeypatch):
        state, session = self.queue({"id": 1, "priority": 80}, {"id": 2, "priority": 60})
        monkeypatch.setattr(db, "sessionmaker", lambda: session)

        await db.move_in_queue(1, "down", by="tobias")

        assert self.order(state) == [2, 1]

    async def test_a_full_priority_at_the_top_is_no_obstacle(self, monkeypatch):
        # The boundary: there is nothing above 100, so nudging by one would
        # clamp, tie on age, and leave the order exactly as it was.
        state, session = self.queue({"id": 1, "priority": 100}, {"id": 2, "priority": 100})
        monkeypatch.setattr(db, "sessionmaker", lambda: session)

        await db.move_in_queue(2, "first", by="tobias")

        assert self.order(state) == [2, 1]

    async def test_the_bottom_of_the_range_is_no_obstacle_either(self, monkeypatch):
        state, session = self.queue({"id": 1, "priority": 0}, {"id": 2, "priority": 0})
        monkeypatch.setattr(db, "sessionmaker", lambda: session)

        await db.move_in_queue(1, "down", by="tobias")

        assert self.order(state) == [2, 1]

    async def test_the_last_one_cannot_go_further_down(self, monkeypatch):
        state, session = self.queue({"id": 1, "priority": 80}, {"id": 2, "priority": 60})
        monkeypatch.setattr(db, "sessionmaker", lambda: session)

        await db.move_in_queue(2, "down", by="tobias")

        assert self.order(state) == [1, 2]

    async def test_a_session_that_is_not_queued_is_not_moved(self, monkeypatch):
        _, session = self.queue({"id": 1, "priority": 80})
        monkeypatch.setattr(db, "sessionmaker", lambda: session)

        assert await db.move_in_queue(4711, "up", by="tobias") is None

    async def test_an_unknown_move_is_refused(self, monkeypatch):
        _, session = self.queue({"id": 1, "priority": 80})
        monkeypatch.setattr(db, "sessionmaker", lambda: session)

        with pytest.raises(ValueError, match="unknown move"):
            await db.move_in_queue(1, "sideways", by="tobias")

    async def test_the_reason_says_who_moved_it(self, monkeypatch):
        state, session = self.queue({"id": 1, "priority": 80}, {"id": 2, "priority": 60})
        monkeypatch.setattr(db, "sessionmaker", lambda: session)

        await db.move_in_queue(2, "first", by="tobias")

        # Only on the row that was moved: the others were renumbered to
        # keep the order, which is not a decision anybody made about them.
        moved = next(row for row in state if row["id"] == 2)
        assert "tobias" in str(moved.get("priority_reason"))
        assert not next(row for row in state if row["id"] == 1).get("priority_reason")


class TestMovingWhenAgeAndIdDisagree:
    """The queue is ordered by age among equals, not by row id.

    A fake that sorted by id would accept a move the database's own
    tie-break undoes — the rows here are deliberately numbered against
    their order in time.
    """

    async def test_a_move_holds_when_the_older_row_has_the_higher_id(self, monkeypatch):
        state, session = TestMovingInTheQueue.queue(
            {"id": 9, "priority": 60, "created_at": "2026-09-03T10:00:00"},
            {"id": 1, "priority": 60, "created_at": "2026-09-03T11:00:00"},
        )
        monkeypatch.setattr(db, "sessionmaker", lambda: session)

        # 9 is older, so it is first; moving 1 to the front has to hold
        # against that.
        assert TestMovingInTheQueue.order(state) == [9, 1]
        await db.move_in_queue(1, "first", by="tobias")

        assert TestMovingInTheQueue.order(state) == [1, 9]

    async def test_a_queue_too_long_to_order_is_refused(self, monkeypatch):
        rows = [{"id": index, "priority": 50, "created_at": f"2026-09-03T{index:02d}:00:00"} for index in range(120)]
        state, session = TestMovingInTheQueue.queue(*rows)
        monkeypatch.setattr(db, "sessionmaker", lambda: session)

        # Two rows would have to share a number, and the tie falls to age —
        # which is the thing the move is overruling.
        with pytest.raises(ValueError, match="cannot be ordered"):
            await db.move_in_queue(119, "first", by="tobias")


class TestClaimingOnOneBranch:
    """Two sessions that commit to one branch must not both be admitted.

    The row lock each claim takes covers only its own row: two claims in
    different workspaces lock different rows, and each sees the other still
    queued. What keeps them apart is the branch's advisory lock, held to
    the claim's commit — so the fake below models what Postgres models:
    row locks that skip, an advisory lock per branch, and writes that stay
    invisible to other transactions until their commit.
    """

    OCCUPYING = ("starting", "running", "paused", "finalizing")

    @staticmethod
    def _row(**fields):
        row = {"trigger_ref": None, "model": "gpt", "task": "work", "created_at": ""}
        row.update(fields)
        return row

    class _Model:
        def __init__(self, rows):
            self.sessions = {row["id"]: dict(row) for row in rows}
            self.admission_lock = asyncio.Lock()
            self.locked_rows: set[int] = set()
            self._branch_locks: dict[str, asyncio.Lock] = {}

        def branch_lock(self, branch):
            lock = self._branch_locks.get(branch)
            if lock is None:
                lock = self._branch_locks[branch] = asyncio.Lock()
            return lock

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def scalar_one_or_none(self):
            return self._rows[0] if self._rows else None

        def mappings(self):
            return self

        def all(self):
            return self._rows

        def first(self):
            return self._rows[0] if self._rows else None

    class _Transaction:
        def __init__(self, model):
            self.model = model
            self.pending: dict[int, str] = {}
            self.held_rows: list[int] = []
            self.held_advisory: list[asyncio.Lock] = []
            self.done = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, *_):
            if not self.done:
                await self.rollback()
            return False

        def status_of(self, session_id):
            return self.pending.get(session_id, self.model.sessions[session_id]["status"])

        def _startable(self, row, include_triggered):
            if self.status_of(row["id"]) != "queued":
                return False
            if not include_triggered and row.get("trigger_ref") is not None:
                return False
            branch = row.get("branch_name")
            for other in self.model.sessions.values():
                if other["id"] == row["id"] or self.status_of(other["id"]) not in TestClaimingOnOneBranch.OCCUPYING:
                    continue
                if other["workspace_id"] == row["workspace_id"]:
                    return False
                if branch is not None and other.get("branch_name") == branch:
                    return False
            return True

        def _best_of_workspace(self, row, include_triggered):
            peers = [
                peer
                for peer in self.model.sessions.values()
                if peer["workspace_id"] == row["workspace_id"]
                and self.status_of(peer["id"]) == "queued"
                and (include_triggered or peer.get("trigger_ref") is None)
            ]
            if not peers:
                return False
            best = min(peers, key=lambda peer: (-peer["priority"], peer.get("created_at", ""), peer["id"]))
            return best["id"] == row["id"]

        def _candidates(self, include_triggered):
            rows = sorted(
                self.model.sessions.values(),
                key=lambda row: (-row["priority"], row.get("created_at", ""), row["id"]),
            )
            return [
                row
                for row in rows
                if self._startable(row, include_triggered) and self._best_of_workspace(row, include_triggered)
            ]

        def _lock_row(self, row):
            # A set of ids, not an asyncio.Lock: nothing suspends while the
            # lock is held, so the lock object would only add a coroutine
            # to await — and an acquire nobody awaited would leave the row
            # unlocked, the SKIP LOCKED branch dead, and the fake claiming
            # what the database it models would refuse.
            if row["id"] in self.model.locked_rows:
                return False  # SKIP LOCKED
            self.model.locked_rows.add(row["id"])
            self.held_rows.append(row["id"])
            return True

        async def execute(self, sql, params=None):
            params = params or {}
            sql = " ".join(str(sql).split())
            # Every statement is a round trip: a yield so a concurrent
            # transaction runs in between, as the network gives it the
            # chance. Without the branch lock this is where the race lives.
            await asyncio.sleep(0)
            if sql.startswith("SELECT pg_advisory_xact_lock"):
                if "logos-agent-branch" in sql:
                    lock = self.model.branch_lock(params["branch"])
                else:
                    lock = self.model.admission_lock
                await lock.acquire()
                self.held_advisory.append(lock)
                return TestClaimingOnOneBranch._Result([1])
            if sql.startswith("SELECT s.branch_name FROM agent_sessions"):
                row = self.model.sessions.get(params["session_id"])
                return TestClaimingOnOneBranch._Result([row["branch_name"]] if row else [])
            if sql.startswith("SELECT s.id, s.branch_name FROM agent_sessions"):
                rows = self._candidates(params.get("include_triggered", True))
                if "FOR UPDATE" in sql:
                    rows = [row for row in rows if self._lock_row(row)]
                return TestClaimingOnOneBranch._Result(
                    [{"id": row["id"], "branch_name": row.get("branch_name")} for row in rows]
                )
            if sql.startswith("SELECT s.id FROM agent_sessions"):
                row = self.model.sessions.get(params["session_id"])
                if row is None or not self._lock_row(row) or not self._startable(row, True):
                    return TestClaimingOnOneBranch._Result([])
                quota = params.get("trigger_quota")
                if quota is not None and row.get("trigger_ref") is not None:
                    active = sum(
                        1
                        for other in self.model.sessions.values()
                        if other.get("trigger_ref") is not None
                        and self.status_of(other["id"]) in TestClaimingOnOneBranch.OCCUPYING
                    )
                    if active >= quota:
                        return TestClaimingOnOneBranch._Result([])
                return TestClaimingOnOneBranch._Result([row["id"]])
            if sql.startswith("UPDATE agent_sessions SET status"):
                if "ANY(:ids)" in sql:
                    for session_id in params["ids"]:
                        self.pending[session_id] = "starting"
                else:
                    self.pending[params["session_id"]] = "starting"
                return TestClaimingOnOneBranch._Result([1])
            if sql.startswith("SELECT s.id, s.workspace_id"):
                ids = params["ids"] if "ids" in params else [params["session_id"]]
                rows = []
                for session_id in ids:
                    row = dict(self.model.sessions[session_id])
                    row["status"] = self.status_of(session_id)
                    rows.append(row)
                return TestClaimingOnOneBranch._Result(rows)
            raise AssertionError(f"unexpected statement in test: {sql}")

        async def commit(self):
            # The window first: other transactions still read the old
            # state, as until the commit is durable. Then the writes
            # become visible and the locks go.
            await asyncio.sleep(0)
            for session_id, status in self.pending.items():
                self.model.sessions[session_id]["status"] = status
            self.pending.clear()
            self._release()
            await asyncio.sleep(0)

        async def rollback(self):
            self.pending.clear()
            self._release()
            await asyncio.sleep(0)

        def _release(self):
            self.done = True
            for session_id in self.held_rows:
                self.model.locked_rows.discard(session_id)
            self.held_rows.clear()
            for lock in self.held_advisory:
                if lock.locked():
                    lock.release()
            self.held_advisory.clear()

    @classmethod
    def _patch(cls, monkeypatch, model):
        monkeypatch.setattr(db, "sessionmaker", lambda: (lambda: cls._Transaction(model)))

    @classmethod
    def _branch_model(cls):
        # Two workspaces queuing on one branch, one on none: the pair is
        # what the branch rule is about, the null branch is what must keep
        # working while the pair is resolved.
        return cls._Model(
            [
                cls._row(
                    id=1,
                    workspace_id=1,
                    branch_name="feature/x",
                    status="queued",
                    priority=80,
                    created_at="2026-09-04T10:00:00",
                ),
                cls._row(
                    id=2,
                    workspace_id=2,
                    branch_name="feature/x",
                    status="queued",
                    priority=60,
                    created_at="2026-09-04T10:00:00",
                ),
                cls._row(
                    id=3,
                    workspace_id=3,
                    branch_name=None,
                    status="queued",
                    priority=50,
                    created_at="2026-09-04T10:00:00",
                ),
            ]
        )

    async def test_two_single_claims_on_one_branch_admit_exactly_one(self, monkeypatch):
        model = self._branch_model()
        self._patch(monkeypatch, model)

        results = await asyncio.gather(db.claim_session(1), db.claim_session(2))

        claimed = [row for row in results if row is not None]
        assert len(claimed) == 1
        assert claimed[0]["status"] == "starting"
        # The loser stays queued for the next pass: it refused, it was not
        # deleted.
        statuses = {model.sessions[session_id]["status"] for session_id in (1, 2)}
        assert statuses == {"queued", "starting"}

    async def test_a_batch_claim_takes_at_most_one_session_per_branch(self, monkeypatch):
        model = self._branch_model()
        self._patch(monkeypatch, model)

        claimed = await db.claim_queued_sessions(2)

        # Session 2 lost to session 1 on the branch — not to the limit,
        # which the pass filled with the branch-free session instead.
        assert {row["id"] for row in claimed} == {1, 3}
        assert model.sessions[2]["status"] == "queued"

    async def test_a_single_claim_and_a_batch_claim_on_one_branch_admit_one(self, monkeypatch):
        model = self._branch_model()
        self._patch(monkeypatch, model)

        batch, single = await asyncio.gather(db.claim_queued_sessions(2), db.claim_session(2))

        on_branch = [session_id for session_id in (1, 2) if model.sessions[session_id]["status"] == "starting"]
        assert len(on_branch) == 1
        # Whoever won the branch, nothing was claimed twice.
        taken = [row["id"] for row in batch] + ([single["id"]] if single else [])
        assert len(taken) == len(set(taken))

    async def test_two_batch_claims_on_one_branch_admit_one(self, monkeypatch):
        model = self._branch_model()
        self._patch(monkeypatch, model)

        first, second = await asyncio.gather(db.claim_queued_sessions(1), db.claim_queued_sessions(1))

        on_branch = [session_id for session_id in (1, 2) if model.sessions[session_id]["status"] == "starting"]
        assert len(on_branch) == 1
        taken = [row["id"] for row in first + second]
        assert len(taken) == len(set(taken))

    @classmethod
    def _triggered_then_manual_model(cls):
        # One workspace, one triggered row ahead of one manual one. The
        # triggered row is the workspace's most urgent queued session,
        # which is exactly what makes the comparison dangerous for the
        # manual one.
        return cls._Model(
            [
                cls._row(
                    id=1,
                    workspace_id=1,
                    branch_name=None,
                    status="queued",
                    priority=80,
                    created_at="2026-09-04T10:00:00",
                    trigger_ref="pr-1-review-1",
                ),
                cls._row(
                    id=2,
                    workspace_id=1,
                    branch_name=None,
                    status="queued",
                    priority=50,
                    created_at="2026-09-04T10:05:00",
                ),
            ]
        )

    async def test_a_manual_row_behind_a_triggered_one_is_still_claimed(self, monkeypatch):
        # A pass that may not take triggered rows must not let the
        # triggered row stand in as the workspace's best candidate either:
        # it would fail the outer predicate, every manual row behind it
        # would fail the comparison, and the workspace would go unclaimed
        # while the quota is full.
        model = self._triggered_then_manual_model()
        self._patch(monkeypatch, model)

        claimed = await db.claim_queued_sessions(2, include_triggered=False)

        assert [row["id"] for row in claimed] == [2]
        assert model.sessions[1]["status"] == "queued"

    async def test_the_triggered_row_leads_its_workspace_when_it_may(self, monkeypatch):
        # The control for the test above: with triggered rows in play the
        # most urgent one of the workspace is the one claimed, and the
        # manual one waits its turn.
        model = self._triggered_then_manual_model()
        self._patch(monkeypatch, model)

        claimed = await db.claim_queued_sessions(2)

        assert [row["id"] for row in claimed] == [1]
        assert model.sessions[2]["status"] == "queued"

    async def test_two_single_claims_on_one_row_admit_exactly_one(self, monkeypatch):
        # Two transactions locking one row: the first claim takes the row
        # lock, the second must see it locked and skip — not walk through
        # to a second UPDATE of the same session.
        model = self._Model(
            [
                self._row(
                    id=7,
                    workspace_id=1,
                    branch_name=None,
                    status="queued",
                    priority=50,
                    created_at="2026-09-04T10:00:00",
                )
            ]
        )
        self._patch(monkeypatch, model)

        results = await asyncio.gather(db.claim_session(7), db.claim_session(7))

        claimed = [row for row in results if row is not None]
        assert len(claimed) == 1
        assert claimed[0]["id"] == 7
        assert model.sessions[7]["status"] == "starting"
