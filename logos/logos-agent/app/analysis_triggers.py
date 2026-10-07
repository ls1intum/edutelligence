"""Queue read-only agent sessions that analyse linked team repositories.

Linked application repos (``team_repositories``) need AI-workflow diagrams and
SLO recommendations. Owners can trigger that from the UI; this poller also
queues spare-capacity analysis when a link has no succeeded analysis yet, and
once a night (``LOGOS_AGENT_ANALYSIS_NIGHTLY_HOUR_UTC``) for every analysed
link whose branch head moved past the analysed commit.

Sessions are ``no_push``, ``trigger_kind=analysis``, low priority, and write
``/artifacts/analysis.json`` for :mod:`analysis_ingest`.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from . import controls, db, github, model_policy
from .config import settings
from .schemas import ACTIVE_STATUSES, SessionStatus

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 300.0
# A queued analysis row is attached to its session within one queue call.
UNATTACHED_SLOT_TTL = timedelta(minutes=10)
CREATED_BY = "logos-agent (analysis)"
# Below issue (50) / comment (70) so application analysis yields to Logos work.
ANALYSIS_PRIORITY = 10
ANALYSIS_PRIORITY_REASON = "workflow analysis — spare capacity"


ANALYSIS_TASK = """\
Analyse this linked application repository for AI / LLM call sites and produce
workflow diagrams plus SLO recommendations.

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
      "recommended_slo": "ux-critical" | "ux-high-prio" | "ux-background",
      "objective_priority": ["latency" | "quality" | "price", "..."],
      "confidence": 0.0,
      "justification": "why this SLO and objective order",
      "traffic_flags": {{"night_heavy": false}}
    }}
  ]
}}

`diagram_mermaid` must parse with Mermaid 11: wrap every node and edge label
in double quotes (`A["Session title LLM (deferred)"]`, `B{{"EXERCISE mode?"}}`,
`A -->|"yes"| B`). Parentheses, brackets, braces, pipes or slashes inside an
unquoted label are syntax errors and the diagram will not render.

`objective_priority` is a full ranking of latency, quality, and price (most
important first). It complements SLO: SLO is urgency/interactivity; the ranking
says what to optimize for when choosing a model. If omitted, defaults are:
ux-critical → [latency, quality, price]; ux-high-prio → [quality, latency, price];
ux-background → [price, quality, latency].

Repository: {repo_slug}
Clone URL: {repo_url}
Focus paths (empty means whole tree): {paths}
"""

# Appended for a nightly run whose branch head the runner could not look up
# (e.g. a private repository): the session itself stops at once when nothing
# changed, instead of analysing the same commit again.
UNCHANGED_CHECK = """
The previous analysis described commit {previous_commit}. Before anything else
run `git rev-parse HEAD`. If it prints that commit, the repository has not
changed: write `{{"unchanged": true, "commit_sha": "{previous_commit}"}}` to
`/artifacts/analysis.json` and stop immediately, without analysing anything.
"""


class AnalysisPoller:
    """Periodically queues analysis sessions for team repository links."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._last_error: str = ""
        self._last_pass: datetime | None = None
        self._queued_total = 0
        # The UTC date whose nightly re-analysis already ran. Lost on restart,
        # which is harmless: a second pass that night finds every head unchanged.
        self._nightly_done_for: date | None = None
        self._skipped_unchanged_total = 0
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

        queued: list[int] = []
        for link in links:
            session_id = await self._queue(link)
            if session_id is not None:
                queued.append(session_id)
        if self._nightly_due(now):
            queued.extend(await self._nightly_pass())
            # Only a pass that got through counts: one that raised is retried
            # by the next poll within the same hour.
            self._nightly_done_for = now.date()
        if not queued:
            return []
        if queued and self.on_queued is not None:
            try:
                await self.on_queued()
            except Exception as exc:
                logger.info("scheduler nudge after analysis queue failed: %s", exc)
        return queued

    def _nightly_due(self, now: datetime) -> bool:
        hour = settings.analysis_nightly_hour_utc
        return 0 <= hour <= 23 and now.hour == hour and self._nightly_done_for != now.date()

    async def _nightly_pass(self) -> list[int]:
        """Re-analyse every analysed repository whose branch moved on.

        A repository whose head is still the commit of its latest succeeded
        analysis is skipped outright. When the head cannot be looked up, the
        session is queued with the previous commit and stops by itself if it
        finds the same one.
        """
        queued: list[int] = []
        skipped = 0
        for link in await self._links_for_nightly():
            previous = str(link.get("last_commit") or "").strip() or None
            head = await github.branch_head(str(link["repo_slug"]), str(link.get("branch") or "main"))
            if head is not None and previous is not None and head == previous:
                skipped += 1
                logger.info("nightly analysis of %s skipped: still at %s", link["repo_slug"], head[:12])
                continue
            session_id = await self._queue(link, previous_commit=previous if head is None else None)
            if session_id is not None:
                queued.append(session_id)
        self._skipped_unchanged_total += skipped
        logger.info("nightly analysis pass: %s queued, %s unchanged", len(queued), skipped)
        return queued

    async def _links_for_nightly(self) -> list[dict[str, Any]]:
        """Repositories with a succeeded analysis and nothing in flight, with that analysis' commit."""
        async with db.sessionmaker()() as conn:
            rows = (
                (
                    await conn.execute(
                        text("""
                        SELECT tr.id, tr.team_id, tr.repo_url, tr.repo_slug, tr.branch, tr.paths,
                               (SELECT a.commit_sha FROM ai_workflow_analyses a
                                 WHERE a.team_repository_id = tr.id
                                   AND a.status IN ('succeeded', 'skipped')
                                 ORDER BY a.finished_at DESC NULLS LAST, a.id DESC
                                 LIMIT 1) AS last_commit
                          FROM team_repositories tr
                         WHERE EXISTS (
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
                        """),
                        {"active": [s.value for s in ACTIVE_STATUSES]},
                    )
                )
                .mappings()
                .all()
            )
        return [dict(r) for r in rows]

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
            # A claimed slot whose session never got attached (the runner died
            # in between) would block the repository for good.
            await conn.execute(
                text("""
                    UPDATE ai_workflow_analyses
                       SET status = 'failed',
                           error = COALESCE(error, 'queued without a session'),
                           finished_at = COALESCE(finished_at, :now)
                     WHERE status = 'queued'
                       AND agent_session_id IS NULL
                       AND started_at < :stale_before
                    """),
                {"now": datetime.now(timezone.utc), "stale_before": datetime.now(timezone.utc) - UNATTACHED_SLOT_TTL},
            )
            await conn.commit()

    async def _links_needing_analysis(self) -> list[dict[str, Any]]:
        """Team repos with no succeeded analysis, and nothing already in flight.

        Any succeeded row counts as covered here; analysed repositories are
        revisited by the nightly pass, which compares the branch head with the
        analysed commit. A failed-only history is re-queued once nothing is
        queued/running.
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

    async def _queue(self, link: dict[str, Any], *, previous_commit: str | None = None) -> int | None:
        link_id = int(link["id"])
        team_id = int(link["team_id"])
        repo_url = str(link["repo_url"])
        repo_slug = str(link["repo_slug"])
        branch = str(link.get("branch") or "main")
        paths = link.get("paths")
        paths_label = ", ".join(paths) if isinstance(paths, list) and paths else "(entire repository)"
        trigger_ref = f"team-repository:{link_id}"

        # The analysis row first: the partial unique index on in-flight
        # analyses admits one per repository across this poller and the
        # webservice's individual and bulk queueing, so a lost race ends here,
        # before any session exists.
        analysis_id = await self._insert_queued_analysis(team_id, link_id)
        if analysis_id is None:
            logger.info("analysis of %s already queued or running; not queueing another", repo_slug)
            return None

        workspace_id = await self._ensure_workspace(team_id, link_id, branch)
        if workspace_id is None:
            await self._drop_queued_analysis(analysis_id)
            return None

        task = ANALYSIS_TASK.format(
            repo_slug=repo_slug,
            repo_url=repo_url,
            paths=paths_label,
        )
        if previous_commit:
            task += UNCHANGED_CHECK.format(previous_commit=previous_commit)
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
            await self._drop_queued_analysis(analysis_id)
            return None

        await self._attach_session(analysis_id, session_id)

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

    async def _insert_queued_analysis(self, team_id: int, link_id: int) -> int | None:
        """Claim the repository's in-flight slot, or None when another writer holds it."""
        async with db.sessionmaker()() as conn:
            try:
                analysis_id = (
                    await conn.execute(
                        text("""
                            INSERT INTO ai_workflow_analyses
                                (team_id, team_repository_id, status, source, started_at)
                            VALUES
                                (:team_id, :repo_id, 'queued', 'agent', :now)
                            RETURNING id
                            """),
                        {"team_id": team_id, "repo_id": link_id, "now": datetime.now(timezone.utc)},
                    )
                ).scalar_one()
            except IntegrityError:
                await conn.rollback()
                return None
            await conn.commit()
        return int(analysis_id)

    async def _attach_session(self, analysis_id: int, session_id: int) -> None:
        async with db.sessionmaker()() as conn:
            await conn.execute(
                text("UPDATE ai_workflow_analyses SET agent_session_id = :session_id WHERE id = :id"),
                {"session_id": session_id, "id": analysis_id},
            )
            await conn.commit()

    async def _drop_queued_analysis(self, analysis_id: int) -> None:
        """Release a claimed slot whose session could not be created."""
        async with db.sessionmaker()() as conn:
            await conn.execute(
                text("DELETE FROM ai_workflow_analyses WHERE id = :id AND agent_session_id IS NULL"),
                {"id": analysis_id},
            )
            await conn.commit()

    def status(self) -> dict[str, Any]:
        return {
            "enabled": settings.triggers_enabled,
            "polling": self._task is not None and not self._task.done(),
            "poll_interval_s": POLL_INTERVAL_S,
            "last_pass": self._last_pass.isoformat() if self._last_pass else None,
            "queued_total": self._queued_total,
            "nightly_hour_utc": settings.analysis_nightly_hour_utc,
            "nightly_done_for": self._nightly_done_for.isoformat() if self._nightly_done_for else None,
            "skipped_unchanged_total": self._skipped_unchanged_total,
            "last_error": self._last_error,
        }


poller = AnalysisPoller()
