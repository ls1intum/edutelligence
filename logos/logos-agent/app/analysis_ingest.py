"""Ingest agent-produced workflow analysis into the webservice schema.

A read-only analysis session writes ``/artifacts/analysis.json``. After a
successful no-push finalize the runner loads that file (when present) and
upserts ``ai_workflow_analyses`` / ``ai_workflows`` / ``ai_workflow_steps`` /
``ai_llm_call_recommendations`` — the same tables Liquibase 046/057 and the
webservice analysis path use. Missing file is a no-op with a log line;
the session still succeeds.
"""

from __future__ import annotations

import json
import logging
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from . import db
from .config import settings

logger = logging.getLogger(__name__)

ANALYSIS_FILE = "analysis.json"
VALID_SLOS = frozenset({"ux-critical", "ux-high-prio", "ux-background"})
OBJECTIVE_KEYS = ("latency", "quality", "price")
DEFAULT_OBJECTIVE_PRIORITY = list(OBJECTIVE_KEYS)
# Cap memory: an agent-written artifact must not exhaust the runner.
MAX_ANALYSIS_BYTES = 2 * 1024 * 1024
# Bound on walking pending predecessors back to the last reviewed decision.
MAX_ANCESTOR_HOPS = 50
# Bound on the candidate pairs one (file, workflow) group may build when matching.
MAX_MATCH_PAIRS_PER_GROUP = 10_000
_TAG_ALLOWED = re.compile(r"[^a-z0-9-]")
MAX_TAG_CHARS = 80
# Room kept for a "-N" suffix that makes an allocated tag unique.
TAG_SUFFIX_RESERVE = 6


def objective_priority_for_slo(slo: str) -> list[str]:
    if slo == "ux-critical":
        return ["latency", "quality", "price"]
    if slo == "ux-background":
        return ["price", "quality", "latency"]
    return ["quality", "latency", "price"]


def normalize_objective_priority(raw: object, *, slo: str) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    if isinstance(raw, list):
        for item in raw:
            key = str(item or "").strip().lower()
            if key in OBJECTIVE_KEYS and key not in seen:
                ordered.append(key)
                seen.add(key)
    if not ordered:
        ordered = objective_priority_for_slo(slo)
        seen = set(ordered)
    for key in OBJECTIVE_KEYS:
        if key not in seen:
            ordered.append(key)
    return ordered


def normalize_workflow_tag(raw: object) -> str | None:
    """Stable kebab-case tag for ``X-Logos-Workflow-Tag``; blank → None."""
    if raw is None:
        return None
    value = str(raw).strip().lower()
    if not value:
        return None
    cleaned = _TAG_ALLOWED.sub("", value)[:MAX_TAG_CHARS]
    return cleaned or None


def unique_workflow_tag(tag: str | None, taken: set[str] | None) -> str | None:
    """``tag``, or ``tag-2``, ``tag-3``, … — never one in ``taken``; reserves it.

    Mirrors the webservice allocator: a long tag is cut to leave room for the
    suffix, so truncation cannot make two tags equal.
    """
    if not tag or taken is None:
        return tag
    stem = (
        tag[: MAX_TAG_CHARS - TAG_SUFFIX_RESERVE].rstrip("-") if len(tag) > MAX_TAG_CHARS - TAG_SUFFIX_RESERVE else tag
    )
    candidate, n = stem, 2
    while candidate in taken:
        candidate = f"{stem}-{n}"
        n += 1
    taken.add(candidate)
    return candidate


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
        previous_for = match_workflows(previous_workflows, previous_recs, workflows, recommendations)
        # Tags are matched team-wide; reserve every carried-over tag first so a
        # new one cannot take it, then allocate the rest against that set.
        taken_tags = await _lock_team_tags(conn, team_id, team_repository_id)
        for previous_wf in previous_workflows:
            taken_tags.update(t for t in [previous_wf.get("tag")] if t)
            taken_tags.update(st["tag"] for st in previous_wf.get("steps", {}).values() if st.get("tag"))

        workflow_ids: dict[str, int] = {}
        # Per workflow name → step name → step id (for recommendation step_id).
        step_ids: dict[str, dict[str, int]] = {}
        for index, raw in enumerate(workflows):
            if not isinstance(raw, dict):
                continue
            name = _workflow_name(raw, index)
            agent_diagram = str(raw.get("diagram_mermaid") or "")
            # Owner edits live on the workflow row, which a re-analysis
            # replaces: the matched previous workflow carries them over.
            previous_wf = previous_for.get(index)
            diagram, owner_flag, proposed, dismissed = _diagram_for_ingest(agent_diagram, previous_wf)
            wf_id = (
                await conn.execute(
                    text("""
                        INSERT INTO ai_workflows
                            (analysis_id, name, trigger_summary, diagram_mermaid, sort_order, tag,
                             status, deleted_at, previous_workflow_id,
                             diagram_set_by_owner, proposed_diagram_mermaid, dismissed_diagram_mermaid)
                        VALUES
                            (:analysis_id, :name, :trigger_summary, :diagram, :sort_order, :tag,
                             :status, :deleted_at, :previous_workflow_id,
                             :diagram_set_by_owner, :proposed, :dismissed)
                        RETURNING id
                        """),
                    {
                        "analysis_id": analysis_id,
                        "name": name,
                        "trigger_summary": _str_or_none(raw.get("trigger_summary")),
                        "diagram": diagram,
                        "sort_order": _sort_order(raw, index),
                        "tag": (previous_wf or {}).get("tag")
                        or unique_workflow_tag(normalize_workflow_tag(raw.get("tag")), taken_tags),
                        "status": (previous_wf or {}).get("status") or "active",
                        "deleted_at": (previous_wf or {}).get("deleted_at"),
                        "previous_workflow_id": (previous_wf or {}).get("id"),
                        "diagram_set_by_owner": owner_flag,
                        "proposed": proposed,
                        "dismissed": dismissed,
                    },
                )
            ).scalar_one()
            workflow_ids[name] = int(wf_id)
            step_ids[name] = await _insert_workflow_steps(
                conn,
                workflow_id=int(wf_id),
                raw_steps=raw.get("steps"),
                previous_steps=(previous_wf or {}).get("steps") or {},
                taken_tags=taken_tags,
            )
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
            # Sessions queued before the sla → slo rename still write the old
            # key; honour it rather than defaulting the tier.
            slo = str(raw.get("recommended_slo") or raw.get("recommended_sla") or "").strip()
            if slo not in VALID_SLOS:
                slo = "ux-high-prio"
            workflow_name = str(raw.get("workflow") or raw.get("workflow_name") or "").strip()
            step_name = str(raw.get("step") or raw.get("step_name") or "").strip()
            flags = raw.get("traffic_flags")
            confidence = raw.get("confidence")
            try:
                confidence_f = float(confidence) if confidence is not None else 0.5
            except (TypeError, ValueError):
                confidence_f = 0.5
            # Never trust a numeric workflow_id / step_id from the artifact —
            # resolve only via names created for this ingest.
            workflow_id = workflow_ids.get(workflow_name) if workflow_name else None
            step_id = None
            if workflow_name and step_name:
                step_id = step_ids.get(workflow_name, {}).get(step_name)
            parsed.append(
                {
                    "file_path": file_path,
                    "workflow_name": workflow_name,
                    "workflow_id": workflow_id,
                    "step_id": step_id,
                    "start_line": _int_or_none(raw.get("start_line")),
                    "end_line": _int_or_none(raw.get("end_line")),
                    "code_url": _str_or_none(raw.get("code_url")),
                    "detected_model": _str_or_none(raw.get("detected_model")),
                    "slo": slo,
                    "priority": normalize_objective_priority(raw.get("objective_priority"), slo=slo),
                    "confidence": confidence_f,
                    "justification": str(raw.get("justification") or ""),
                    "flags": json.dumps(flags if isinstance(flags, dict) else {}),
                }
            )

        predecessors = match_recommendations(previous_recs, parsed)
        for index, rec in enumerate(parsed):
            previous = predecessors.get(index)
            review = carried_review(
                previous.get("decision") if previous else None, slo=rec["slo"], priority=rec["priority"]
            )
            owner_model = previous is not None and bool(previous["model_set_by_owner"])
            await conn.execute(
                text("""
                    INSERT INTO ai_llm_call_recommendations
                        (analysis_id, workflow_id, step_id, team_id, file_path, start_line, end_line,
                         code_url, detected_model, model_set_by_owner, recommended_slo, objective_priority,
                         confidence, justification, traffic_flags, review_status, review_carried_over,
                         confirmed_slo, confirmed_objective_priority, api_key_id, reviewed_by, reviewed_at,
                         previous_recommendation_id)
                    VALUES
                        (:analysis_id, :workflow_id, :step_id, :team_id, :file_path, :start_line, :end_line,
                         :code_url, :detected_model, :model_set_by_owner, :slo, CAST(:priority AS jsonb),
                         :confidence, :justification, CAST(:flags AS jsonb), :review_status, :carried_over,
                         :confirmed_slo, CAST(:confirmed_priority AS jsonb), :api_key_id, :reviewed_by, :reviewed_at,
                         :previous_id)
                    """),
                {
                    **review,
                    "carried_over": review["review_status"] != "pending",
                    "analysis_id": analysis_id,
                    "team_id": team_id,
                    "workflow_id": rec["workflow_id"],
                    "step_id": rec["step_id"],
                    "file_path": rec["file_path"],
                    "start_line": rec["start_line"],
                    "end_line": rec["end_line"],
                    "code_url": rec["code_url"],
                    # The owner said which model this call site uses; the analysis
                    # guessing again must not replace that.
                    "detected_model": previous["detected_model"] if owner_model else rec["detected_model"],
                    "model_set_by_owner": owner_model,
                    "previous_id": previous["id"] if previous is not None else None,
                    "slo": rec["slo"],
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


async def _insert_workflow_steps(
    conn: Any,
    *,
    workflow_id: int,
    raw_steps: object,
    previous_steps: dict[str, dict[str, Any]] | None = None,
    taken_tags: set[str] | None = None,
) -> dict[str, int]:
    """Insert ``ai_workflow_steps`` for one workflow. Returns name → id.

    Missing or empty ``steps`` is fine (backward compatible). Status /
    soft-delete live on the parent workflow. ``previous_steps`` (step name →
    row of the previous analysis) carries an owner-confirmed SLO and an
    established tag over to a same-named step.
    """
    names_to_ids: dict[str, int] = {}
    if not isinstance(raw_steps, list):
        return names_to_ids
    for index, raw in enumerate(raw_steps):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        # Same trimmed name twice would copy one predecessor's tag/SLO onto both.
        if name in names_to_ids:
            logger.warning(
                "skipping duplicate workflow step name %r on workflow %s",
                name,
                workflow_id,
            )
            continue
        slo = str(raw.get("recommended_slo") or raw.get("recommended_sla") or "").strip()
        if slo not in VALID_SLOS:
            slo = "ux-high-prio"
        previous = (previous_steps or {}).get(name) or {}
        confirmed_slo = previous.get("confirmed_slo")
        confirmed_priority = None
        if previous.get("confirmed_objective_priority") is not None:
            confirmed_priority = json.dumps(
                _priority_list(previous["confirmed_objective_priority"], slo=confirmed_slo or slo)
            )
        step_id = (
            await conn.execute(
                text("""
                    INSERT INTO ai_workflow_steps
                        (workflow_id, name, sort_order, tag, recommended_slo, objective_priority,
                         confirmed_slo, confirmed_objective_priority)
                    VALUES
                        (:workflow_id, :name, :sort_order, :tag, :slo, CAST(:priority AS jsonb),
                         :confirmed_slo, CAST(:confirmed_priority AS jsonb))
                    RETURNING id
                    """),
                {
                    "workflow_id": workflow_id,
                    "name": name,
                    "sort_order": _sort_order(raw, index),
                    "tag": previous.get("tag")
                    or unique_workflow_tag(normalize_workflow_tag(raw.get("tag")), taken_tags),
                    "slo": slo,
                    "priority": json.dumps(normalize_objective_priority(raw.get("objective_priority"), slo=slo)),
                    "confirmed_slo": confirmed_slo,
                    "confirmed_priority": confirmed_priority,
                },
            )
        ).scalar_one()
        names_to_ids[name] = int(step_id)
    return names_to_ids


async def _lock_team_tags(conn: Any, team_id: int, team_repository_id: int) -> set[str]:
    """Take the team's tag lock (shared with the webservice) and return the tags in use.

    The namespace is every other repository's latest succeeded analysis of the
    team — what the request resolvers match in. This repository's own tags
    are being replaced and come back through the carry-over.
    """
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('ai-workflow-tags'), :team_id)"),
        {"team_id": team_id},
    )
    rows = (
        (
            await conn.execute(
                text("""
                    WITH current_analyses AS (
                        SELECT a.id FROM ai_workflow_analyses a
                         WHERE a.team_id = :team_id
                           AND a.team_repository_id <> :repo
                           AND a.id = (
                                 SELECT latest.id FROM ai_workflow_analyses latest
                                  WHERE latest.team_repository_id = a.team_repository_id
                                    AND latest.status = 'succeeded'
                                  ORDER BY latest.finished_at DESC NULLS LAST, latest.id DESC
                                  LIMIT 1
                               )
                    )
                    SELECT w.tag AS tag FROM ai_workflows w
                     WHERE w.analysis_id IN (SELECT id FROM current_analyses) AND w.tag IS NOT NULL
                    UNION
                    SELECT s.tag AS tag FROM ai_workflow_steps s
                      JOIN ai_workflows w ON w.id = s.workflow_id
                     WHERE w.analysis_id IN (SELECT id FROM current_analyses) AND s.tag IS NOT NULL
                    """),
                {"team_id": team_id, "repo": team_repository_id},
            )
        )
        .mappings()
        .all()
    )
    return {str(r["tag"]) for r in rows}


def _workflow_name(raw: dict[str, Any], index: int) -> str:
    return str(raw.get("name") or "").strip() or f"workflow-{index + 1}"


def _workflow_key(name: str) -> str:
    """`Chat`, `chat` and `chat-flow` / `Chat flow` name the same workflow."""
    return re.sub(r"[^0-9a-z]+", " ", name.casefold()).strip()


def match_workflows(
    previous_workflows: list[dict[str, Any]],
    previous_recs: list[dict[str, Any]],
    workflows: list[Any],
    recommendations: list[Any],
) -> dict[int, dict[str, Any]]:
    """Pair each new workflow (by index) with its previous-analysis workflow.

    The agent names workflows freely on every run, so an exact name is not a
    stable identity. Match on the case- and punctuation-insensitive name first;
    the rest pair up by how many files their recommended call sites share,
    taking only mutually unique best pairs (repeated until none is left). Each
    previous workflow carries forward at most once.
    """
    entries = [(i, _workflow_name(raw, i)) for i, raw in enumerate(workflows) if isinstance(raw, dict)]
    matched: dict[int, dict[str, Any]] = {}
    used: set[int] = set()
    by_key: dict[str, int] = {}
    for p_index, prev in enumerate(previous_workflows):
        key = _workflow_key(str(prev.get("name") or ""))
        if key:
            by_key.setdefault(key, p_index)
    for index, name in entries:
        p_index = by_key.get(_workflow_key(name))
        if p_index is not None and p_index not in used:
            matched[index] = previous_workflows[p_index]
            used.add(p_index)

    prev_files: dict[str, set[str]] = {}
    for rec in previous_recs:
        if rec.get("workflow_name") and rec.get("file_path"):
            prev_files.setdefault(_workflow_key(str(rec["workflow_name"])), set()).add(str(rec["file_path"]))
    new_files: dict[str, set[str]] = {}
    for rec in recommendations:
        if isinstance(rec, dict) and rec.get("file_path"):
            wf = str(rec.get("workflow") or rec.get("workflow_name") or "")
            new_files.setdefault(_workflow_key(wf), set()).add(str(rec["file_path"]).strip())
    for i, raw in enumerate(workflows):
        nested = raw.get("recommendations") if isinstance(raw, dict) else None
        for rec in nested if isinstance(nested, list) else []:
            if isinstance(rec, dict) and rec.get("file_path"):
                key = _workflow_key(_workflow_name(raw, i))
                new_files.setdefault(key, set()).add(str(rec["file_path"]).strip())

    # Score every unmatched pair, then take only pairs that are each other's
    # unique best; drop them and repeat, so neither list order nor an earlier
    # tie decides who keeps an owner diagram. Ambiguous pairs stay unmatched.
    while True:
        scores: dict[tuple[int, int], int] = {}
        for p_index, prev in enumerate(previous_workflows):
            if p_index in used:
                continue
            files = prev_files.get(_workflow_key(str(prev.get("name") or "")), set())
            for index, name in entries:
                if index in matched:
                    continue
                overlap = len(files & new_files.get(_workflow_key(name), set()))
                if overlap:
                    scores[(p_index, index)] = overlap
        best_for_prev = _unique_best(scores, side=0)
        best_for_new = _unique_best(scores, side=1)
        pairs = [(p_index, index) for p_index, index in best_for_prev.items() if best_for_new.get(index) == p_index]
        if not pairs:
            break
        for p_index, index in pairs:
            matched[index] = previous_workflows[p_index]
            used.add(p_index)
    return matched


def _unique_best(scores: dict[tuple[int, int], int], *, side: int) -> dict[int, int]:
    """For each key on ``side`` of the pairs, its single highest-scoring partner (ties: none)."""
    ranked: dict[int, list[tuple[int, int]]] = {}
    for pair, score in scores.items():
        ranked.setdefault(pair[side], []).append((score, pair[1 - side]))
    best: dict[int, int] = {}
    for key, options in ranked.items():
        options.sort(reverse=True)
        if len(options) == 1 or options[1][0] < options[0][0]:
            best[key] = options[0][1]
    return best


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

    Matched by :func:`match_workflows` when carrying owner edits forward:
    diagrams, lifecycle, tags, and — under ``steps`` (step name → row) —
    step tags and confirmed SLOs. The caller holds the repository row lock;
    owner edits take it too.
    """
    rows = (
        (
            await conn.execute(
                text("""
                    SELECT w.id, w.name, w.diagram_mermaid, w.diagram_set_by_owner,
                           w.proposed_diagram_mermaid, w.dismissed_diagram_mermaid,
                           w.status, w.deleted_at, w.tag
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
    previous = [dict(r) for r in rows]
    for p in previous:
        p["steps"] = {}
    ids = [int(p["id"]) for p in previous if p.get("id") is not None]
    if not ids:
        return previous
    step_rows = (
        (
            await conn.execute(
                text("""
                    SELECT s.workflow_id, s.name, s.tag, s.confirmed_slo, s.confirmed_objective_priority
                      FROM ai_workflow_steps s
                     WHERE s.workflow_id = ANY(:ids)
                     ORDER BY s.id
                    """),
                {"ids": ids},
            )
        )
        .mappings()
        .all()
    )
    by_id = {int(p["id"]): p for p in previous if p.get("id") is not None}
    for row in step_rows:
        workflow = by_id.get(int(row["workflow_id"]))
        if workflow is not None:
            workflow["steps"].setdefault(
                str(row["name"]),
                {
                    "tag": row["tag"],
                    "confirmed_slo": row["confirmed_slo"],
                    "confirmed_objective_priority": row["confirmed_objective_priority"],
                },
            )
    return previous


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
                           d.id, d.review_status, d.recommended_slo, d.objective_priority,
                           d.confirmed_slo, d.confirmed_objective_priority,
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


def _priority_list(raw: Any, *, slo: str) -> list[str]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = None
    return normalize_objective_priority(raw, slo=slo)


def carried_review(previous: dict[str, Any] | None, *, slo: str, priority: list[str]) -> dict[str, Any]:
    """Review fields for a new recommendation, given the last reviewed decision it inherits.

    A re-analysis proposes; it never overwrites a decision. When the new
    proposal is what the owner already confirmed (or already rejected), that
    review carries over unchanged. Anything else is pending, and the UI shows
    it next to the previous decision.
    """
    pending: dict[str, Any] = {
        "review_status": "pending",
        "confirmed_slo": None,
        "confirmed_priority": None,
        "api_key_id": None,
        "reviewed_by": None,
        "reviewed_at": None,
    }
    if previous is None:
        return pending
    status = previous["review_status"]
    if status in ("accepted", "overridden"):
        confirmed_slo = previous["confirmed_slo"] or previous["recommended_slo"]
        confirmed = _priority_list(
            previous["confirmed_objective_priority"] or previous["objective_priority"], slo=confirmed_slo
        )
        if (slo, priority) != (confirmed_slo, confirmed):
            return pending
        return {
            "review_status": status,
            "confirmed_slo": confirmed_slo,
            "confirmed_priority": json.dumps(confirmed),
            "api_key_id": previous["api_key_id"],
            "reviewed_by": previous["reviewed_by"],
            "reviewed_at": previous["reviewed_at"],
        }
    if status == "rejected":
        rejected_slo = previous["recommended_slo"]
        if (slo, priority) != (rejected_slo, _priority_list(previous["objective_priority"], slo=rejected_slo)):
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


def _sort_order(raw: dict[str, Any], index: int) -> int:
    """Prefer a numeric ``sort_order``; fall back to the list index on missing/invalid."""
    parsed = _int_or_none(raw.get("sort_order"))
    return index if parsed is None else parsed
