"""Queue read-only agent sessions that analyse linked team repositories.

Linked application repos (``team_repositories``) need AI-workflow diagrams and
SLA recommendations. Owners can trigger that from the UI; this poller also
queues spare-capacity analysis when a link has no succeeded analysis yet (or
none for the commit it last recorded — until a HEAD match exists, "none at
all" is the practical signal).

Sessions are ``no_push``, ``trigger_kind=analysis``, low priority, and write
``/artifacts/analysis.json`` for :mod:`analysis_ingest`.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import text

from . import controls, db, model_policy
from .config import settings
from .schemas import ACTIVE_STATUSES, SessionStatus

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 300.0
CREATED_BY = "logos-agent (analysis)"
# Below issue (50) / comment (70) so application analysis yields to Logos work.
ANALYSIS_PRIORITY = 10
ANALYSIS_PRIORITY_REASON = "workflow analysis — spare capacity"


ANALYSIS_TASK = """\
Analyse this linked application repository for AI / LLM call sites and produce
workflow diagrams plus SLA recommendations.

Write structured results ONLY to `/artifacts/analysis.json` (UTF-8 JSON).
Do not push commits, open pull requests, or modify the remote.

Schema for `/artifacts/analysis.json`:
{{
  "commit_sha": "<git HEAD sha of the checkout you analysed>",
  "workflows": [
    {{
      "name": "<short workflow group name>",
      "trigger_summary": "<what starts this flow>",
      "diagram_mermaid": "flowchart TD\\n  A-->B",
      "sort_order": 0
    }}
  ],
  "recommendations": [
    {{
      "workflow": "<matching workflows[].name>",
      "file_path": "path/from/repo/root.py",
      "start_line": 1,
      "end_line": 20,
      "code_url": "optional permalink to the call site, or null",
      "detected_model": "optional model name or null",
      "recommended_sla": "ux-critical" | "ux-high-prio" | "ux-background",
      "objective_priority": ["latency" | "quality" | "price", "..."],
      "confidence": 0.0,
      "justification": "why this SLA and objective order",
      "traffic_flags": {{"night_heavy": false}}
    }}
  ]
}}

`objective_priority` is a full ranking of latency, quality, and price (most
important first). It complements SLA: SLA is urgency/interactivity; the ranking
says what to optimize for when choosing a model. If omitted, defaults are:
ux-critical → [latency, quality, price]; ux-high-prio → [quality, latency, price];
ux-background → [price, quality, latency].

Repository: {repo_slug}
Clone URL: {repo_url}
Focus paths (empty means whole tree): {paths}
"""


class AnalysisPoller:
    """Periodically queues analysis sessions for team repository links."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._last_error: str = ""
        self._last_pass: datetime | None = None
        self._queued_total = 0
        self.on_queued: Callable[[], Awaitable[None]] | None = None

    async def start(self) -> None:
        if not settings.triggers_enabled:
            logger.info("analysis poller off (LOGOS_AGENT_TRIGGERS_ENABLED=false)")
            return
        self._task = asyncio.create_task(self._loop(), name="agent-analysis-triggers")
        logger.info("watching team repositories for workflow analysis every %.0fs", POLL_INTERVAL_S)

    async def stop(self) -> None:
        self._stopping.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = str(exc)
                logger.warning("analysis poll failed: %s", exc)
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=POLL_INTERVAL_S)
            except asyncio.TimeoutError:
                pass

    async def poll_once(self) -> list[int]:
        """Queue analysis for links that still need it. Returns session ids."""
        now = datetime.now(timezone.utc)
        await self._reconcile_stale_analyses()
        control = await controls.current()
        blocked = control.admission_block()
        if blocked:
            logger.debug("analysis poll skipped: %s", blocked)
            self._last_pass = now
            return []
        policy = model_policy.current()
        if not policy.ok:
            logger.debug("analysis poll skipped: %s", policy.detail)
            self._last_pass = now
            return []

        links = await self._links_needing_analysis()
        self._last_pass = now
        self._last_error = ""
        if not links:
            return []

        queued: list[int] = []
        for link in links:
            session_id = await self._queue(link)
            if session_id is not None:
                queued.append(session_id)
        if queued and self.on_queued is not None:
            try:
                await self.on_queued()
            except Exception as exc:
                logger.info("scheduler nudge after analysis queue failed: %s", exc)
        return queued

    async def _reconcile_stale_analyses(self) -> None:
        """Mark queued/running analyses failed when their session is terminal."""
        terminal = [
            SessionStatus.FAILED.value,
            SessionStatus.CANCELLED.value,
            SessionStatus.SUCCEEDED.value,
        ]
        async with db.sessionmaker()() as conn:
            await conn.execute(
                text("""
                    UPDATE ai_workflow_analyses a
                       SET status = 'failed',
                           error = COALESCE(a.error, 'agent session ended without ingest'),
                           finished_at = COALESCE(a.finished_at, :now)
                      FROM agent_sessions s
                     WHERE a.agent_session_id = s.id
                       AND a.status IN ('queued', 'running')
                       AND s.status = ANY(:terminal)
                       AND NOT EXISTS (
                             SELECT 1 FROM ai_workflow_analyses ok
                              WHERE ok.agent_session_id = s.id
                                AND ok.status = 'succeeded'
                           )
                    """),
                {"now": datetime.now(timezone.utc), "terminal": terminal},
            )
            # Succeeded sessions that never produced a succeeded analysis row
            # (ingest skipped / failed) are covered above. Also clear orphaned
            # queued rows whose session row is gone.
            await conn.execute(
                text("""
                    UPDATE ai_workflow_analyses a
                       SET status = 'failed',
                           error = COALESCE(a.error, 'agent session missing'),
                           finished_at = COALESCE(a.finished_at, :now)
                     WHERE a.status IN ('queued', 'running')
                       AND a.agent_session_id IS NOT NULL
                       AND NOT EXISTS (
                             SELECT 1 FROM agent_sessions s WHERE s.id = a.agent_session_id
                           )
                    """),
                {"now": datetime.now(timezone.utc)},
            )
            await conn.commit()

    async def _links_needing_analysis(self) -> list[dict[str, Any]]:
        """Team repos with no succeeded analysis, and nothing already in flight.

        "Current commit" matching needs a HEAD lookup the poller does not do
        yet: until then, any succeeded row counts as covered. A failed-only
        history is re-queued once nothing is queued/running.
        """
        async with db.sessionmaker()() as conn:
            rows = (
                (
                    await conn.execute(
                        text("""
                        SELECT tr.id, tr.team_id, tr.repo_url, tr.repo_slug,
                               tr.branch, tr.paths
                          FROM team_repositories tr
                         WHERE NOT EXISTS (
                                 SELECT 1 FROM ai_workflow_analyses a
                                  WHERE a.team_repository_id = tr.id
                                    AND a.status = 'succeeded'
                               )
                           AND NOT EXISTS (
                                 SELECT 1 FROM ai_workflow_analyses a
                                  WHERE a.team_repository_id = tr.id
                                    AND a.status IN ('queued', 'running')
                               )
                           AND NOT EXISTS (
                                 SELECT 1 FROM agent_sessions s
                                  WHERE s.team_repository_id = tr.id
                                    AND s.trigger_kind = 'analysis'
                                    AND s.status = ANY(:active)
                               )
                         ORDER BY tr.id
                         LIMIT 20
                        """),
                        {"active": [s.value for s in ACTIVE_STATUSES]},
                    )
                )
                .mappings()
                .all()
            )
        return [dict(r) for r in rows]

    async def _queue(self, link: dict[str, Any]) -> int | None:
        link_id = int(link["id"])
        team_id = int(link["team_id"])
        repo_url = str(link["repo_url"])
        repo_slug = str(link["repo_slug"])
        branch = str(link.get("branch") or "main")
        paths = link.get("paths")
        paths_label = ", ".join(paths) if isinstance(paths, list) and paths else "(entire repository)"
        trigger_ref = f"team-repository:{link_id}"

        workspace_id = await self._ensure_workspace(team_id, link_id, branch)
        if workspace_id is None:
            return None

        task = ANALYSIS_TASK.format(
            repo_slug=repo_slug,
            repo_url=repo_url,
            paths=paths_label,
        )
        try:
            session_id = await db.create_session(
                workspace_id=workspace_id,
                task=task,
                model=None,
                created_by=CREATED_BY,
                open_pull_request=False,
                deploy_to_dev=False,
                screenshot_paths=[],
                no_push=True,
                trigger_kind="analysis",
                trigger_ref=trigger_ref,
                priority=ANALYSIS_PRIORITY,
                priority_reason=ANALYSIS_PRIORITY_REASON,
                repo_url=repo_url,
                repo_slug=repo_slug,
                team_repository_id=link_id,
            )
        except ValueError as exc:
            logger.warning("could not queue analysis for team_repository %s: %s", link_id, exc)
            return None

        try:
            await self._insert_queued_analysis(team_id, link_id, session_id)
        except Exception as exc:
            logger.warning(
                "queued session %s but could not insert ai_workflow_analyses: %s",
                session_id,
                exc,
            )

        self._queued_total += 1
        logger.info("queued analysis session %s for %s", session_id, repo_slug)
        return session_id

    async def _ensure_workspace(self, team_id: int, link_id: int, branch: str) -> int | None:
        name = f"analysis-team-{team_id}-repo-{link_id}"
        try:
            # Upsert always so a reused / revived workspace picks up branch edits.
            created = await db.create_workspace(
                name=name,
                base_branch=branch,
                created_by=CREATED_BY,
                ephemeral=True,
            )
            return int(created["id"])
        except ValueError:
            # Live workspace of the same name: update base_branch in place.
            async with db.sessionmaker()() as conn:
                row = (
                    (
                        await conn.execute(
                            text("""
                            UPDATE agent_workspaces
                               SET base_branch = :branch
                             WHERE name = :name AND archived_at IS NULL
                         RETURNING id
                            """),
                            {"name": name, "branch": branch},
                        )
                    )
                    .mappings()
                    .first()
                )
                await conn.commit()
            if row is None:
                logger.info("analysis workspace %s unavailable", name)
                return None
            return int(row["id"])

    async def _insert_queued_analysis(self, team_id: int, link_id: int, session_id: int) -> None:
        async with db.sessionmaker()() as conn:
            await conn.execute(
                text("""
                    INSERT INTO ai_workflow_analyses
                        (team_id, team_repository_id, status, source, agent_session_id, started_at)
                    VALUES
                        (:team_id, :repo_id, 'queued', 'agent', :session_id, :now)
                    """),
                {
                    "team_id": team_id,
                    "repo_id": link_id,
                    "session_id": session_id,
                    "now": datetime.now(timezone.utc),
                },
            )
            await conn.commit()

    def status(self) -> dict[str, Any]:
        return {
            "enabled": settings.triggers_enabled,
            "polling": self._task is not None and not self._task.done(),
            "poll_interval_s": POLL_INTERVAL_S,
            "last_pass": self._last_pass.isoformat() if self._last_pass else None,
            "queued_total": self._queued_total,
            "last_error": self._last_error,
        }


poller = AnalysisPoller()
