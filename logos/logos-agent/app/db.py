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

from . import pulse
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


class Unchanged:
    """ "Leave this alone", as a value.

    Null already means something here — "clear the override" — so a half
    nobody touched cannot be expressed as null, and a default of null would
    quietly reset it.
    """

    __slots__ = ()


UNCHANGED = Unchanged()


async def get_instructions() -> dict[str, Any] | None:
    """The standing instructions, or None when the row is missing."""
    async with sessionmaker()() as db:
        row = (
            (
                await db.execute(
                    text(
                        """
                        SELECT house_rules, environment_notes, updated_by, updated_at
                          FROM agent_instructions WHERE id = 1
                        """
                    )
                )
            )
            .mappings()
            .first()
        )
    return dict(row) if row else None


async def set_instructions(
    *,
    house_rules: str | None | Unchanged = UNCHANGED,
    environment_notes: str | None | Unchanged = UNCHANGED,
    updated_by: str,
) -> None:
    """Store the standing instructions.

    Three things can be meant about a half, and they are all different:
    text replaces it, null clears the override back to what the code ships
    with, and `UNCHANGED` leaves what is stored alone. The last one is why
    the write is per-half — resetting the house rules must not save
    whatever happens to be sitting in the other box on somebody's screen.
    """
    async with sessionmaker()() as db:
        await db.execute(
            text(
                """
                INSERT INTO agent_instructions (id, house_rules, environment_notes, updated_by, updated_at)
                VALUES (1, :house_rules, :environment_notes, :updated_by, :now)
                ON CONFLICT (id) DO UPDATE SET
                    house_rules = CASE WHEN :write_house
                        THEN :house_rules ELSE agent_instructions.house_rules END,
                    environment_notes = CASE WHEN :write_notes
                        THEN :environment_notes ELSE agent_instructions.environment_notes END,
                    updated_by = :updated_by,
                    updated_at = :now
                """
            ),
            {
                # There is no row to keep on the insert path, so an untouched
                # half starts out as no override at all.
                "house_rules": None if isinstance(house_rules, Unchanged) else house_rules,
                "environment_notes": None if isinstance(environment_notes, Unchanged) else environment_notes,
                "write_house": not isinstance(house_rules, Unchanged),
                "write_notes": not isinstance(environment_notes, Unchanged),
                "updated_by": updated_by,
                "now": _now(),
            },
        )
        await db.commit()


# --- what an operator changed while the runner was running ----------------


async def get_controls() -> dict[str, Any] | None:
    """The one row of runtime controls, or None if it is missing."""
    async with sessionmaker()() as db:
        row = (
            (
                await db.execute(
                    text(
                        """
                    SELECT mode, mode_reason, max_parallel, comments_scanned_at,
                           updated_by, updated_at
                      FROM agent_controls WHERE id = 1
                    """
                    )
                )
            )
            .mappings()
            .first()
        )
    return dict(row) if row else None


async def set_controls(
    *,
    mode: str | None = None,
    mode_reason: str | None = None,
    max_parallel: int | None = None,
    clear_max_parallel: bool = False,
    updated_by: str,
) -> None:
    """Change the runtime controls, leaving untouched what was not named.

    ``clear_max_parallel`` is how the override goes back to "whatever the
    environment configured": null is a value here, not an absence, so it
    cannot be expressed by omitting the argument.
    """
    async with sessionmaker()() as db:
        await db.execute(
            text(
                """
                INSERT INTO agent_controls (id, mode, mode_reason, max_parallel, updated_by, updated_at)
                VALUES (1, COALESCE(:mode, 'running'), :mode_reason,
                        CASE WHEN CAST(:clear AS BOOLEAN) THEN NULL
                             ELSE CAST(:max_parallel AS INTEGER) END,
                        :updated_by, :now)
                ON CONFLICT (id) DO UPDATE SET
                    mode = COALESCE(:mode, agent_controls.mode),
                    mode_reason = CASE
                        WHEN :mode IS NULL THEN agent_controls.mode_reason
                        ELSE :mode_reason
                    END,
                    -- The casts are not decoration: both branches of a CASE
                    -- over bare parameters are untyped, so PostgreSQL
                    -- resolves the whole expression to text and refuses to
                    -- write it into an integer column. Without them this
                    -- statement fails for every value, including the ones
                    -- that look obviously fine.
                    max_parallel = CASE
                        WHEN CAST(:clear AS BOOLEAN) THEN NULL
                        WHEN CAST(:max_parallel AS INTEGER) IS NULL THEN agent_controls.max_parallel
                        ELSE CAST(:max_parallel AS INTEGER)
                    END,
                    updated_by = :updated_by,
                    updated_at = :now
                """
            ),
            {
                "mode": mode,
                "mode_reason": mode_reason,
                "max_parallel": max_parallel,
                "clear": clear_max_parallel,
                "updated_by": updated_by,
                "now": _now(),
            },
        )
        await db.commit()


# --- workspaces -----------------------------------------------------------


async def create_workspace(name: str, base_branch: str, created_by: str, *, ephemeral: bool = False) -> dict[str, Any]:
    volume = f"logos_agent_ws_{name}"
    async with sessionmaker()() as db:
        row = (
            (
                await db.execute(
                    text(
                        """
                    INSERT INTO agent_workspaces
                        (name, base_branch, volume_name, created_by, ephemeral)
                    VALUES (:name, :base_branch, :volume, :created_by, :ephemeral)
                    -- An archived workspace of the same name is revived
                    -- rather than collided with: the name identifies the
                    -- work (an issue, a pull request), and its history is
                    -- worth keeping across the gap. A live one is left
                    -- alone, which is what makes the name unique.
                    ON CONFLICT (name) DO UPDATE
                       SET archived_at = NULL,
                           base_branch = EXCLUDED.base_branch,
                           ephemeral = EXCLUDED.ephemeral
                     WHERE agent_workspaces.archived_at IS NOT NULL
                    RETURNING id, name, base_branch, volume_name, created_by,
                              created_at, ephemeral
                    """
                    ),
                    {
                        "name": name,
                        "base_branch": base_branch,
                        "volume": volume,
                        "created_by": created_by,
                        "ephemeral": ephemeral,
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
                           w.created_at, w.ephemeral,
                           COUNT(s.id) FILTER (WHERE s.status = ANY(:active)) AS active_sessions
                      FROM agent_workspaces w
                      LEFT JOIN agent_sessions s ON s.workspace_id = w.id
                     WHERE w.archived_at IS NULL
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


async def comments_scanned_at() -> datetime | None:
    """How far the comment scan has got, across restarts."""
    async with sessionmaker()() as db:
        return (
            await db.execute(text("SELECT comments_scanned_at FROM agent_controls WHERE id = 1"))
        ).scalar_one_or_none()


async def mark_comments_scanned(moment: datetime) -> None:
    """Remember that comments up to this point have been dealt with."""
    async with sessionmaker()() as db:
        await db.execute(
            text(
                """
                INSERT INTO agent_controls (id, comments_scanned_at, updated_at)
                VALUES (1, :moment, :now)
                ON CONFLICT (id) DO UPDATE SET comments_scanned_at = :moment
                """
            ),
            {"moment": moment, "now": _now()},
        )
        await db.commit()


async def disposable_workspaces(idle_before: datetime) -> list[dict[str, Any]]:
    """Ephemeral workspaces whose work is done and whose volume can go.

    A workspace the runner made for one piece of triggered work has no
    meaning once that work has finished, and left behind they fill the
    parallel ceiling with checkouts nobody is using. An operator's
    workspace is never in this list: they made it, they keep it.

    Idle is measured from when the last session in it *finished*, not from
    when the workspace was created — a workspace made an hour ago whose
    session ended a minute ago is not idle. A workspace that never ran
    anything falls back to its creation time, which also covers the gap
    between a session being queued into a fresh workspace and being
    claimed: neither is active yet, and sweeping then would delete the
    working copy out from under the session it was made for.
    """
    async with sessionmaker()() as db:
        rows = (
            (
                await db.execute(
                    text(
                        """
                    SELECT w.id, w.name, w.volume_name
                      FROM agent_workspaces w
                     WHERE w.ephemeral = TRUE
                       AND w.archived_at IS NULL
                       AND NOT EXISTS (
                             SELECT 1 FROM agent_sessions s
                              WHERE s.workspace_id = w.id
                                AND s.status = ANY(:active)
                           )
                       AND COALESCE(
                             (SELECT MAX(s.finished_at) FROM agent_sessions s
                               WHERE s.workspace_id = w.id),
                             w.created_at
                           ) < :idle_before
                     ORDER BY w.id
                    """
                    ),
                    {"idle_before": idle_before, "active": [s.value for s in ACTIVE_STATUSES]},
                )
            )
            .mappings()
            .all()
        )
    return [dict(row) for row in rows]


async def archive_workspace(workspace_id: int) -> bool:
    """Retire a workspace without deleting anything that happened in it.

    The row stays: `agent_sessions.workspace_id` cascades, so deleting it
    would take every finished session in it — their events, their trigger
    references, their pending replies — and with the references gone, work
    that is still assigned would be queued all over again. Archiving keeps
    the history and the name while giving back the only thing worth
    reclaiming, which is the volume.

    Refuses while the workspace is occupied, under the same row lock
    :func:`create_session` takes, so a session accepted a moment ago is
    never archived out from under itself.
    """
    async with sessionmaker()() as db:
        existing = (
            await db.execute(
                text("SELECT id FROM agent_workspaces WHERE id = :id AND archived_at IS NULL FOR UPDATE"),
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
            await db.rollback()
            return False
        await db.execute(
            text("UPDATE agent_workspaces SET archived_at = :now WHERE id = :id"),
            {"id": workspace_id, "now": _now()},
        )
        await db.commit()
    return True


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
    no_push: bool = False,
    trigger_kind: str | None = None,
    trigger_ref: str | None = None,
    branch: str | None = None,
    reply_target: str | None = None,
    reaction_target: str | None = None,
    priority: int = 50,
    priority_reason: str | None = None,
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
                         no_push, trigger_kind, trigger_ref, branch_name,
                         reply_target, reaction_target, priority, priority_reason)
                    VALUES
                        (:workspace_id, :task, :model, 'queued', :created_by,
                         :open_pr, :deploy, CAST(:paths AS jsonb),
                         :no_push, :trigger_kind, :trigger_ref, :branch,
                         :reply_target,
                         :reaction_target,
                         :priority, :priority_reason)
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
                    # Set only for the sessions that answer from a checkout
                    # they may not write to: the finalizer is told by the
                    # row, not by the task text, to leave the remote alone.
                    "no_push": no_push,
                    "trigger_kind": trigger_kind,
                    "trigger_ref": trigger_ref,
                    # Set only when the work belongs on a branch that already
                    # exists — a review session updating the pull request it
                    # answers. Otherwise the launch derives the branch from
                    # the session id.
                    "branch": branch,
                    "reply_target": reply_target,
                    "reaction_target": reaction_target,
                    "priority": priority,
                    "priority_reason": priority_reason,
                },
            )
        ).scalar_one()
        await db.commit()
    return int(session_id)


# How often a trigger may be taken up again after a session that never got
# as far as running. Enough to survive a host that is missing an image or a
# Docker daemon that was restarting; few enough that a request which cannot
# be launched at all stops being retried and is left to a person.
LAUNCH_ATTEMPTS = 3


async def handled_trigger_refs(refs: Sequence[str]) -> set[str]:
    """Which of these GitHub events are dealt with — ever.

    Deliberately without a time window. A reference names one thing that
    happened once: an issue was assigned, a review was submitted, somebody
    asked a question. Answering it a second time a week later would be a
    duplicate pull request or a duplicate answer, not a retry — and an issue
    that simply stays assigned would produce one every week.

    With one exception, learned in production: a session that failed *before
    its agent ever started* did no work and answered nothing, and must not
    consume the request. A host missing the session image failed sixteen
    launches in as many seconds, and every one of those assignments and
    questions was then permanently invisible to the poller — the only way
    back was editing the database by hand. Such a request is taken up again,
    at most ``LAUNCH_ATTEMPTS`` times, so a launch that can never work stops
    rather than loops.
    """
    if not refs:
        return set()
    async with sessionmaker()() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT trigger_ref
                      FROM agent_sessions
                     WHERE trigger_ref = ANY(:refs)
                     GROUP BY trigger_ref
                    HAVING bool_or(status <> 'failed' OR started_at IS NOT NULL)
                        OR count(*) >= CAST(:attempts AS INTEGER)
                    """
                ),
                {"refs": list(refs), "attempts": LAUNCH_ATTEMPTS},
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


async def last_session_branch(workspace_id: int, *, before_session_id: int) -> str | None:
    """The branch the previous session in this workspace worked on.

    What decides whether the next session continues that conversation or
    starts a new one: the same branch is the same piece of work — an issue
    that became a pull request, and every review round after it.
    """
    async with sessionmaker()() as db:
        return (
            await db.execute(
                text(
                    """
                    SELECT branch_name
                      FROM agent_sessions
                     WHERE workspace_id = :workspace_id
                       AND id < :session_id
                       AND branch_name IS NOT NULL
                     ORDER BY id DESC
                     LIMIT 1
                    """
                ),
                {"workspace_id": workspace_id, "session_id": before_session_id},
            )
        ).scalar_one_or_none()


async def update_session_usage(session_id: int, *, tokens_in: int, tokens_out: int) -> None:
    """Record what a running session has spent so far.

    Only ever upwards: the counters are a running total, and a batch of
    output that arrives out of order must not make the number go backwards.
    Settlement overwrites both with the authoritative totals from the
    result file.
    """
    async with sessionmaker()() as db:
        await db.execute(
            text(
                """
                UPDATE agent_sessions
                   SET tokens_in = GREATEST(COALESCE(tokens_in, 0), CAST(:tokens_in AS INTEGER)),
                       tokens_out = GREATEST(COALESCE(tokens_out, 0), CAST(:tokens_out AS INTEGER))
                 WHERE id = :id
                """
            ),
            {"id": session_id, "tokens_in": tokens_in, "tokens_out": tokens_out},
        )
        await db.commit()


async def abandon_reply(session_id: int, *, attempts: int) -> None:
    """Stop owing an answer that can never be written.

    A settled session's artefacts are final: if it wrote no answer, no later
    pass will find one. Without this the sweep asks again every few seconds
    for the life of the deployment. The target stays on the row for the
    record; only the sweep lets go.
    """
    async with sessionmaker()() as db:
        await db.execute(
            text("UPDATE agent_sessions SET reply_attempts = GREATEST(reply_attempts, :attempts) WHERE id = :id"),
            {"id": session_id, "attempts": attempts},
        )
        await db.commit()


async def count_active_trigger_sessions() -> int:
    """Self-queued sessions that are occupying capacity right now.

    Queued ones are deliberately not counted. The ceiling this feeds is
    about how much of the platform the automation may be *using*, and a
    queued session uses nothing — it is a piece of work waiting its turn,
    which is what a queue is for and what the page shows. Counting the
    queue against the ceiling meant the runner refused to write down work
    it had already found, so nothing was ever waiting: the backlog lived in
    the repository, invisible.
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
                {"active": [s.value for s in ACTIVE_STATUSES if s is not SessionStatus.QUEUED]},
            )
        ).scalar_one()
    return int(count or 0)


_SESSION_SELECT = """
    SELECT s.id, s.workspace_id, w.name AS workspace_name, s.task, s.status,
           s.model, s.branch_name, s.pr_url, s.created_by, s.created_at,
           s.started_at, s.finished_at, s.exit_code, s.error,
           s.container_id, s.open_pull_request, s.deploy_to_dev,
           s.screenshot_paths, s.no_push, s.trigger_kind, s.trigger_ref,
           s.reply_target, s.reaction_target,
           s.priority, s.priority_reason, s.environment_notes,
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


# How long a queue can still be put in an exact order using the priority
# column alone. Beyond it two rows must share a number, and the tie falls to
# age — which is what a move overrules, so the move would not hold.
_ORDERABLE = 100


def _renumbered(order: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Priorities that put this list in exactly this order.

    Spread across the range the column allows rather than nudged by one:
    a queue whose top row is already at the maximum has no room above it,
    and a move that cannot change the order is a move that did not happen.
    Only rows whose number actually changes are written.
    """
    count = len(order)
    if count == 0:
        return []
    if count > _ORDERABLE:
        # More rows than the column has distinct values: two of them would
        # share a number and the tie would fall to age, which is the very
        # thing a move is trying to overrule. The caller refuses instead of
        # pretending.
        raise ValueError(f"a queue of {count} cannot be ordered by priority alone")
    step = max(1, 100 // (count + 1))
    for index, row in enumerate(order):
        row["priority"] = max(0, min(100, 100 - (index + 1) * step))
    return order


async def _one_session(session_id: int) -> dict[str, Any] | None:
    async with sessionmaker()() as db:
        row = (await db.execute(text(_SESSION_SELECT + " WHERE s.id = :id"), {"id": session_id})).mappings().first()
    return dict(row) if row else None


async def move_in_queue(session_id: int, move: str, *, by: str) -> dict[str, Any] | None:
    """Put a queued session somewhere else in the queue.

    The order is `priority DESC, created_at` — what the runner works on
    while the platform is busy — and an operator watching a backlog knows
    things the priority rules cannot: that this review is holding up a
    release, that this issue can wait. So they can say so.

    Expressed as a move rather than as a number, because a number invites
    guessing what the neighbours are. Moving past a session of equal
    priority means going one above it: ties are broken by age, and nothing
    here can make a session older.

    Returns the session as it now stands, or None if it is not queued.
    """
    if move not in ("up", "down", "first"):
        raise ValueError(f"unknown move '{move}' (expected up, down or first)")
    async with sessionmaker()() as db:
        rows = (
            (
                await db.execute(
                    text(
                        """
                    SELECT id, priority FROM agent_sessions
                     WHERE status = 'queued'
                     ORDER BY priority DESC, created_at, id
                     FOR UPDATE
                    """
                    )
                )
            )
            .mappings()
            .all()
        )
        order = [dict(row) for row in rows]
        at = next((index for index, row in enumerate(order) if row["id"] == session_id), None)
        if at is None:
            await db.rollback()
            return None
        # The move expressed as a position, so the boundaries cannot swallow
        # it: at 100 there is no "one above", and clamping would leave the
        # order exactly as it was while telling the operator it had moved.
        wanted = {"first": 0, "up": max(at - 1, 0), "down": min(at + 1, len(order) - 1)}[move]
        if wanted == at:
            await db.rollback()
            return await _one_session(session_id)
        moved = order.pop(at)
        order.insert(wanted, moved)
        try:
            order = _renumbered(order)
        except ValueError:
            await db.rollback()
            raise
        reason = f"moved in the queue by {by}"
        for position, row in enumerate(order):
            await db.execute(
                text(
                    """
                    UPDATE agent_sessions
                       SET priority = :priority,
                           priority_reason = CASE WHEN id = :moved THEN :reason ELSE priority_reason END
                     WHERE id = :id AND status = 'queued'
                    """
                ),
                {"id": row["id"], "priority": row["priority"], "moved": session_id, "reason": reason},
            )
            del position
        row = (await db.execute(text(_SESSION_SELECT + " WHERE s.id = :id"), {"id": session_id})).mappings().first()
        await db.commit()
    return dict(row) if row else None


async def attempts_for_trigger(ref: str) -> int:
    """How many sessions this one request has already had."""
    if not ref:
        return 0
    async with sessionmaker()() as db:
        count = (
            await db.execute(
                text("SELECT COUNT(*) FROM agent_sessions WHERE trigger_ref = :ref"),
                {"ref": ref},
            )
        ).scalar_one()
    return int(count or 0)


async def next_queued_session(*, include_triggered: bool = True) -> dict[str, Any] | None:
    """The session a claim would take next, without taking it.

    Admission decides against a capacity reading, and the reading has to be
    of the lane *this* session would be served by: a queued session on a
    saturated model must not be let in on an idle model's figure. Read under
    the same lock the claim runs in, and in the same order, so what is
    measured is what is then claimed.
    """
    async with sessionmaker()() as db:
        row = (
            (
                await db.execute(
                    text(
                        """
                    SELECT s.id, s.model, s.workspace_id
                      FROM agent_sessions s
                     WHERE s.status = 'queued'
                       AND (:include_triggered OR s.trigger_ref IS NULL)
                       AND NOT EXISTS (
                             SELECT 1 FROM agent_sessions busy
                              WHERE busy.workspace_id = s.workspace_id
                                AND busy.status = ANY(:occupying)
                           )
                       -- Nor while another session holds the same branch.
                       -- Two triggers on one pull request — a review and a
                       -- question, minutes apart — are two requests about
                       -- one piece of work, and two sessions in different
                       -- workspaces would each commit to that branch from a
                       -- checkout taken before the other one pushed. One
                       -- waits; its checkout then contains the other's work.
                       AND NOT EXISTS (
                             SELECT 1 FROM agent_sessions same
                              WHERE same.branch_name IS NOT NULL
                                AND same.branch_name = s.branch_name
                                AND same.id <> s.id
                                AND same.status = ANY(:occupying)
                           )
                     ORDER BY s.priority DESC, s.created_at
                     LIMIT 1
                    """
                    ),
                    {
                        "include_triggered": include_triggered,
                        "occupying": [
                            SessionStatus.STARTING.value,
                            SessionStatus.RUNNING.value,
                            SessionStatus.PAUSED.value,
                            SessionStatus.FINALIZING.value,
                        ],
                    },
                )
            )
            .mappings()
            .first()
        )
    return dict(row) if row else None


async def claim_session(session_id: int, *, trigger_quota: int | None = None) -> dict[str, Any] | None:
    """Take this exact queued session, or nothing.

    Admission measures the lane of the session it intends to start, and the
    peek and the claim are separate statements: in between, that row can be
    cancelled, or a more urgent one on another model can be queued. Claiming
    "the next one" would then start a session whose lane nobody measured.

    ``trigger_quota`` is how many self-queued sessions may be running at
    once, counted *inside this statement*. Counting it beforehand and
    claiming afterwards leaves a window in which two schedulers both see
    room — the automation would then take the places kept for people.

    A session with a branch holds that branch's advisory lock while it
    claims: the row lock alone cannot keep two claims on one branch apart —
    each locks only its own row, and the branch check sees the other still
    queued. The branch is written at insert and never changed, so the peek
    names exactly the branch the claim checks; the lock is held to the
    end of this transaction, and the check below re-reads the branch only
    after the previous holder has committed.
    """
    async with sessionmaker()() as db:
        if trigger_quota is not None:
            # One admission at a time, across every replica: two schedulers
            # locking different rows would otherwise both read the same
            # count of active triggered sessions and both pass the check
            # below, taking the places kept for people. Held to the end of
            # this transaction, which is the claim.
            await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('logos-agent-admission'))"))
        branch = (
            await db.execute(
                text("SELECT s.branch_name FROM agent_sessions s WHERE s.id = :session_id"),
                {"session_id": session_id},
            )
        ).scalar_one_or_none()
        if branch is not None:
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('logos-agent-branch:' || :branch))"),
                {"branch": branch},
            )
        claimed = (
            await db.execute(
                text(
                    """
                    SELECT s.id FROM agent_sessions s
                     WHERE s.id = :session_id
                       AND s.status = 'queued'
                       AND NOT EXISTS (
                             SELECT 1 FROM agent_sessions busy
                              WHERE busy.workspace_id = s.workspace_id
                                AND busy.status = ANY(:occupying)
                           )
                       -- Nor while another session holds the same branch.
                       -- Two triggers on one pull request — a review and a
                       -- question, minutes apart — are two requests about
                       -- one piece of work, and two sessions in different
                       -- workspaces would each commit to that branch from a
                       -- checkout taken before the other one pushed. One
                       -- waits; its checkout then contains the other's work.
                       AND NOT EXISTS (
                             SELECT 1 FROM agent_sessions same
                              WHERE same.branch_name IS NOT NULL
                                AND same.branch_name = s.branch_name
                                AND same.id <> s.id
                                AND same.status = ANY(:occupying)
                           )
                       AND (
                             s.trigger_ref IS NULL
                             OR CAST(:trigger_quota AS INTEGER) IS NULL
                             OR (
                                  SELECT COUNT(*) FROM agent_sessions mine
                                   WHERE mine.trigger_ref IS NOT NULL
                                     AND mine.status = ANY(:occupying)
                                ) < CAST(:trigger_quota AS INTEGER)
                           )
                     FOR UPDATE OF s SKIP LOCKED
                    """
                ),
                {
                    "session_id": session_id,
                    "trigger_quota": trigger_quota,
                    "occupying": [
                        SessionStatus.STARTING.value,
                        SessionStatus.RUNNING.value,
                        SessionStatus.PAUSED.value,
                        SessionStatus.FINALIZING.value,
                    ],
                },
            )
        ).scalar_one_or_none()
        if claimed is None:
            await db.rollback()
            return None
        await db.execute(
            text("UPDATE agent_sessions SET status = 'starting' WHERE id = :session_id"),
            {"session_id": session_id},
        )
        row = (
            (await db.execute(text(_SESSION_SELECT + " WHERE s.id = :session_id"), {"session_id": session_id}))
            .mappings()
            .first()
        )
        await db.commit()
    return dict(row) if row else None


# The conditions under which a queued session may be claimed, shared by the
# branch peek and the claim below so the two cannot drift apart. A session
# is startable only when no other session is already occupying its workspace
# — the workspace is one working copy on one volume, so two concurrent
# sessions in it would write over each other — and when no other session
# occupies its branch, for the same reason one level up: two workspaces
# committing to one branch from checkouts taken before the other pushed.
# Parallelism comes from running several *workspaces*, not several sessions
# per workspace or per branch.
_CLAIMABLE = """
    s.status = 'queued'
      -- The automation may fill the platform, but not the
      -- last places in it: with its quota used up, only
      -- work a person queued is claimable.
      AND (:include_triggered OR s.trigger_ref IS NULL)
      AND NOT EXISTS (
            SELECT 1 FROM agent_sessions busy
             WHERE busy.workspace_id = s.workspace_id
               AND busy.status = ANY(:occupying)
           )
      -- Nor while another session holds the same branch.
      -- Two triggers on one pull request — a review and a
      -- question, minutes apart — are two requests about
      -- one piece of work, and two sessions in different
      -- workspaces would each commit to that branch from a
      -- checkout taken before the other one pushed. One
      -- waits; its checkout then contains the other's work.
      AND NOT EXISTS (
            SELECT 1 FROM agent_sessions same
             WHERE same.branch_name IS NOT NULL
               AND same.branch_name = s.branch_name
               AND same.id <> s.id
               AND same.status = ANY(:occupying)
           )
      -- One candidate per workspace, so a workspace cannot
      -- take several slots in a pass and then collide with
      -- itself — and it is that workspace's most urgent
      -- queued session, oldest among equals. Picking the
      -- oldest outright would hide a security fix behind a
      -- typo that happened to be queued into the same
      -- checkout first, and the global order below could
      -- never correct it.
      AND s.id = (
            SELECT peer.id FROM agent_sessions peer
             WHERE peer.workspace_id = s.workspace_id
               AND peer.status = 'queued'
               -- The same trigger rule as the outer predicate: a pass that
               -- may not take triggered rows must not let a triggered row
               -- stand in as the workspace's best candidate either, or
               -- every manual row behind it fails this comparison and the
               -- workspace goes unclaimed while the quota is full.
               AND (:include_triggered OR peer.trigger_ref IS NULL)
             ORDER BY peer.priority DESC, peer.created_at, peer.id
             LIMIT 1
           )
"""


async def claim_queued_sessions(limit: int, *, include_triggered: bool = True) -> list[dict[str, Any]]:
    """Take up to `limit` startable queued sessions and mark them starting.

    ``FOR UPDATE SKIP LOCKED`` makes this safe to call from more than one
    replica: two schedulers never claim the same session.

    Branches are the second axis the row locks cannot cover: one statement
    can select several sessions that commit to one branch, and two replicas
    can each select one. The peek therefore names every branch the pass
    may touch, and those advisory locks are taken — sorted, so two passes
    locking different sets cannot deadlock — before the claim re-checks
    everything under the row locks. The claim selects *every* candidate,
    not `limit`: dedup happens before the limit, so a second session of one
    branch spends no slot the platform would never admit it to, and null
    branches keep every slot they earn.
    """
    if limit <= 0:
        return []
    async with sessionmaker()() as db:
        params = {
            "include_triggered": include_triggered,
            "occupying": [
                SessionStatus.STARTING.value,
                SessionStatus.RUNNING.value,
                SessionStatus.PAUSED.value,
                # The finalizer runs git in the working copy on
                # the same volume: a new session admitted during
                # finalization would write over it.
                SessionStatus.FINALIZING.value,
            ],
        }
        candidates = (
            (
                await db.execute(
                    text(
                        "SELECT s.id, s.branch_name FROM agent_sessions s WHERE "
                        + _CLAIMABLE
                        # Most urgent first, oldest among equals: sessions
                        # are admitted one per capacity reading, so this
                        # order is what the platform works on while it is
                        # busy. The id tie-break keeps the order below
                        # deterministic when two sessions share a moment.
                        + " ORDER BY s.priority DESC, s.created_at, s.id"
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )
        for branch in sorted({c["branch_name"] for c in candidates if c["branch_name"] is not None}):
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('logos-agent-branch:' || :branch))"),
                {"branch": branch},
            )
        claimed = (
            (
                await db.execute(
                    text(
                        "SELECT s.id, s.branch_name FROM agent_sessions s WHERE "
                        + _CLAIMABLE
                        + " ORDER BY s.priority DESC, s.created_at, s.id"
                        + " FOR UPDATE OF s SKIP LOCKED"
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )
        taken: list[int] = []
        seen_branches: set[str] = set()
        for candidate in claimed:
            if len(taken) >= limit:
                break
            branch = candidate["branch_name"]
            if branch is not None:
                if branch in seen_branches:
                    continue
                seen_branches.add(branch)
            taken.append(candidate["id"])
        if not taken:
            await db.rollback()
            return []
        await db.execute(
            text("UPDATE agent_sessions SET status = 'starting' WHERE id = ANY(:ids)"),
            {"ids": list(taken)},
        )
        rows = (
            (await db.execute(text(_SESSION_SELECT + " WHERE s.id = ANY(:ids)"), {"ids": list(taken)})).mappings().all()
        )
        await db.commit()
    return [dict(r) for r in rows]


async def sessions_awaiting_checks() -> list[dict[str, Any]]:
    """Finished sessions whose pushed commit nobody has judged yet.

    The follow-up on a red build outlives the process that started it: a
    redeploy in the couple of minutes between pushing and CI concluding
    used to drop it silently. Asked on startup and on every scheduler pass,
    and almost always empty.
    """
    async with sessionmaker()() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT id, workspace_id, task, model, branch_name, checks_sha,
                           trigger_kind, trigger_ref, reply_target, reaction_target,
                           priority, priority_reason, open_pull_request, finished_at
                      FROM agent_sessions
                     WHERE checks_watch = 'pending'
                     ORDER BY id
                    """
                )
            )
        ).mappings()
        return [dict(row) for row in rows]


async def sessions_owing_a_replacement(*, max_attempts: int, since: datetime) -> list[dict[str, Any]]:
    """Failed requests that were never taken up again, and still could be.

    Derived rather than flagged, and deliberately so. A row already says
    everything needed to know whether a replacement is owed — it failed, it
    came from a request, nothing newer has been tried for that request, and
    the request has attempts left — so there is no intent to write, nothing
    to keep in step with the rows it describes, and no way for the intent
    and the fact to disagree. It also covers the sessions that failed
    before any of this existed, which a flag written at settlement never
    could.

    ``id > s.id`` is what makes "nothing newer" cheap and exact: a
    replacement that is queued, running or itself failed is a later row
    with the same reference, and any of the three means this row is no
    longer the one that owes anything.
    """
    async with sessionmaker()() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT s.id, s.workspace_id, s.task, s.model, s.branch_name,
                           s.trigger_kind, s.trigger_ref, s.reply_target, s.reaction_target,
                           s.priority, s.priority_reason, s.open_pull_request, s.error,
                           s.finished_at
                      FROM agent_sessions s
                     WHERE s.status = 'failed'
                       AND COALESCE(s.trigger_ref, '') <> ''
                       AND s.finished_at IS NOT NULL
                       AND s.finished_at > :since
                       AND NOT EXISTS (
                             SELECT 1 FROM agent_sessions newer
                              WHERE newer.trigger_ref = s.trigger_ref
                                AND newer.id > s.id
                           )
                       AND (
                             SELECT COUNT(*) FROM agent_sessions tried
                              WHERE tried.trigger_ref = s.trigger_ref
                           ) < :max_attempts
                     ORDER BY s.id
                    """
                ),
                {"since": since, "max_attempts": max_attempts},
            )
        ).mappings()
        return [dict(row) for row in rows]


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
        # The text this session was handed, as opposed to the text sessions
        # are handed now — the instructions are editable.
        "environment_notes",
        # The commit whose checks somebody still has to look at, and whether
        # anybody still owes that.
        "checks_sha",
        "checks_watch",
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
    # Committed first, then announced: a watcher woken by this reads the
    # event it was woken for, not the transaction that has not landed yet.
    pulse.ring(session_id)


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
