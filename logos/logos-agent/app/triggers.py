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


def _next_auto_name(existing: set[str]) -> str:
    """The lowest ``auto-N`` no workspace carries.

    Counting workspaces would repeat a name after a deletion — with `auto-1`
    and `auto-3` left, the count says `auto-3` — and every later poll would
    hit the same conflict and defer work while the ceiling still had room.
    """
    index = 1
    while f"auto-{index}" in existing:
        index += 1
    return f"auto-{index}"


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


def _inline_block(comments: list[dict[str, Any]]) -> str:
    """The review's inline comments, as the agent needs to read them.

    Each one carries where it is: most changes-requested reviews say almost
    nothing in the body and everything in the inline comments, so a task
    built from the body alone would ask an agent to fix nothing in
    particular.
    """
    rendered: list[str] = []
    for comment in comments:
        path = str(comment.get("path") or "?")
        line = comment.get("line") or comment.get("original_line") or "?"
        body = str(comment.get("body") or "").strip()
        if not body:
            continue
        if len(body) > 3000:
            body = body[:3000] + " […]"
        rendered.append(f"- {path}:{line}\n  {body}")
    if not rendered:
        return ""
    return "Inline comments:\n\n" + "\n\n".join(rendered[:30]) + "\n\n"


def review_task(number: int, title: str, review: dict[str, Any], comments: list[dict[str, Any]] | None = None) -> str:
    """The task text for a review that asked a pull request for changes."""
    reviewer = str((review.get("user") or {}).get("login") or "a reviewer")
    body = str(review.get("body") or "").strip()
    if len(body) > 6000:
        body = body[:6000] + "\n\n[review body truncated]"
    inline = _inline_block(comments or [])
    return (
        f"A review on pull request #{number} ('{title}') asked for changes. You are working "
        f"in a checkout of that pull request's own branch, and your commit updates it — "
        f"there is no new pull request to open.\n\n"
        f"Review by {reviewer}:\n\n"
        f"{body or '(no review body; the requested changes are the inline comments below)'}\n\n"
        f"{inline}"
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
            fresh = [
                review
                for review in await github.reviews_since(number, since)
                # Only a review that asks for changes is work. An approval
                # or a comment is a conversation, and answering it is a
                # person's call.
                if str(review.get("state") or "").upper() == "CHANGES_REQUESTED" and isinstance(review.get("id"), int)
            ]
            if not fresh:
                continue
            branch = await self._writable_head(number)
            if branch is None:
                continue
            for review in fresh:
                review_id = int(review["id"])
                comments = await github.review_comments(number, review_id)
                found.append(
                    {
                        "ref": f"pr-{number}-review-{review_id}",
                        "kind": "review",
                        "task": review_task(number, title, review, comments),
                        "title": title,
                        # The branch the work belongs on. A review session
                        # updates the pull request it answers; it does not
                        # open a second one.
                        "branch": branch,
                        "workspace": f"pr-{number}",
                    }
                )
        return found

    async def _writable_head(self, number: int) -> str | None:
        """The branch a review session may push, or None if there is none.

        Two conditions, both about not writing where the runner has no
        business writing. The head must live in this repository — a fork's
        branch is not ours to push, and the token could not do it anyway —
        and it must be under the agent branch prefix, which means the pull
        request is one the runner opened. A human's branch is exactly what
        `branch_for()` and the protected-branch rules exist to keep agent
        pushes away from, and a review on it stays a person's job.
        """
        try:
            pull = await github.pull_request(number)
        except Exception as exc:
            logger.warning("could not read pull request %s: %s", number, exc)
            return None
        ref, repo = github.head_of(pull)
        if not ref:
            logger.info("pull request %s has no usable head branch; skipping its review", number)
            return None
        if repo != settings.repo_slug:
            logger.info("pull request %s comes from '%s'; the runner does not push to forks", number, repo or "?")
            return None
        if not ref.startswith(settings.branch_prefix):
            logger.info(
                "pull request %s is on '%s', which is not an agent branch; its review is a person's to answer",
                number,
                ref,
            )
            return None
        return ref

    async def _queue(self, candidate: dict[str, Any]) -> int | None:
        """Queue one session, making a workspace for it if none is free."""
        policy = model_policy.current()
        if not policy.ok:
            logger.info("not queueing %s: %s", candidate["ref"], policy.detail)
            return None
        branch = candidate.get("branch")
        workspace_id = await self._free_workspace(
            base_branch=branch or "main",
            preferred_name=candidate.get("workspace"),
        )
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
                # A review session pushes to the pull request's own branch,
                # so the work lands where the review was written. Opening a
                # second pull request for it would answer a review with a
                # different pull request.
                branch=branch,
                open_pull_request=branch is None,
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

    async def _free_workspace(self, *, base_branch: str, preferred_name: str | None = None) -> int | None:
        """A free workspace whose checkout starts from ``base_branch``.

        Sessions the runner queues have nobody to prepare a working copy for
        them, so it makes its own — up to the parallel ceiling, since a
        workspace beyond that could never be used anyway. Each is one Docker
        volume holding one shallow clone.

        A free workspace already on the wanted branch is the cheapest answer;
        otherwise a new one is created, and only when the ceiling forbids
        that is a free workspace re-pointed at the branch. Re-pointing is
        safe: the base branch is what the preparation phase resets the
        checkout to, and a workspace with no active session holds nothing
        worth keeping.
        """
        workspaces = await db.list_workspaces()
        free = [w for w in workspaces if int(w.get("active_sessions") or 0) == 0]
        for workspace in free:
            if str(workspace.get("base_branch") or "") == base_branch:
                return int(workspace["id"])
        if len(workspaces) < settings.max_parallel_sessions:
            name = preferred_name or _next_auto_name({str(w.get("name") or "") for w in workspaces})
            try:
                created = await db.create_workspace(name=name, base_branch=base_branch, created_by=CREATED_BY)
            except ValueError:
                # The name belongs to a workspace that is currently
                # occupied — most often the one for this very pull request,
                # already working on an earlier review.
                logger.info("workspace '%s' is taken; deferring", name)
                return None
            logger.info("created workspace '%s' on '%s' for triggered work", name, base_branch)
            return int(created["id"])
        if free:
            workspace = free[0]
            await db.set_workspace_base_branch(int(workspace["id"]), base_branch)
            logger.info("repointed workspace '%s' at '%s'", workspace.get("name"), base_branch)
            return int(workspace["id"])
        return None

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
