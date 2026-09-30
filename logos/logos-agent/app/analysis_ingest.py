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
# Cap memory: an agent-written artifact must not exhaust the runner.
MAX_ANALYSIS_BYTES = 2 * 1024 * 1024


def artifact_analysis_path(session_id: int) -> Path:
    return Path(settings.artifact_root) / str(session_id) / ANALYSIS_FILE


def read_analysis_artifact(path: Path) -> bytes:
    """Read ``analysis.json`` without following symlinks, as a regular file only.

    The agent sandbox can create ``analysis.json -> ../other-session/...``.
    Following that would let one session ingest another team's private
    workflows. ``O_NOFOLLOW`` rejects a final-component symlink; ``fstat``
    confirms a regular file; the read is byte-capped.
    """
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
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
    try:
        await upsert_analysis(
            session_id=session_id,
            team_repository_id=int(team_repository_id),
            payload=payload,
        )
    except Exception as exc:
        logger.warning("analysis ingest for session %s failed: %s", session_id, exc)
        await mark_analysis_failed(session_id, str(exc))


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
        team_id = (
            await conn.execute(
                text("SELECT team_id FROM team_repositories WHERE id = :id"),
                {"id": team_repository_id},
            )
        ).scalar_one_or_none()
        if team_id is None:
            raise ValueError(f"team_repository {team_repository_id} does not exist")

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
            await conn.execute(
                text("""
                    INSERT INTO ai_llm_call_recommendations
                        (analysis_id, workflow_id, team_id, file_path, start_line, end_line,
                         code_url, detected_model, recommended_sla, confidence, justification,
                         traffic_flags, review_status)
                    VALUES
                        (:analysis_id, :workflow_id, :team_id, :file_path, :start_line, :end_line,
                         :code_url, :detected_model, :sla, :confidence, :justification,
                         CAST(:flags AS jsonb), 'pending')
                    """),
                {
                    "analysis_id": analysis_id,
                    "workflow_id": workflow_id,
                    "team_id": team_id,
                    "file_path": file_path,
                    "start_line": _int_or_none(raw.get("start_line")),
                    "end_line": _int_or_none(raw.get("end_line")),
                    "code_url": _str_or_none(raw.get("code_url")),
                    "detected_model": _str_or_none(raw.get("detected_model")),
                    "sla": sla,
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
