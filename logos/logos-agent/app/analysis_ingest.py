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
# Bound on walking pending predecessors back to the last reviewed decision.
MAX_ANCESTOR_HOPS = 50
# Bound on the candidate pairs one (file, workflow) group may build when matching.
MAX_MATCH_PAIRS_PER_GROUP = 10_000


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
                   AND status IN ('queued', 'running')
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
        previous_workflows = await _previous_workflows(conn, team_repository_id, int(analysis_id))
        previous_by_name = {str(w["name"]): w for w in previous_workflows if w.get("name")}

        workflow_ids: dict[str, int] = {}
        for index, raw in enumerate(workflows):
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip() or f"workflow-{index + 1}"
            agent_diagram = str(raw.get("diagram_mermaid") or "")
            previous_wf = previous_by_name.get(name)
            diagram, owner_flag, proposed, dismissed = _diagram_for_ingest(agent_diagram, previous_wf)
            wf_id = (
                await conn.execute(
                    text("""
                        INSERT INTO ai_workflows
                            (analysis_id, name, trigger_summary, diagram_mermaid, sort_order,
                             diagram_set_by_owner, proposed_diagram_mermaid, dismissed_diagram_mermaid)
                        VALUES
                            (:analysis_id, :name, :trigger_summary, :diagram, :sort_order,
                             :diagram_set_by_owner, :proposed, :dismissed)
                        RETURNING id
                        """),
                    {
                        "analysis_id": analysis_id,
                        "name": name,
                        "trigger_summary": _str_or_none(raw.get("trigger_summary")),
                        "diagram": diagram,
                        "sort_order": int(raw.get("sort_order") if raw.get("sort_order") is not None else index),
                        "diagram_set_by_owner": owner_flag,
                        "proposed": proposed,
                        "dismissed": dismissed,
                    },
                )
            ).scalar_one()
            workflow_ids[name] = int(wf_id)
            nested = raw.get("recommendations")
            if isinstance(nested, list):
                for nested_rec in nested:
                    if isinstance(nested_rec, dict):
                        recommendations.append({**nested_rec, "workflow": name})

        parsed: list[dict[str, Any]] = []
        for raw in recommendations:
            if not isinstance(raw, dict):
                continue
            file_path = str(raw.get("file_path") or "").strip()
            if not file_path:
                continue
            sla = str(raw.get("recommended_sla") or "").strip()
            if sla not in VALID_SLAS:
                sla = "ux-high-prio"
            workflow_name = str(raw.get("workflow") or raw.get("workflow_name") or "").strip()
            flags = raw.get("traffic_flags")
            confidence = raw.get("confidence")
            try:
                confidence_f = float(confidence) if confidence is not None else 0.5
            except (TypeError, ValueError):
                confidence_f = 0.5
            parsed.append(
                {
                    "file_path": file_path,
                    "workflow_name": workflow_name,
                    # Never trust a numeric workflow_id from the artifact — it could
                    # point at another analysis/team. Resolve only via names created
                    # for this ingest.
                    "workflow_id": workflow_ids.get(workflow_name) if workflow_name else None,
                    "start_line": _int_or_none(raw.get("start_line")),
                    "end_line": _int_or_none(raw.get("end_line")),
                    "code_url": _str_or_none(raw.get("code_url")),
                    "detected_model": _str_or_none(raw.get("detected_model")),
                    "sla": sla,
                    "priority": normalize_objective_priority(raw.get("objective_priority"), sla=sla),
                    "confidence": confidence_f,
                    "justification": str(raw.get("justification") or ""),
                    "flags": json.dumps(flags if isinstance(flags, dict) else {}),
                }
            )

        predecessors = match_recommendations(previous_recs, parsed)
        for index, rec in enumerate(parsed):
            previous = predecessors.get(index)
            review = carried_review(
                previous.get("decision") if previous else None, sla=rec["sla"], priority=rec["priority"]
            )
            owner_model = previous is not None and bool(previous["model_set_by_owner"])
            await conn.execute(
                text("""
                    INSERT INTO ai_llm_call_recommendations
                        (analysis_id, workflow_id, team_id, file_path, start_line, end_line,
                         code_url, detected_model, model_set_by_owner, recommended_sla, objective_priority,
                         confidence, justification, traffic_flags, review_status, review_carried_over,
                         confirmed_sla, confirmed_objective_priority, api_key_id, reviewed_by, reviewed_at,
                         previous_recommendation_id)
                    VALUES
                        (:analysis_id, :workflow_id, :team_id, :file_path, :start_line, :end_line,
                         :code_url, :detected_model, :model_set_by_owner, :sla, CAST(:priority AS jsonb),
                         :confidence, :justification, CAST(:flags AS jsonb), :review_status, :carried_over,
                         :confirmed_sla, CAST(:confirmed_priority AS jsonb), :api_key_id, :reviewed_by, :reviewed_at,
                         :previous_id)
                    """),
                {
                    **review,
                    "carried_over": review["review_status"] != "pending",
                    "analysis_id": analysis_id,
                    "team_id": team_id,
                    "workflow_id": rec["workflow_id"],
                    "file_path": rec["file_path"],
                    "start_line": rec["start_line"],
                    "end_line": rec["end_line"],
                    "code_url": rec["code_url"],
                    # The owner said which model this call site uses; the analysis
                    # guessing again must not replace that.
                    "detected_model": previous["detected_model"] if owner_model else rec["detected_model"],
                    "model_set_by_owner": owner_model,
                    "previous_id": previous["id"] if previous is not None else None,
                    "sla": rec["sla"],
                    "priority": json.dumps(rec["priority"]),
                    "confidence": rec["confidence"],
                    "justification": rec["justification"],
                    "flags": rec["flags"],
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


def _normalize_diagram(text: str) -> str:
    """Compare Mermaid without trailing whitespace noise."""
    return "\n".join(line.rstrip() for line in (text or "").strip().splitlines())


def _diagram_for_ingest(
    agent_diagram: str, previous: dict[str, Any] | None
) -> tuple[str, bool, str | None, str | None]:
    """Keep an owner-edited diagram; store a differing agent version as a proposal.

    Returns (diagram, set_by_owner, proposed, dismissed). A proposal the owner
    already dismissed ("Keep mine") is not offered again while the agent keeps
    drawing the same Mermaid.
    """
    if previous is None or not bool(previous.get("diagram_set_by_owner")):
        return agent_diagram, False, None, None
    owner_diagram = str(previous.get("diagram_mermaid") or "")
    dismissed = _str_or_none(previous.get("dismissed_diagram_mermaid"))
    agent_norm = _normalize_diagram(agent_diagram)
    if not agent_norm or agent_norm == _normalize_diagram(owner_diagram):
        return owner_diagram, True, None, dismissed
    if dismissed is not None and agent_norm == _normalize_diagram(dismissed):
        return owner_diagram, True, None, dismissed
    return owner_diagram, True, agent_diagram, dismissed


async def _previous_workflows(conn: Any, team_repository_id: int, analysis_id: int) -> list[dict[str, Any]]:
    """Workflows of the latest other succeeded analysis of this repository.

    Matched by name when carrying owner-edited diagrams forward. The caller
    holds the repository row lock; owner diagram edits take it too.
    """
    rows = (
        (
            await conn.execute(
                text("""
                    SELECT w.name, w.diagram_mermaid, w.diagram_set_by_owner,
                           w.proposed_diagram_mermaid, w.dismissed_diagram_mermaid
                      FROM ai_workflows w
                     WHERE w.analysis_id = (
                             SELECT a.id FROM ai_workflow_analyses a
                              WHERE a.team_repository_id = :repo
                                AND a.status = 'succeeded'
                                AND a.id <> :current
                              ORDER BY a.finished_at DESC NULLS LAST, a.id DESC
                              LIMIT 1
                           )
                     ORDER BY w.sort_order, w.id
                    """),
                {"repo": team_repository_id, "current": analysis_id},
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


async def _previous_recommendations(conn: Any, team_repository_id: int, analysis_id: int) -> list[dict[str, Any]]:
    """Recommendations of the latest other succeeded analysis of this repository.

    Each carries ``decision``: its nearest reviewed ancestor (itself when it was
    reviewed), found through pending predecessors, so an earlier decision is not
    lost because a changed proposal sat unreviewed while the next analysis ran.
    The caller holds the repository row lock; owner edits take it too.
    """
    rows = (
        (
            await conn.execute(
                text("""
                    SELECT r.id, r.file_path, r.start_line, w.name AS workflow_name,
                           r.review_status, r.detected_model, r.model_set_by_owner
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
    previous = [dict(r) for r in rows]
    if not previous:
        return []
    decisions = (
        (
            await conn.execute(
                text("""
                    WITH RECURSIVE chain AS (
                        SELECT r.id AS start_id, r.id, r.review_status, r.previous_recommendation_id, 0 AS depth
                          FROM ai_llm_call_recommendations r
                         WHERE r.id = ANY(:ids)
                        UNION ALL
                        SELECT c.start_id, r.id, r.review_status, r.previous_recommendation_id, c.depth + 1
                          FROM chain c
                          JOIN ai_llm_call_recommendations r ON r.id = c.previous_recommendation_id
                         WHERE c.review_status = 'pending' AND c.depth < :max_hops
                    )
                    SELECT DISTINCT ON (c.start_id) c.start_id,
                           d.id, d.review_status, d.recommended_sla, d.objective_priority,
                           d.confirmed_sla, d.confirmed_objective_priority,
                           d.api_key_id, d.reviewed_by, d.reviewed_at
                      FROM chain c
                      JOIN ai_llm_call_recommendations d ON d.id = c.id
                     WHERE c.review_status <> 'pending'
                     ORDER BY c.start_id, c.depth
                    """),
                {"ids": [int(p["id"]) for p in previous], "max_hops": MAX_ANCESTOR_HOPS},
            )
        )
        .mappings()
        .all()
    )
    by_start = {int(d["start_id"]): dict(d) for d in decisions}
    for p in previous:
        p["decision"] = by_start.get(int(p["id"]))
    return previous


def match_recommendations(previous: list[dict[str, Any]], current: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Pair new recommendations with the ones they succeed, conservatively.

    The whole set is matched before anything is carried over, so an added call
    site cannot take an existing one's predecessor. First the same file and
    the same workflow, nearest line first. Then, per file, a remaining pair is
    matched only when it is the single unmatched row on both sides. Anything
    else — new, removed or ambiguous — stays without a predecessor (pending).
    Returns current index → previous row.
    """
    used: set[int] = set()
    matched: dict[int, dict[str, Any]] = {}

    def line_gap(cur: dict[str, Any], prev: dict[str, Any]) -> int:
        if cur["start_line"] is None or prev["start_line"] is None:
            return 0
        return abs(int(prev["start_line"]) - int(cur["start_line"]))

    groups: dict[tuple[str, str], tuple[list[int], list[int]]] = {}
    for ci, cur in enumerate(current):
        if cur["workflow_name"]:
            groups.setdefault((cur["file_path"], cur["workflow_name"]), ([], []))[0].append(ci)
    for pi, prev in enumerate(previous):
        key = (prev["file_path"], prev["workflow_name"] or "")
        if key in groups:
            groups[key][1].append(pi)
    for cur_ids, prev_ids in groups.values():
        # Pairing is quadratic in the group; a group too large to pair cheaply
        # stays unmatched (pending) rather than stalling the runner.
        if len(cur_ids) * len(prev_ids) > MAX_MATCH_PAIRS_PER_GROUP:
            continue
        pairs = sorted((line_gap(current[ci], previous[pi]), ci, pi) for ci in cur_ids for pi in prev_ids)
        for _gap, ci, pi in pairs:
            if ci not in matched and pi not in used:
                matched[ci] = previous[pi]
                used.add(pi)

    open_current: dict[str, list[int]] = {}
    for ci, cur in enumerate(current):
        if ci not in matched:
            open_current.setdefault(cur["file_path"], []).append(ci)
    open_previous: dict[str, list[int]] = {}
    for pi, prev in enumerate(previous):
        if pi not in used:
            open_previous.setdefault(prev["file_path"], []).append(pi)
    for file_path, cur_ids in open_current.items():
        prev_ids = open_previous.get(file_path, [])
        if len(cur_ids) == 1 and len(prev_ids) == 1:
            matched[cur_ids[0]] = previous[prev_ids[0]]
            used.add(prev_ids[0])
    return matched


def _priority_list(raw: Any, *, sla: str) -> list[str]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = None
    return normalize_objective_priority(raw, sla=sla)


def carried_review(previous: dict[str, Any] | None, *, sla: str, priority: list[str]) -> dict[str, Any]:
    """Review fields for a new recommendation, given the last reviewed decision it inherits.

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
