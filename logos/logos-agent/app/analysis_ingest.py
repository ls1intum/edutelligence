"""Ingest agent-produced workflow analysis into the webservice schema.

A read-only analysis session writes ``/artifacts/analysis.json``. After a
successful no-push finalize the runner loads that file (when present) and
upserts ``ai_workflow_analyses`` / ``ai_workflows`` /
``ai_llm_call_recommendations`` — the same tables Liquibase 043 and the
webservice heuristic scanner use. Missing file is a no-op with a log line;
the session still succeeds.
"""

from __future__ import annotations

import json
import logging
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from . import db
from .config import settings

logger = logging.getLogger(__name__)

ANALYSIS_FILE = "analysis.json"
VALID_SLAS = frozenset({"ux-critical", "ux-high-prio", "ux-background"})
OBJECTIVE_KEYS = ("latency", "quality", "price")
DEFAULT_OBJECTIVE_PRIORITY = list(OBJECTIVE_KEYS)
# Cap memory: an agent-written artifact must not exhaust the runner.
MAX_ANALYSIS_BYTES = 2 * 1024 * 1024


def objective_priority_for_sla(sla: str) -> list[str]:
    if sla == "ux-critical":
        return ["latency", "quality", "price"]
    if sla == "ux-background":
        return ["price", "quality", "latency"]
    return ["quality", "latency", "price"]


def normalize_objective_priority(raw: object, *, sla: str) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    if isinstance(raw, list):
        for item in raw:
            key = str(item or "").strip().lower()
            if key in OBJECTIVE_KEYS and key not in seen:
                ordered.append(key)
                seen.add(key)
    if not ordered:
        ordered = objective_priority_for_sla(sla)
        seen = set(ordered)
    for key in OBJECTIVE_KEYS:
        if key not in seen:
            ordered.append(key)
    return ordered


def artifact_analysis_path(session_id: int) -> Path:
    return Path(settings.artifact_root) / str(session_id) / ANALYSIS_FILE


def read_analysis_artifact(path: Path) -> bytes:
    """Read ``analysis.json`` without following symlinks, as a regular file only.

    The agent sandbox can create ``analysis.json -> ../other-session/...``.
    Following that would let one session ingest another team's private
    workflows. ``O_NOFOLLOW`` rejects a final-component symlink; ``O_NONBLOCK``
    prevents a named pipe without a writer from hanging the asyncio loop;
    ``fstat`` confirms a regular file; the read is byte-capped.
    """
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise OSError(f"unsafe or unreadable analysis artifact: {exc}") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise OSError("analysis artifact is not a regular file")
        if st.st_size > MAX_ANALYSIS_BYTES:
            raise OSError(f"analysis artifact exceeds {MAX_ANALYSIS_BYTES} bytes")
        # Clear non-blocking for the actual read of a verified regular file.
        if hasattr(os, "set_blocking"):
            os.set_blocking(fd, True)
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, 64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_ANALYSIS_BYTES:
                raise OSError(f"analysis artifact exceeds {MAX_ANALYSIS_BYTES} bytes")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


async def ingest_session(session: dict[str, Any]) -> None:
    """Load analysis.json for ``session`` and upsert results, or mark failed."""
    session_id = int(session["id"])
    path = artifact_analysis_path(session_id)
    try:
        raw = read_analysis_artifact(path)
    except FileNotFoundError:
        logger.info(
            "analysis session %s left no %s; marking analysis failed",
            session_id,
            ANALYSIS_FILE,
        )
        await mark_analysis_failed(session_id, f"missing {ANALYSIS_FILE}")
        return
    except OSError as exc:
        logger.warning("could not safely read analysis.json for session %s: %s", session_id, exc)
        await mark_analysis_failed(session_id, f"unsafe analysis.json: {exc}")
        return
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("could not parse analysis.json for session %s: %s", session_id, exc)
        await mark_analysis_failed(session_id, f"invalid analysis.json: {exc}")
        return
    if not isinstance(payload, dict):
        logger.warning("analysis.json for session %s is not an object; skipping", session_id)
        await mark_analysis_failed(session_id, "analysis.json is not an object")
        return
    team_repository_id = session.get("team_repository_id")
    if team_repository_id is None:
        logger.warning("analysis session %s has no team_repository_id; skipping ingest", session_id)
        await mark_analysis_failed(session_id, "session has no team_repository_id")
        return
    if payload.get("unchanged") is True:
        await mark_analysis_unchanged(
            session_id=session_id,
            team_repository_id=int(team_repository_id),
            commit_sha=_str_or_none(payload.get("commit_sha")),
        )
        return
    try:
        await upsert_analysis(
            session_id=session_id,
            team_repository_id=int(team_repository_id),
            payload=payload,
            session_repo_slug=session.get("repo_slug"),
        )
    except ObsoleteLinkError as exc:
        logger.info("analysis session %s obsolete after link edit: %s", session_id, exc)
        await mark_analysis_failed(session_id, str(exc))
    except Exception as exc:
        logger.warning("analysis ingest for session %s failed: %s", session_id, exc)
        await mark_analysis_failed(session_id, str(exc))


async def mark_analysis_unchanged(*, session_id: int, team_repository_id: int, commit_sha: str | None) -> None:
    """Record a session that stopped because the repository did not change.

    Only believed when the commit it names is the one the latest succeeded
    analysis of that repository described; anything else is a session that
    skipped its work, and is recorded as failed.
    """
    async with db.sessionmaker()() as conn:
        previous = (
            await conn.execute(
                text("""
                    SELECT commit_sha FROM ai_workflow_analyses
                     WHERE team_repository_id = :repo AND status = 'succeeded'
                     ORDER BY finished_at DESC NULLS LAST, id DESC
                     LIMIT 1
                    """),
                {"repo": team_repository_id},
            )
        ).scalar_one_or_none()
        if not commit_sha or not previous or commit_sha != previous:
            await conn.rollback()
            logger.warning(
                "analysis session %s claimed unchanged at %s, latest analysed commit is %s",
                session_id,
                commit_sha,
                previous,
            )
            await mark_analysis_failed(session_id, "reported unchanged, but not at the analysed commit")
            return
        await conn.execute(
            text("""
                UPDATE ai_workflow_analyses
                   SET status = 'skipped', commit_sha = :sha, error = NULL, finished_at = :now
                 WHERE agent_session_id = :session_id
                """),
            {"sha": commit_sha, "now": datetime.now(timezone.utc), "session_id": session_id},
        )
        await conn.commit()
    logger.info("analysis session %s: repository unchanged at %s, skipped", session_id, commit_sha[:12])


class ObsoleteLinkError(ValueError):
    """Session analysed a repository the link no longer points at."""


async def mark_analysis_failed(session_id: int, error: str) -> None:
    """Persist a failed terminal state for the analysis linked to ``session_id``."""
    async with db.sessionmaker()() as conn:
        await conn.execute(
            text("""
                UPDATE ai_workflow_analyses
                   SET status = 'failed',
                       error = :error,
                       finished_at = :now
                 WHERE agent_session_id = :session_id
                   AND status IN ('queued', 'running')
                """),
            {
                "session_id": session_id,
                "error": (error or "analysis failed")[:2000],
                "now": datetime.now(timezone.utc),
            },
        )
        await conn.commit()


async def upsert_analysis(
    *,
    session_id: int,
    team_repository_id: int,
    payload: dict[str, Any],
    session_repo_slug: str | None = None,
) -> int:
    """Write workflows + recommendations for one agent analysis. Returns analysis id."""
    commit_sha = _str_or_none(payload.get("commit_sha"))
    workflows = payload.get("workflows") or []
    recommendations = payload.get("recommendations") or []
    if not isinstance(workflows, list):
        workflows = []
    if not isinstance(recommendations, list):
        recommendations = []

    async with db.sessionmaker()() as conn:
        # Serialize with TeamRepoLinkService slug edits (FOR UPDATE) and reject
        # results whose session targeted a previous repository identity.
        link = (
            (
                await conn.execute(
                    text("""
                    SELECT team_id, repo_slug
                      FROM team_repositories
                     WHERE id = :id
                     FOR UPDATE
                    """),
                    {"id": team_repository_id},
                )
            )
            .mappings()
            .first()
        )
        if link is None:
            raise ValueError(f"team_repository {team_repository_id} does not exist")
        team_id = int(link["team_id"])
        current_slug = str(link["repo_slug"] or "").lower()
        expected = str(session_repo_slug or "").strip().lower()
        if expected and current_slug and expected != current_slug:
            raise ObsoleteLinkError(f"session targeted {expected} but link now points at {current_slug}")

        analysis_id = (
            await conn.execute(
                text("""
                    SELECT id FROM ai_workflow_analyses
                     WHERE agent_session_id = :session_id
                     ORDER BY id DESC LIMIT 1
                    """),
                {"session_id": session_id},
            )
        ).scalar_one_or_none()

        now = datetime.now(timezone.utc)
        if analysis_id is None:
            analysis_id = (
                await conn.execute(
                    text("""
                        INSERT INTO ai_workflow_analyses
                            (team_id, team_repository_id, commit_sha, status, source,
                             agent_session_id, started_at, finished_at)
                        VALUES
                            (:team_id, :repo_id, :commit_sha, 'succeeded', 'agent',
                             :session_id, :now, :now)
                        RETURNING id
                        """),
                    {
                        "team_id": team_id,
                        "repo_id": team_repository_id,
                        "commit_sha": commit_sha,
                        "session_id": session_id,
                        "now": now,
                    },
                )
            ).scalar_one()
        else:
            await conn.execute(
                text("""
                    UPDATE ai_workflow_analyses
                       SET commit_sha = :commit_sha,
                           status = 'succeeded',
                           source = 'agent',
                           error = NULL,
                           finished_at = :now
                     WHERE id = :id
                    """),
                {"commit_sha": commit_sha, "now": now, "id": analysis_id},
            )
            await conn.execute(
                text("DELETE FROM ai_llm_call_recommendations WHERE analysis_id = :id"),
                {"id": analysis_id},
            )
            await conn.execute(
                text("DELETE FROM ai_workflows WHERE analysis_id = :id"),
                {"id": analysis_id},
            )

        previous_recs = await _previous_recommendations(conn, team_repository_id, int(analysis_id))

        workflow_ids: dict[str, int] = {}
        for index, raw in enumerate(workflows):
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip() or f"workflow-{index + 1}"
            wf_id = (
                await conn.execute(
                    text("""
                        INSERT INTO ai_workflows
                            (analysis_id, name, trigger_summary, diagram_mermaid, sort_order)
                        VALUES
                            (:analysis_id, :name, :trigger_summary, :diagram, :sort_order)
                        RETURNING id
                        """),
                    {
                        "analysis_id": analysis_id,
                        "name": name,
                        "trigger_summary": _str_or_none(raw.get("trigger_summary")),
                        "diagram": str(raw.get("diagram_mermaid") or ""),
                        "sort_order": int(raw.get("sort_order") if raw.get("sort_order") is not None else index),
                    },
                )
            ).scalar_one()
            workflow_ids[name] = int(wf_id)
            nested = raw.get("recommendations")
            if isinstance(nested, list):
                for nested_rec in nested:
                    if isinstance(nested_rec, dict):
                        recommendations.append({**nested_rec, "workflow": name})

        for raw in recommendations:
            if not isinstance(raw, dict):
                continue
            file_path = str(raw.get("file_path") or "").strip()
            if not file_path:
                continue
            sla = str(raw.get("recommended_sla") or "").strip()
            if sla not in VALID_SLAS:
                sla = "ux-high-prio"
            priority = normalize_objective_priority(raw.get("objective_priority"), sla=sla)
            workflow_name = str(raw.get("workflow") or raw.get("workflow_name") or "").strip()
            workflow_id = workflow_ids.get(workflow_name) if workflow_name else None
            # Never trust a numeric workflow_id from the artifact — it could
            # point at another analysis/team. Resolve only via names created
            # for this ingest.
            flags = raw.get("traffic_flags")
            flags_json = json.dumps(flags if isinstance(flags, dict) else {})
            confidence = raw.get("confidence")
            try:
                confidence_f = float(confidence) if confidence is not None else 0.5
            except (TypeError, ValueError):
                confidence_f = 0.5
            start_line = _int_or_none(raw.get("start_line"))
            detected_model = _str_or_none(raw.get("detected_model"))
            previous = _match_previous(previous_recs, file_path, workflow_name, start_line)
            review = carried_review(previous, sla=sla, priority=priority)
            if previous is not None and previous["model_set_by_owner"]:
                # The owner said which model this call site uses; the analysis guessing
                # again must not replace that.
                detected_model = previous["detected_model"]
            await conn.execute(
                text("""
                    INSERT INTO ai_llm_call_recommendations
                        (analysis_id, workflow_id, team_id, file_path, start_line, end_line,
                         code_url, detected_model, model_set_by_owner, recommended_sla, objective_priority,
                         confidence, justification, traffic_flags, review_status,
                         confirmed_sla, confirmed_objective_priority, api_key_id, reviewed_by, reviewed_at,
                         previous_recommendation_id)
                    VALUES
                        (:analysis_id, :workflow_id, :team_id, :file_path, :start_line, :end_line,
                         :code_url, :detected_model, :model_set_by_owner, :sla, CAST(:priority AS jsonb),
                         :confidence, :justification, CAST(:flags AS jsonb), :review_status,
                         :confirmed_sla, CAST(:confirmed_priority AS jsonb), :api_key_id, :reviewed_by, :reviewed_at,
                         :previous_id)
                    """),
                {
                    **review,
                    "model_set_by_owner": bool(previous is not None and previous["model_set_by_owner"]),
                    "previous_id": previous["id"] if previous is not None else None,
                    "analysis_id": analysis_id,
                    "workflow_id": workflow_id,
                    "team_id": team_id,
                    "file_path": file_path,
                    "start_line": start_line,
                    "end_line": _int_or_none(raw.get("end_line")),
                    "code_url": _str_or_none(raw.get("code_url")),
                    "detected_model": detected_model,
                    "sla": sla,
                    "priority": json.dumps(priority),
                    "confidence": confidence_f,
                    "justification": str(raw.get("justification") or ""),
                    "flags": flags_json,
                },
            )
        await conn.commit()
    logger.info(
        "ingested analysis %s for session %s (%s workflows)",
        analysis_id,
        session_id,
        len(workflow_ids),
    )
    return int(analysis_id)


async def _previous_recommendations(conn: Any, team_repository_id: int, analysis_id: int) -> list[dict[str, Any]]:
    """Recommendations of the latest other succeeded analysis of this repository."""
    rows = (
        (
            await conn.execute(
                text("""
                    SELECT r.id, r.file_path, r.start_line, w.name AS workflow_name,
                           r.review_status, r.recommended_sla, r.objective_priority,
                           r.confirmed_sla, r.confirmed_objective_priority,
                           r.api_key_id, r.reviewed_by, r.reviewed_at,
                           r.detected_model, r.model_set_by_owner
                      FROM ai_llm_call_recommendations r
                      LEFT JOIN ai_workflows w ON w.id = r.workflow_id
                     WHERE r.analysis_id = (
                             SELECT a.id FROM ai_workflow_analyses a
                              WHERE a.team_repository_id = :repo
                                AND a.status = 'succeeded'
                                AND a.id <> :current
                              ORDER BY a.finished_at DESC NULLS LAST, a.id DESC
                              LIMIT 1
                           )
                     ORDER BY r.id
                    """),
                {"repo": team_repository_id, "current": analysis_id},
            )
        )
        .mappings()
        .all()
    )
    return [{**dict(r), "_used": False} for r in rows]


def _match_previous(
    previous: list[dict[str, Any]], file_path: str, workflow_name: str, start_line: int | None
) -> dict[str, Any] | None:
    """The unused previous recommendation for the same call site, if any.

    Same file is required; the same workflow wins over another one, then the
    nearest line (code moves between commits). Each previous row is matched once.
    """
    candidates = [p for p in previous if not p["_used"] and p["file_path"] == file_path]
    if not candidates:
        return None

    def distance(p: dict[str, Any]) -> tuple[int, int]:
        same_workflow = 0 if workflow_name and p["workflow_name"] == workflow_name else 1
        if start_line is None or p["start_line"] is None:
            return same_workflow, 0
        return same_workflow, abs(int(p["start_line"]) - start_line)

    best = min(candidates, key=distance)
    best["_used"] = True
    return best


def _priority_list(raw: Any, *, sla: str) -> list[str]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = None
    return normalize_objective_priority(raw, sla=sla)


def carried_review(previous: dict[str, Any] | None, *, sla: str, priority: list[str]) -> dict[str, Any]:
    """Review fields for a new recommendation, given the one it succeeds.

    A re-analysis proposes; it never overwrites a decision. When the new
    proposal is what the owner already confirmed (or already rejected), that
    review carries over unchanged. Anything else is pending, and the UI shows
    it next to the previous decision.
    """
    pending: dict[str, Any] = {
        "review_status": "pending",
        "confirmed_sla": None,
        "confirmed_priority": None,
        "api_key_id": None,
        "reviewed_by": None,
        "reviewed_at": None,
    }
    if previous is None:
        return pending
    status = previous["review_status"]
    if status in ("accepted", "overridden"):
        confirmed_sla = previous["confirmed_sla"] or previous["recommended_sla"]
        confirmed = _priority_list(
            previous["confirmed_objective_priority"] or previous["objective_priority"], sla=confirmed_sla
        )
        if (sla, priority) != (confirmed_sla, confirmed):
            return pending
        return {
            "review_status": status,
            "confirmed_sla": confirmed_sla,
            "confirmed_priority": json.dumps(confirmed),
            "api_key_id": previous["api_key_id"],
            "reviewed_by": previous["reviewed_by"],
            "reviewed_at": previous["reviewed_at"],
        }
    if status == "rejected":
        rejected_sla = previous["recommended_sla"]
        if (sla, priority) != (rejected_sla, _priority_list(previous["objective_priority"], sla=rejected_sla)):
            return pending
        return {
            **pending,
            "review_status": "rejected",
            "reviewed_by": previous["reviewed_by"],
            "reviewed_at": previous["reviewed_at"],
        }
    return pending


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
