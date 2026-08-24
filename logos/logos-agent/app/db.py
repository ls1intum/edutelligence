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
from .schemas import ACTIVE_STATUSES, EventKind, SessionStatus

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
    """Delete a workspace. Refuses while it still has non-terminal sessions."""
    async with sessionmaker()() as db:
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
) -> int:
    async with sessionmaker()() as db:
        session_id = (
            await db.execute(
                text(
                    """
                    INSERT INTO agent_sessions
                        (workspace_id, task, model, status, created_by,
                         open_pull_request, deploy_to_dev, screenshot_paths)
                    VALUES
                        (:workspace_id, :task, :model, 'queued', :created_by,
                         :open_pr, :deploy, CAST(:paths AS jsonb))
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
                },
            )
        ).scalar_one()
        await db.commit()
    return int(session_id)


_SESSION_SELECT = """
    SELECT s.id, s.workspace_id, w.name AS workspace_name, s.task, s.status,
           s.model, s.branch_name, s.pr_url, s.created_by, s.created_at,
           s.started_at, s.finished_at, s.exit_code, s.error,
           s.container_id, s.open_pull_request, s.deploy_to_dev,
           s.screenshot_paths,
           COALESCE(s.tokens_in, 0) AS tokens_in,
           COALESCE(s.tokens_out, 0) AS tokens_out,
           COALESCE(s.cost_eur, 0) AS cost_eur,
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
        "cost_eur",
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
