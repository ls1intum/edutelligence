"""Database access for workspaces, sessions, and their event stream.

Raw SQL through SQLAlchemy's async engine, matching the orchestrator's style
(`text()` rather than the ORM query API). The tables are created by the
webservice's Liquibase changelog, not here; this module only reads and writes
them.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from .config import settings
from .schemas import ACTIVE_STATUSES, TERMINAL_STATUSES, EventKind, SessionStatus

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker | None = None


def engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url,
            pool_size=5,
            max_overflow=5,
            pool_pre_ping=True,
        )
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def sessionmaker() -> async_sessionmaker:
    engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def dispose() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- what the agent key may reach -----------------------------------------

# Which model deployments the runner's own Logos key is permitted to use, and
# what kind of provider serves each. The permission rules are the platform's,
# not this service's: the CTEs mirror the orchestrator's
# `DBManager.get_deployments_for_api_key` exactly — a key with custom
# permissions is scoped by its own grants, otherwise by its team's — so the
# runner sees the same deployments a request with that key would be routed
# to. `app/model_policy.py` turns the rows into the local-only decision;
# duplicating the rules there instead of here would put the permission logic
# two joins away from the tables it is about.
_REACHABLE_DEPLOYMENTS = """
    WITH key_info AS (
        SELECT ak.id AS aki,
               ak.team_id AS tid,
               ak.use_custom_permissions AS custom
          FROM api_keys ak
         WHERE ak.key_value = :key_value
           AND ak.is_active = true
    ),
    effective_providers AS (
        SELECT akpp.provider_id
          FROM api_key_provider_permissions akpp, key_info ki
         WHERE akpp.api_key_id = ki.aki AND ki.custom = true
        UNION
        SELECT tpp.provider_id
          FROM team_provider_permissions tpp, key_info ki
         WHERE tpp.team_id = ki.tid AND ki.custom = false
    ),
    effective_models AS (
        SELECT akmp.model_id
          FROM api_key_model_permissions akmp, key_info ki
         WHERE akmp.api_key_id = ki.aki AND ki.custom = true
        UNION
        SELECT tmp.model_id
          FROM team_model_permissions tmp, key_info ki
         WHERE tmp.team_id = ki.tid AND ki.custom = false
    )
    SELECT m.id AS model_id,
           m.name AS model_name,
           p.id AS provider_id,
           p.provider_type AS provider_type,
           (SELECT string_agg(a.alias, ',' ORDER BY a.alias)
              FROM model_aliases a
             WHERE a.model_id = m.id) AS aliases
      FROM models m
      JOIN model_provider mp ON m.id = mp.model_id
      JOIN providers p ON mp.provider_id = p.id
      JOIN effective_models em ON m.id = em.model_id
      JOIN effective_providers ep ON p.id = ep.provider_id
     ORDER BY m.name, p.id
"""


async def agent_key_exists(key_value: str) -> bool:
    """Whether the runner's Logos key is an active key of this platform.

    A key that does not resolve has no permissions to read, which is not the
    same as having none: the difference decides whether the model policy is
    'nothing reachable' or 'unknown', and only the first is safe to run on.
    """
    async with sessionmaker()() as db:
        row = (
            await db.execute(
                text("SELECT 1 FROM api_keys WHERE key_value = :key_value AND is_active = true"),
                {"key_value": key_value},
            )
        ).first()
    return row is not None


async def reachable_deployments(key_value: str) -> list[dict[str, Any]]:
    """Every model deployment the given Logos key is permitted to use."""
    async with sessionmaker()() as db:
        rows = (await db.execute(text(_REACHABLE_DEPLOYMENTS), {"key_value": key_value})).mappings().all()
    return [dict(row) for row in rows]


# --- workspaces -----------------------------------------------------------


async def create_workspace(name: str, base_branch: str, created_by: str) -> dict[str, Any]:
    volume = f"logos_agent_ws_{name}"
    async with sessionmaker()() as db:
        row = (
            (
                await db.execute(
                    text(
                        """
                    INSERT INTO agent_workspaces (name, base_branch, volume_name, created_by)
                    VALUES (:name, :base_branch, :volume, :created_by)
                    ON CONFLICT (name) DO NOTHING
                    RETURNING id, name, base_branch, volume_name, created_by, created_at
                    """
                    ),
                    {
                        "name": name,
                        "base_branch": base_branch,
                        "volume": volume,
                        "created_by": created_by,
                    },
                )
            )
            .mappings()
            .first()
        )
        await db.commit()
    if row is None:
        raise ValueError(f"workspace '{name}' already exists")
    return dict(row)


async def list_workspaces() -> list[dict[str, Any]]:
    async with sessionmaker()() as db:
        rows = (
            (
                await db.execute(
                    text(
                        """
                    SELECT w.id, w.name, w.base_branch, w.volume_name, w.created_by,
                           w.created_at,
                           COUNT(s.id) FILTER (WHERE s.status = ANY(:active)) AS active_sessions
                      FROM agent_workspaces w
                      LEFT JOIN agent_sessions s ON s.workspace_id = w.id
                     GROUP BY w.id
                     ORDER BY w.created_at DESC
                    """
                    ),
                    {"active": [s.value for s in ACTIVE_STATUSES]},
                )
            )
            .mappings()
            .all()
        )
    return [dict(r) for r in rows]


async def workspace_capacity() -> tuple[int, int]:
    """How many workspaces exist, and how many are free right now.

    A session needs a workspace of its own — two sessions in one working
    copy would write over each other — so this is what decides whether the
    runner has to create another one before queued work can start.
    """
    async with sessionmaker()() as db:
        row = (
            (
                await db.execute(
                    text(
                        """
                    SELECT COUNT(*) AS total,
                           COUNT(*) FILTER (
                               WHERE NOT EXISTS (
                                   SELECT 1 FROM agent_sessions s
                                    WHERE s.workspace_id = w.id
                                      AND s.status = ANY(:active)
                               )
                           ) AS free
                      FROM agent_workspaces w
                    """
                    ),
                    {"active": [s.value for s in ACTIVE_STATUSES]},
                )
            )
            .mappings()
            .first()
        )
    if row is None:
        return 0, 0
    return int(row["total"] or 0), int(row["free"] or 0)


async def set_workspace_base_branch(workspace_id: int, base_branch: str) -> None:
    """Point a workspace at another branch.

    The base branch is what the preparation phase resets the checkout to, so
    changing it on a workspace with no active session costs nothing but the
    next fetch. It is how a full pool can still serve a review session on a
    pull request's own branch.
    """
    async with sessionmaker()() as db:
        await db.execute(
            text("UPDATE agent_workspaces SET base_branch = :base WHERE id = :id"),
            {"id": workspace_id, "base": base_branch},
        )
        await db.commit()


async def get_workspace(workspace_id: int) -> dict[str, Any] | None:
    async with sessionmaker()() as db:
        row = (
            (
                await db.execute(
                    text("SELECT * FROM agent_workspaces WHERE id = :id"),
                    {"id": workspace_id},
                )
            )
            .mappings()
            .first()
        )
    return dict(row) if row else None


async def delete_workspace(workspace_id: int) -> bool:
    """Delete a workspace. Refuses while it still has non-terminal sessions.

    The workspace row is locked before the active count is taken, and
    :func:`create_session` takes the same lock before it inserts: the two
    are serialized on that row, so a session accepted after the count ran
    can never be cascade-deleted by it, and a delete that runs first makes
    the create fail cleanly instead.
    """
    async with sessionmaker()() as db:
        existing = (
            await db.execute(
                text("SELECT id FROM agent_workspaces WHERE id = :id FOR UPDATE"),
                {"id": workspace_id},
            )
        ).scalar_one_or_none()
        if existing is None:
            await db.rollback()
            return False
        active = (
            await db.execute(
                text(
                    """
                    SELECT COUNT(*) FROM agent_sessions
                     WHERE workspace_id = :id AND status = ANY(:active)
                    """
                ),
                {"id": workspace_id, "active": [s.value for s in ACTIVE_STATUSES]},
            )
        ).scalar_one()
        if active:
            raise ValueError(f"workspace has {active} active session(s)")
        result = await db.execute(text("DELETE FROM agent_workspaces WHERE id = :id"), {"id": workspace_id})
        await db.commit()
    return result.rowcount > 0


# --- sessions -------------------------------------------------------------


async def create_session(
    *,
    workspace_id: int,
    task: str,
    model: str | None,
    created_by: str,
    open_pull_request: bool,
    deploy_to_dev: bool,
    screenshot_paths: Sequence[str],
    trigger_kind: str | None = None,
    trigger_ref: str | None = None,
    branch: str | None = None,
    reply_target: str | None = None,
) -> int:
    async with sessionmaker()() as db:
        # Lock the workspace row before inserting. delete_workspace takes
        # the same lock before it counts active sessions and deletes, so
        # the two transactions are serialized on the row: either the delete
        # runs first (the lock select finds no row and this fails cleanly)
        # or this commit runs first (the delete's count sees the queued
        # session and refuses). A session that is accepted can never be
        # cascade-deleted by a count that ran before it existed.
        workspace = (
            await db.execute(
                text("SELECT id FROM agent_workspaces WHERE id = :workspace_id FOR UPDATE"),
                {"workspace_id": workspace_id},
            )
        ).scalar_one_or_none()
        if workspace is None:
            await db.rollback()
            raise ValueError(f"workspace {workspace_id} does not exist")
        session_id = (
            await db.execute(
                text(
                    """
                    INSERT INTO agent_sessions
                        (workspace_id, task, model, status, created_by,
                         open_pull_request, deploy_to_dev, screenshot_paths,
                         trigger_kind, trigger_ref, branch_name, reply_target)
                    VALUES
                        (:workspace_id, :task, :model, 'queued', :created_by,
                         :open_pr, :deploy, CAST(:paths AS jsonb),
                         :trigger_kind, :trigger_ref, :branch, :reply_target)
                    RETURNING id
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "task": task,
                    "model": model,
                    "created_by": created_by,
                    "open_pr": open_pull_request,
                    "deploy": deploy_to_dev,
                    "paths": json.dumps(list(screenshot_paths)),
                    "trigger_kind": trigger_kind,
                    "trigger_ref": trigger_ref,
                    # Set only when the work belongs on a branch that already
                    # exists — a review session updating the pull request it
                    # answers. Otherwise the launch derives the branch from
                    # the session id.
                    "branch": branch,
                    "reply_target": reply_target,
                },
            )
        ).scalar_one()
        await db.commit()
    return int(session_id)


async def handled_trigger_refs(refs: Sequence[str]) -> set[str]:
    """Which of these GitHub events already have a session — ever.

    Deliberately without a time window. A reference names one thing that
    happened once: an issue was assigned, a review was submitted, somebody
    asked a question. Answering it a second time a week later would be a
    duplicate pull request or a duplicate answer, not a retry — and an issue
    that simply stays assigned would produce one every week. A session that
    failed is re-queued by a person, who can see why it failed.
    """
    if not refs:
        return set()
    async with sessionmaker()() as db:
        rows = (
            await db.execute(
                text("SELECT DISTINCT trigger_ref FROM agent_sessions WHERE trigger_ref = ANY(:refs)"),
                {"refs": list(refs)},
            )
        ).all()
    return {row[0] for row in rows}


async def session_is_starting(session_id: int) -> bool:
    """Whether the row is still the 'starting' one a launch claimed.

    Narrower than reading the whole session: this is asked on the launch's
    hot path, immediately before a container is given a credential, and the
    only thing that matters there is whether the row is still ours.
    """
    async with sessionmaker()() as db:
        status = (
            await db.execute(text("SELECT status FROM agent_sessions WHERE id = :id"), {"id": session_id})
        ).scalar_one_or_none()
    return status == SessionStatus.STARTING.value


async def sessions_owing_a_reply(max_attempts: int) -> list[dict[str, Any]]:
    """Finished sessions whose answer has not reached GitHub yet.

    The reply is attempted once when a session settles; a timeout or a 5xx
    at that moment would otherwise lose it, because the trigger reference
    counts as handled and nothing looks at it again. This is what a later
    pass retries.
    """
    async with sessionmaker()() as db:
        rows = (
            (
                await db.execute(
                    text(
                        """
                    SELECT id, reply_target, reply_attempts
                      FROM agent_sessions
                     WHERE reply_target IS NOT NULL
                       AND reply_posted_at IS NULL
                       AND reply_attempts < :max_attempts
                       AND status = ANY(:terminal)
                     ORDER BY id
                     LIMIT 20
                    """
                    ),
                    {"max_attempts": max_attempts, "terminal": [s.value for s in TERMINAL_STATUSES]},
                )
            )
            .mappings()
            .all()
        )
    return [dict(row) for row in rows]


async def record_reply_attempt(session_id: int, *, delivered: bool) -> None:
    """Count an attempt, and stamp the delivery when it worked."""
    async with sessionmaker()() as db:
        await db.execute(
            text(
                """
                UPDATE agent_sessions
                   SET reply_attempts = reply_attempts + 1,
                       reply_posted_at = CASE WHEN :delivered THEN :now ELSE reply_posted_at END
                 WHERE id = :id
                """
            ),
            {"id": session_id, "delivered": delivered, "now": _now()},
        )
        await db.commit()


async def count_active_trigger_sessions() -> int:
    """Active sessions the runner queued by itself.

    The ceiling this feeds is separate from the parallel-session ceiling: a
    person asking for work must not find the queue already full of the
    runner's own ideas.
    """
    async with sessionmaker()() as db:
        count = (
            await db.execute(
                text(
                    """
                    SELECT COUNT(*) FROM agent_sessions
                     WHERE trigger_ref IS NOT NULL AND status = ANY(:active)
                    """
                ),
                {"active": [s.value for s in ACTIVE_STATUSES]},
            )
        ).scalar_one()
    return int(count or 0)


_SESSION_SELECT = """
    SELECT s.id, s.workspace_id, w.name AS workspace_name, s.task, s.status,
           s.model, s.branch_name, s.pr_url, s.created_by, s.created_at,
           s.started_at, s.finished_at, s.exit_code, s.error,
           s.container_id, s.open_pull_request, s.deploy_to_dev,
           s.screenshot_paths, s.trigger_kind, s.trigger_ref, s.reply_target,
           COALESCE(s.tokens_in, 0) AS tokens_in,
           COALESCE(s.tokens_out, 0) AS tokens_out,
           COALESCE(s.cost_usd, 0) AS cost_usd,
           (SELECT COUNT(*) FROM agent_events e
             WHERE e.session_id = s.id AND e.kind = 'screenshot') AS screenshot_count
      FROM agent_sessions s
      JOIN agent_workspaces w ON w.id = s.workspace_id
"""


async def get_session(session_id: int) -> dict[str, Any] | None:
    async with sessionmaker()() as db:
        row = (await db.execute(text(_SESSION_SELECT + " WHERE s.id = :id"), {"id": session_id})).mappings().first()
    return dict(row) if row else None


async def list_sessions(
    *, status: str | None = None, workspace_id: int | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    clauses, params = [], {"limit": limit}
    if status:
        clauses.append("s.status = :status")
        params["status"] = status
    if workspace_id is not None:
        clauses.append("s.workspace_id = :workspace_id")
        params["workspace_id"] = workspace_id
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    async with sessionmaker()() as db:
        rows = (
            (
                await db.execute(
                    text(_SESSION_SELECT + where + " ORDER BY s.created_at DESC LIMIT :limit"),
                    params,
                )
            )
            .mappings()
            .all()
        )
    return [dict(r) for r in rows]


async def claim_queued_sessions(limit: int) -> list[dict[str, Any]]:
    """Take up to `limit` startable queued sessions and mark them starting.

    A session is startable only when no other session is already occupying its
    workspace: the workspace is one working copy on one volume, so two
    concurrent sessions in it would write over each other. Parallelism comes
    from running several *workspaces*, not several sessions per workspace.

    ``FOR UPDATE SKIP LOCKED`` makes this safe to call from more than one
    replica: two schedulers never claim the same session.
    """
    if limit <= 0:
        return []
    async with sessionmaker()() as db:
        ids = (
            (
                await db.execute(
                    text(
                        """
                    SELECT s.id FROM agent_sessions s
                     WHERE s.status = 'queued'
                       AND NOT EXISTS (
                             SELECT 1 FROM agent_sessions busy
                              WHERE busy.workspace_id = s.workspace_id
                                AND busy.status = ANY(:occupying)
                           )
                       -- Only the oldest queued session of each workspace is a
                       -- candidate, so one workspace cannot take several slots
                       -- in a single pass and then collide with itself.
                       AND s.id = (
                             SELECT min(peer.id) FROM agent_sessions peer
                              WHERE peer.workspace_id = s.workspace_id
                                AND peer.status = 'queued'
                           )
                     ORDER BY s.created_at
                     LIMIT :limit
                     FOR UPDATE OF s SKIP LOCKED
                    """
                    ),
                    {
                        "limit": limit,
                        "occupying": [
                            SessionStatus.STARTING.value,
                            SessionStatus.RUNNING.value,
                            SessionStatus.PAUSED.value,
                            # The finalizer runs git in the working copy on
                            # the same volume: a new session admitted during
                            # finalization would write over it.
                            SessionStatus.FINALIZING.value,
                        ],
                    },
                )
            )
            .scalars()
            .all()
        )
        if not ids:
            await db.rollback()
            return []
        await db.execute(
            text("UPDATE agent_sessions SET status = 'starting' WHERE id = ANY(:ids)"),
            {"ids": list(ids)},
        )
        rows = (
            (await db.execute(text(_SESSION_SELECT + " WHERE s.id = ANY(:ids)"), {"ids": list(ids)})).mappings().all()
        )
        await db.commit()
    return [dict(r) for r in rows]


async def update_session(session_id: int, **fields: Any) -> None:
    """Patch a session row. Callers pass only the columns they mean to change."""
    if not fields:
        return
    allowed = {
        "status",
        "container_id",
        "branch_name",
        "pr_url",
        "started_at",
        "finished_at",
        "exit_code",
        "error",
        "tokens_in",
        "tokens_out",
        "cost_usd",
        "deployed_at",
    }
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"cannot update unknown session columns: {sorted(unknown)}")
    assignments = ", ".join(f"{k} = :{k}" for k in fields)
    params: dict[str, Any] = {**fields, "id": session_id}
    async with sessionmaker()() as db:
        await db.execute(text(f"UPDATE agent_sessions SET {assignments} WHERE id = :id"), params)
        await db.commit()


async def transition_session(session_id: int, target: SessionStatus, **fields: Any) -> bool:
    """Move a session to `target`, but only from a state that allows it.

    Returns False when the row was already in another state — the caller then
    knows a competing actor (a cancel, a crashed container) got there first.
    """
    from .schemas import can_transition  # local import keeps schemas dependency-free

    async with sessionmaker()() as db:
        current = (
            await db.execute(
                text("SELECT status FROM agent_sessions WHERE id = :id FOR UPDATE"),
                {"id": session_id},
            )
        ).scalar_one_or_none()
        if current is None:
            await db.rollback()
            return False
        if not can_transition(SessionStatus(current), target):
            await db.rollback()
            return False
        payload: dict[str, Any] = {**fields, "status": target.value, "id": session_id}
        assignments = ", ".join(f"{k} = :{k}" for k in payload if k != "id")
        await db.execute(text(f"UPDATE agent_sessions SET {assignments} WHERE id = :id"), payload)
        await db.commit()
    return True


async def count_sessions_by_status() -> dict[str, int]:
    async with sessionmaker()() as db:
        rows = (
            (await db.execute(text("SELECT status, COUNT(*) AS n FROM agent_sessions GROUP BY status")))
            .mappings()
            .all()
        )
    return {r["status"]: int(r["n"]) for r in rows}


async def sessions_in_status(status: SessionStatus) -> list[dict[str, Any]]:
    async with sessionmaker()() as db:
        rows = (
            (
                await db.execute(
                    text(_SESSION_SELECT + " WHERE s.status = :status ORDER BY s.started_at"),
                    {"status": status.value},
                )
            )
            .mappings()
            .all()
        )
    return [dict(r) for r in rows]


# --- events ---------------------------------------------------------------


async def add_event(session_id: int, kind: EventKind, payload: dict[str, Any]) -> None:
    async with sessionmaker()() as db:
        await db.execute(
            text(
                """
                INSERT INTO agent_events (session_id, kind, payload)
                VALUES (:sid, :kind, CAST(:payload AS jsonb))
                """
            ),
            {"sid": session_id, "kind": kind.value, "payload": json.dumps(payload)},
        )
        await db.commit()


async def list_events(session_id: int, *, after_id: int = 0, limit: int = 500) -> list[dict[str, Any]]:
    async with sessionmaker()() as db:
        rows = (
            (
                await db.execute(
                    text(
                        """
                    SELECT id, session_id, ts, kind, payload
                      FROM agent_events
                     WHERE session_id = :sid AND id > :after
                     ORDER BY id
                     LIMIT :limit
                    """
                    ),
                    {"sid": session_id, "after": after_id, "limit": limit},
                )
            )
            .mappings()
            .all()
        )
    return [dict(r) for r in rows]


async def ping() -> bool:
    try:
        async with sessionmaker()() as db:
            await db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
