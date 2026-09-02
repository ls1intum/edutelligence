"""Queueing work the repository asked for, without anyone asking the runner.

Two things happen in a repository that an agent can act on without being
told: an issue is opened, and a review asks a pull request for changes. This
module watches for both and queues a session for each — the same sessions an
operator would have created by hand, with the same capacity gating, the same
local-only model policy, and the same isolation.

**Opt-in by label.** Only issues and pull requests carrying `logos-agent`
are picked up. The repository is shared with people who did not ask for an
agent to answer their issue, and "everything that moves" would be a promise
this runner has no business making. The label is the promise.

**Polling, not webhooks.** A webhook needs an endpoint GitHub can reach, and
this service is deliberately reachable only from the stack's own network.
The trade is minutes of latency for work whose whole premise is "when the
GPUs are idle anyway".

**Idempotent by reference.** Every reaction is recorded on the session as the
thing it reacted to — `issue-812`, `pr-772-review-5085681761`. A poll that
sees the same issue or review again finds that session and queues nothing.
References are stable identities, not timestamps, so a restarted runner with
a fresh clock cannot duplicate work.

**Bounded.** At most a few self-queued sessions are active at once, and the
runner never crowds out an operator: the ceiling counts only sessions it
queued itself, and the parallel-session ceiling applies on top.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from . import db, github, model_policy
from .config import settings

logger = logging.getLogger(__name__)

# How often the repository is polled. Frequent enough that a review posted
# during a working day is picked up while its author is still around, rare
# enough to stay far inside GitHub's rate limits (a pass is a handful of
# requests).
POLL_INTERVAL_S = 120.0

# How far back the first pass after a start looks. A runner that was down
# over a weekend must not wake up and queue the whole weekend at once; six
# hours is "what is currently going on", not "the backlog".
FIRST_PASS_LOOKBACK = timedelta(hours=6)

# How long a handled reference stays handled after its session finished.
# Long enough that a finished session is not re-queued by the next poll,
# short enough that a genuinely new review on the same pull request — which
# carries a new review id anyway — is never suppressed by it.
DEDUP_WINDOW = timedelta(days=7)

# The label that opts a thread into agent work.
LABEL = "logos-agent"

# The account sessions are attributed to when the runner queued them itself.
CREATED_BY = "logos-agent (trigger)"


def max_active_sessions() -> int:
    """How many self-queued sessions may be active at once.

    Derived rather than configured: half the parallel ceiling, at least one.
    The runner is a guest on this platform even when it is idle, and an
    operator who queues work by hand should always find room next to the
    automation.
    """
    return max(1, settings.max_parallel_sessions // 2)


def issue_task(issue: dict[str, Any]) -> str:
    """The task text for an opened issue.

    The issue's own words are the task; what this adds is the frame the
    session needs — where the work came from, and that it ends as a draft
    pull request a person reviews.
    """
    number = issue.get("number")
    title = str(issue.get("title") or "").strip()
    body = str(issue.get("body") or "").strip()
    if len(body) > 6000:
        body = body[:6000] + "\n\n[issue body truncated]"
    return (
        f"Work on this repository issue and open a draft pull request with your result.\n\n"
        f"Issue #{number}: {title}\n\n"
        f"{body}\n\n"
        f"Scope your change to what the issue asks for. Add or adjust tests for what you "
        f"change, and run the test suite and linters of the part of the repository you "
        f"touched before you finish. If the issue is unclear or turns out to be larger "
        f"than it looks, do the part you are confident about and say plainly in your "
        f"final message what you left out and why. Do not reference the issue number in "
        f"code comments, docstrings, or test names."
    )


def review_task(number: int, title: str, review: dict[str, Any]) -> str:
    """The task text for a review that asked a pull request for changes."""
    reviewer = str((review.get("user") or {}).get("login") or "a reviewer")
    body = str(review.get("body") or "").strip()
    if len(body) > 6000:
        body = body[:6000] + "\n\n[review body truncated]"
    return (
        f"A review on pull request #{number} ('{title}') asked for changes. Address it on "
        f"the same branch.\n\n"
        f"Review by {reviewer}:\n\n"
        f"{body}\n\n"
        f"Check each point against the current code before you change anything — lines "
        f"move, and some of it may already be addressed. Fix what is still valid, add "
        f"regression coverage for it, and run the tests and linters of the part you "
        f"touched. Reply to the review in English on GitHub, saying for each point what "
        f"you changed and how you verified it, or why it needed no change. Do not merge "
        f"the pull request and do not force-push."
    )


class TriggerPoller:
    """Polls the repository and queues sessions for what it finds."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        # Only reactions to things that happened after this are queued. It
        # starts one lookback window in the past and then follows the clock,
        # so a long-running runner reacts to what is new rather than to
        # everything the label has ever been on.
        self._since = datetime.now(timezone.utc) - FIRST_PASS_LOOKBACK
        self._last_error: str = ""
        self._last_pass: datetime | None = None
        self._queued_total = 0
        # Called after a pass queued something, so the work starts on the
        # next admission rather than at the scheduler's own tick. Set by the
        # service on startup; the poller does not import the session manager
        # itself, which keeps the dependency pointing one way.
        self.on_queued: Callable[[], Awaitable[None]] | None = None

    # --- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        if not settings.triggers_enabled:
            logger.info("repository triggers are off (LOGOS_AGENT_TRIGGERS_ENABLED)")
            return
        if not settings.github_token:
            logger.warning("repository triggers are on but no GitHub token is configured; not polling")
            return
        self._task = asyncio.create_task(self._loop(), name="agent-triggers")
        logger.info(
            "repository triggers on: polling %s every %.0fs for '%s' issues and reviews",
            settings.repo_slug,
            POLL_INTERVAL_S,
            LABEL,
        )

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
                # A failing poll is not a failing runner: sessions an
                # operator queued keep running, and the next pass tries
                # again.
                self._last_error = str(exc)
                logger.warning("trigger poll failed: %s", exc)
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=POLL_INTERVAL_S)
            except asyncio.TimeoutError:
                pass

    # --- one pass ---------------------------------------------------------

    async def poll_once(self) -> list[int]:
        """One look at the repository. Returns the sessions queued, if any."""
        now = datetime.now(timezone.utc)
        room = max_active_sessions() - await db.count_active_trigger_sessions()
        if room <= 0:
            # Nothing is dropped: the window only moves once the pass has
            # actually looked, so what is skipped here is seen again when a
            # session finishes.
            logger.debug("trigger poll skipped: already at %s self-queued sessions", max_active_sessions())
            self._last_pass = now
            return []

        candidates = await self._candidates(since=self._since)
        if not candidates:
            # Nothing was seen, so nothing can be left behind: the window
            # may follow the clock.
            self._since = now
            self._last_pass = now
            self._last_error = ""
            return []

        handled = await db.handled_trigger_refs(
            [candidate["ref"] for candidate in candidates],
            since=now - DEDUP_WINDOW,
        )
        queued: list[int] = []
        # A candidate this pass could not take on — the ceiling was reached,
        # no workspace was free, the model policy refused — must stay
        # visible to the next pass. The window is what makes it visible: the
        # listings filter by it, so moving it past an unqueued candidate
        # drops that work for good rather than deferring it.
        deferred = False
        for candidate in candidates:
            if candidate["ref"] in handled:
                continue
            if room <= 0:
                deferred = True
                continue
            session_id = await self._queue(candidate)
            if session_id is None:
                deferred = True
                continue
            queued.append(session_id)
            room -= 1
        self._last_pass = now
        self._last_error = ""
        if not deferred:
            # Only a pass that handled everything it saw may move on. A pass
            # that raised earlier leaves the window untouched for the same
            # reason.
            self._since = now
        if queued and self.on_queued is not None:
            await self.on_queued()
        return queued

    async def _candidates(self, *, since: datetime) -> list[dict[str, Any]]:
        """What the repository is asking for, oldest signal first."""
        found: list[dict[str, Any]] = []

        for issue in await github.labelled_issues(LABEL, since=since):
            number = issue.get("number")
            if not isinstance(number, int):
                continue
            found.append(
                {
                    "ref": f"issue-{number}",
                    "kind": "issue",
                    "task": issue_task(issue),
                    "title": str(issue.get("title") or ""),
                }
            )

        for entry in await github.labelled_pull_requests(LABEL):
            number = entry.get("number")
            if not isinstance(number, int):
                continue
            title = str(entry.get("title") or "")
            for review in await github.reviews_since(number, since):
                # Only a review that asks for changes is work. An approval
                # or a comment is a conversation, and answering it is a
                # person's call.
                if str(review.get("state") or "").upper() != "CHANGES_REQUESTED":
                    continue
                review_id = review.get("id")
                if not isinstance(review_id, int):
                    continue
                found.append(
                    {
                        "ref": f"pr-{number}-review-{review_id}",
                        "kind": "review",
                        "task": review_task(number, title, review),
                        "title": title,
                    }
                )
        return found

    async def _queue(self, candidate: dict[str, Any]) -> int | None:
        """Queue one session, making a workspace for it if none is free."""
        policy = model_policy.current()
        if not policy.ok:
            logger.info("not queueing %s: %s", candidate["ref"], policy.detail)
            return None
        workspace_id = await self._free_workspace()
        if workspace_id is None:
            # Every workspace is busy and the ceiling is reached. The
            # candidate is not recorded as handled, so the next pass — after
            # a session has finished — picks it up again.
            logger.info("not queueing %s: no free workspace", candidate["ref"])
            return None
        try:
            session_id = await db.create_session(
                workspace_id=workspace_id,
                task=candidate["task"],
                model=None,
                created_by=CREATED_BY,
                open_pull_request=True,
                # A session the runner queued by itself does not touch a
                # shared environment: deploying is an operator's decision,
                # made per session in the UI.
                deploy_to_dev=False,
                screenshot_paths=[],
                trigger_kind=candidate["kind"],
                trigger_ref=candidate["ref"],
            )
        except ValueError as exc:
            logger.warning("could not queue a session for %s: %s", candidate["ref"], exc)
            return None
        self._queued_total += 1
        logger.info("queued session %s for %s", session_id, candidate["ref"])
        return session_id

    async def _free_workspace(self) -> int | None:
        """A workspace no active session occupies, creating one if allowed.

        Sessions the runner queues have nobody to prepare a working copy for
        them, so it makes its own — up to the parallel ceiling, since a
        workspace beyond that could never be used anyway. Each is one Docker
        volume holding one shallow clone.
        """
        workspaces = await db.list_workspaces()
        for workspace in workspaces:
            if int(workspace.get("active_sessions") or 0) == 0:
                return int(workspace["id"])
        if len(workspaces) >= settings.max_parallel_sessions:
            return None
        name = f"auto-{len(workspaces) + 1}"
        try:
            created = await db.create_workspace(name=name, base_branch="main", created_by=CREATED_BY)
        except ValueError:
            # The name is taken by a workspace that is currently occupied:
            # leave it to the next pass rather than inventing another name.
            return None
        logger.info("created workspace '%s' for triggered work", name)
        return int(created["id"])

    # --- what the UI shows ------------------------------------------------

    def status(self) -> dict[str, Any]:
        return {
            "enabled": settings.triggers_enabled,
            "polling": self._task is not None and not self._task.done(),
            "label": LABEL,
            "poll_interval_s": POLL_INTERVAL_S,
            "max_active_sessions": max_active_sessions(),
            "last_pass": self._last_pass.isoformat() if self._last_pass else None,
            "queued_total": self._queued_total,
            "last_error": self._last_error,
        }


poller = TriggerPoller()


async def active_trigger_sessions() -> int:
    """How many self-queued sessions are active right now."""
    return await db.count_active_trigger_sessions()


__all__ = [
    "DEDUP_WINDOW",
    "FIRST_PASS_LOOKBACK",
    "LABEL",
    "POLL_INTERVAL_S",
    "TriggerPoller",
    "active_trigger_sessions",
    "issue_task",
    "max_active_sessions",
    "poller",
    "review_task",
]
