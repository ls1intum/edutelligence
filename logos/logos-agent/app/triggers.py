"""Working with the agent the way you work with a colleague.

The agent has a GitHub account, and this module is what makes that account
usable like a person's. The gestures are the ordinary ones:

| What you do on GitHub | What the agent does |
|---|---|
| assign it an issue | works on the issue and opens a draft pull request |
| assign it a pull request | takes that pull request over, on its own branch |
| ask one of its pull requests for changes | addresses the review on that branch |
| comment on a pull request it is responsible for | reads the comment and answers it |
| mention it in any comment | answers there, and changes code only if that is what was asked |

No labels, no separate vocabulary. **Consent is per item:** nothing is picked
up because it exists, only because somebody assigned it, reviewed its work,
or asked it something by name.

**It says it heard you.** The moment a session is queued, the runner reacts
with 👀 on the thing that triggered it — so a question does not sit there
looking ignored while the platform waits for idle GPUs.

**It can answer.** The agent phase holds no GitHub credential, so it writes
its answer to a file in its artefact directory and the runner posts it when
the session settles. The reply is data produced by the untrusted phase; the
posting is done by the trusted one.

**Polling, not webhooks.** A webhook needs an endpoint GitHub can reach, and
this service is deliberately reachable only from the stack's own network.
The trade is minutes of latency for work whose whole premise is "when the
GPUs are idle anyway".

**Remembered by reference, forever.** Every reaction is recorded on the
session as the thing it reacted to — `issue-812`, `pr-772-assigned`,
`pr-772-review-5085681761`, `thread-772-3910035243`. A reference that
already has a session is never queued again, so an issue that stays assigned
does not produce a second pull request next week, and an answered question
is not answered twice. Only the *newest* changes-requested review of a pull
request is work; the older ones were answered by it.

**Bounded.** At most half the parallel ceiling may be self-queued sessions,
so an operator queueing work by hand always finds room.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from . import controls, db, github, model_policy, priority
from .config import settings
from .conventions import for_task

logger = logging.getLogger(__name__)

# How often the repository is polled. Frequent enough that a question asked
# during a working day is seen while its author is still around, rare enough
# to stay far inside GitHub's rate limits (a pass is a handful of requests).
POLL_INTERVAL_S = 120.0

# How far back a pass looks for comments. Assignments and reviews need no
# window — they are read from the current state of the repository — but
# comments are a stream, and without a bound the first pass after a restart
# would read years of them. A day is generous for "somebody asked something
# and is waiting"; anything older is not a live question.
COMMENT_LOOKBACK = timedelta(hours=24)

# At most this many comments are carried into one task, and this much of each.
MAX_THREAD_COMMENTS = 20
MAX_COMMENT_CHARS = 3000

# The account sessions are attributed to when the runner queued them itself.
CREATED_BY = "logos-agent (trigger)"

# Where a session writes an answer for the runner to post.
REPLY_FILE = "reply.md"


_NAME_SAFE = re.compile(r"[^a-z0-9]+")


def workspace_name(kind: str, number: int, title: str) -> str:
    """A workspace name that says what is in it.

    The name is not decoration: it becomes part of the branch a session
    pushes (`logos/agent/<workspace>/session-42`) and the first column of
    the workspace list. `auto-2` tells nobody anything; `issue-812-oom-on-
    startup` says what the checkout is for, in the branch as well as in the
    UI.

    Trimmed to keep branch names readable, and reduced to characters that
    are safe in both a Docker volume name and a git ref.
    """
    slug = _NAME_SAFE.sub("-", (title or "").strip().lower()).strip("-")
    words = [word for word in slug.split("-") if word][:5]
    tail = "-".join(words)[:40].strip("-")
    prefix = "issue" if kind == "issue" else "pr"
    return f"{prefix}-{number}-{tail}" if tail else f"{prefix}-{number}"


def _next_auto_name(existing: set[str]) -> str:
    """The lowest ``auto-N`` no workspace carries.

    The fallback for work that names nothing. Counting workspaces would
    repeat a name after a deletion — with `auto-1` and `auto-3` left, the
    count says `auto-3` — and every later poll would hit the same conflict
    and defer work while the ceiling still had room.
    """
    index = 1
    while f"auto-{index}" in existing:
        index += 1
    return f"auto-{index}"


def max_active_sessions(ceiling: int | None = None) -> int:
    """How many self-queued sessions may be active at once.

    Derived rather than configured: half the ceiling in force, at least
    one. The runner is a guest on this platform even when it is idle, and
    an operator who queues work by hand should always find room next to the
    automation — which is why it follows the *current* ceiling and not the
    configured one. Lowering the limit to two and still letting five
    triggered sessions through would take that room away, and their higher
    priorities would win it.
    """
    limit = settings.max_parallel_sessions if ceiling is None else ceiling
    return max(1, limit // 2)


def mentions_agent(body: str) -> bool:
    """Whether a comment addresses the agent by name.

    Matched on a word boundary so `@LogosOSSAgentBot` is not this account,
    and case-insensitively because GitHub logins are.
    """
    return re.search(rf"@{re.escape(settings.github_login)}\b", body or "", re.IGNORECASE) is not None


def is_bot(login: str) -> bool:
    """Whether an author is a bot.

    Bots comment a great deal — a review bot can post a dozen notes on one
    push — and a session per note would be a stampede, not a colleague. Their
    findings still reach the agent: they are part of the pull request the
    next review or assignment brings it back to.
    """
    return login.endswith("[bot]") or login.lower() in {"github-actions", "coderabbitai"}


# --- what the agent is asked to do ----------------------------------------


def issue_task(issue: dict[str, Any]) -> str:
    """The task text for an issue assigned to the agent."""
    number = issue.get("number")
    title = str(issue.get("title") or "").strip()
    body = str(issue.get("body") or "").strip()
    if len(body) > 6000:
        body = body[:6000] + "\n\n[issue body truncated]"
    return for_task(
        f"You have been assigned issue #{number}. Work on it and open a draft pull "
        f"request with your result.\n\n"
        f"Issue #{number}: {title}\n\n"
        f"{body}\n\n"
        f"Scope your change to what the issue asks for: the smallest change that "
        f"answers it, with tests for what you changed. If the issue is unclear or turns "
        f"out to be larger than it looks, do the part you are confident about and say "
        f"plainly in your final message what you left out and why."
    )


def takeover_task(number: int, title: str, body: str, branch: str) -> str:
    """The task text for a pull request handed to the agent."""
    text = (body or "").strip()
    if len(text) > 6000:
        text = text[:6000] + "\n\n[description truncated]"
    return for_task(
        f"Pull request #{number} ('{title}') has been assigned to you: somebody wants you "
        f"to carry it the rest of the way. You are working in a checkout of its own "
        f"branch `{branch}`, and your commit updates that pull request — do not open a "
        f"new one, and do not rename or move the branch.\n\n"
        f"What the pull request says about itself:\n\n{text or '(no description)'}\n\n"
        f"Read the existing review conversation before you change anything, and start "
        f"from whatever is still open in it. Bring the change to a state its author would "
        f"recognise: tests and linters of the part you touched pass, the description "
        f"still matches what the branch does. Say in your final message what you did and "
        f"what you deliberately left alone. Do not merge the pull request and do not "
        f"force-push over anybody else's commits."
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
        if len(body) > MAX_COMMENT_CHARS:
            body = body[:MAX_COMMENT_CHARS] + " […]"
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
    return for_task(
        f"A review on pull request #{number} ('{title}') asked for changes. You are working "
        f"in a checkout of that pull request's own branch, and your commit updates it — "
        f"there is no new pull request to open.\n\n"
        f"Review by {reviewer}:\n\n"
        f"{body or '(no review body; the requested changes are the inline comments below)'}\n\n"
        f"{inline}"
        f"Check each point against the current code before you change anything — lines "
        f"move, and some of it may already be addressed. Fix what is still valid, add "
        f"regression coverage for it, and run the tests and linters of the part you "
        f"touched. Write your reply to the review into `$LOGOS_ARTIFACT_DIR/{REPLY_FILE}` "
        f"— in English, saying for each point what you changed and how you verified it, "
        f"or why it needed no change; the runner posts it for you. Do not merge the pull "
        f"request and do not force-push."
    )


def thread_task(number: int, title: str, comments: list[dict[str, Any]], *, branch: str | None) -> str:
    """The task text for comments addressed to the agent.

    The answer is the deliverable. Whether code changes at all is the
    comment's business: "why does this fail?" wants an explanation, "can you
    also handle X?" wants a commit. Saying so plainly beats guessing.
    """
    rendered = []
    for comment in comments[:MAX_THREAD_COMMENTS]:
        author = str((comment.get("user") or {}).get("login") or "somebody")
        body = str(comment.get("body") or "").strip()
        if len(body) > MAX_COMMENT_CHARS:
            body = body[:MAX_COMMENT_CHARS] + " […]"
        path = comment.get("path")
        where = f" on {path}:{comment.get('line') or comment.get('original_line') or '?'}" if path else ""
        rendered.append(f"{author}{where} wrote:\n{body}")
    conversation = "\n\n---\n\n".join(rendered)
    if branch:
        place = (
            f"You are working in a checkout of that pull request's own branch `{branch}`. "
            f"If — and only if — answering means changing code, commit it there; it updates "
            f"the existing pull request rather than opening a new one."
        )
    else:
        place = (
            "You are working in a checkout of the default branch, and you have no business "
            "pushing to this pull request — it is somebody else's. Answer in words. If the "
            "answer needs a code change, say what you would change and why, and leave it to "
            "the people on the thread."
        )
    return for_task(
        f"You were asked something on #{number} ('{title}').\n\n"
        f"{conversation}\n\n"
        f"Write your answer to `$LOGOS_ARTIFACT_DIR/{REPLY_FILE}` — the runner posts it in "
        f"the thread for you, so write it as the reply itself: English, to the point, no "
        f"preamble about being an agent. Answer what was actually asked; read the code "
        f"before you claim anything about it, and say plainly when you do not know. "
        f"{place}"
    )


class TriggerPoller:
    """Polls the repository and queues sessions for what it finds."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._last_error: str = ""
        self._last_pass: datetime | None = None
        self._queued_total = 0
        # login -> may push, for the duration of one pass.
        self._writers: dict[str, bool] = {}
        # Called after a pass queued something, so the work starts on the
        # next admission rather than at the scheduler's own tick. Set by the
        # service on startup; the poller does not import the session manager
        # itself, which keeps the dependency pointing one way.
        self.on_queued: Callable[[], Awaitable[None]] | None = None

    # --- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        if not settings.triggers_enabled:
            logger.info("repository triggers are off (LOGOS_AGENT_TRIGGERS_ENABLED=false)")
            return
        if not settings.github_token:
            logger.warning("repository triggers are on but no GitHub token is configured; not polling")
            return
        self._task = asyncio.create_task(self._loop(), name="agent-triggers")
        logger.info(
            "watching %s as %s every %.0fs: assignments, reviews, and comments addressed to it",
            settings.repo_slug,
            settings.github_login,
            POLL_INTERVAL_S,
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
                # again. Nothing is lost by a failure either — a pass reads
                # the repository's current state, it does not advance a
                # cursor.
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
        # Nothing to queue into: the runner is paused, draining, or its
        # ceiling is zero. The repository is read again next pass, and
        # nothing is lost by not looking now.
        control = await controls.current()
        blocked = control.admission_block()
        if blocked:
            logger.debug("trigger poll skipped: %s", blocked)
            self._last_pass = now
            return []
        quota = max_active_sessions(control.max_parallel)
        room = quota - await db.count_active_trigger_sessions()
        if room <= 0:
            logger.debug("trigger poll skipped: already at %s self-queued sessions", quota)
            self._last_pass = now
            return []

        # Permission answers are cached per pass: they can change, and a
        # pass is short enough that reading them once is honest.
        self._writers = {}
        candidates = await self._candidates(now)
        self._last_pass = now
        self._last_error = ""
        if not candidates:
            return []

        # Most urgent first: a pass may only have room for some of them, and
        # what it takes should be what matters most.
        candidates.sort(key=lambda candidate: -(candidate.get("urgency").value if candidate.get("urgency") else 50))
        handled = await db.handled_trigger_refs([candidate["ref"] for candidate in candidates])
        queued: list[int] = []
        for candidate in candidates:
            if room <= 0:
                # Left for the next pass: nothing here is consumed by being
                # seen, so what does not fit now is found again.
                break
            if candidate["ref"] in handled:
                continue
            session_id = await self._queue(candidate)
            if session_id is None:
                continue
            queued.append(session_id)
            room -= 1
            await self._acknowledge(candidate)
        if queued and self.on_queued is not None:
            await self.on_queued()
        return queued

    async def _acknowledge(self, candidate: dict[str, Any]) -> None:
        """React with 👀 so the person who asked can see it landed.

        Best effort: a missing reaction is a cosmetic loss, and the work is
        already queued. Anything else would make a failed reaction lose a
        session.
        """
        target = candidate.get("reaction")
        if not target:
            return
        try:
            await github.react(target)
        except Exception as exc:
            logger.info("could not acknowledge %s: %s", candidate["ref"], exc)

    async def _candidates(self, now: datetime) -> list[dict[str, Any]]:
        """Everything the repository is currently asking this account for."""
        login = settings.github_login
        found: list[dict[str, Any]] = []

        for issue in await github.assigned_issues(login):
            number = issue.get("number")
            if not isinstance(number, int):
                continue
            urgency = priority.of("issue", issue.get("labels"))
            if urgency.refused:
                logger.info("issue %s is %s; not starting work on it", number, urgency.reason)
                continue
            title = str(issue.get("title") or "")
            found.append(
                {
                    "ref": f"issue-{number}",
                    "kind": "issue",
                    "task": issue_task(issue),
                    "workspace": workspace_name("issue", number, title),
                    "reaction": f"/repos/{settings.repo_slug}/issues/{number}",
                    "urgency": urgency,
                }
            )

        responsible = await self._responsible_pulls(login)
        # Inline comments a review task already carries: the repository scan
        # below sees the same objects, and a second candidate for them would
        # be a second session writing to one branch about one request.
        consumed: set[int] = set()
        for number, pull in responsible.items():
            branch = pull["branch"]
            review = await github.latest_changes_requested_review(number)
            if review is not None:
                review_id = int(review["id"])
                comments = await github.review_comments(number, review_id)
                consumed.update(c["id"] for c in comments if isinstance(c.get("id"), int))
                if branch is None:
                    # Nowhere to put the fix: a fork's head, or a protected
                    # branch. Queueing it anyway would start a session from
                    # the default branch on a fresh branch of its own, which
                    # cannot update the pull request its task is about.
                    logger.info("review on pull request %s has no writable branch; leaving it to a person", number)
                    continue
                reviewer = str((review.get("user") or {}).get("login") or "")
                if not await self._writer(reviewer):
                    # Anybody may review a public pull request, and a review
                    # is a request to change code: acting on one from
                    # outside the repository would let a stranger direct
                    # what the agent commits.
                    logger.info(
                        "review on pull request %s is by %s, who may not write to this repository; "
                        "leaving it to a person",
                        number,
                        reviewer or "an unknown account",
                    )
                    continue
                found.append(
                    {
                        "ref": f"pr-{number}-review-{review_id}",
                        "kind": "review",
                        "task": review_task(number, pull["title"], review, comments),
                        "branch": branch,
                        "workspace": workspace_name("pr", number, pull["title"]),
                        # A submitted review is not a review *comment*: the
                        # two have independent id sequences, so the
                        # acknowledgement goes on the pull request itself.
                        "reaction": f"/repos/{settings.repo_slug}/issues/{number}",
                        "reply_target": f"issue:{number}",
                        "urgency": priority.of("review", pull["labels"]),
                    }
                )
            elif pull["assigned"] and branch:
                found.append(
                    {
                        "ref": f"pr-{number}-assigned",
                        "kind": "takeover",
                        "task": takeover_task(number, pull["title"], pull["body"], branch),
                        "branch": branch,
                        "workspace": workspace_name("pr", number, pull["title"]),
                        "reaction": f"/repos/{settings.repo_slug}/issues/{number}",
                        "urgency": priority.of("takeover", pull["labels"]),
                    }
                )

        found.extend(await self._comment_candidates(now, responsible, consumed))
        return found

    async def _responsible_pulls(self, login: str) -> dict[int, dict[str, Any]]:
        """The open pull requests this account has to answer for.

        Its own, because their reviews are addressed to it, and the ones
        somebody assigned to it. A head it may not push to is kept anyway,
        with ``branch`` left None: a question on such a pull request is still
        answerable, it just cannot be answered with a commit.
        """
        pulls: dict[int, dict[str, Any]] = {}

        async def remember(entry: dict[str, Any], *, assigned: bool) -> None:
            number = entry.get("number")
            if not isinstance(number, int) or number in pulls:
                return
            pulls[number] = {
                "title": str(entry.get("title") or ""),
                "body": str(entry.get("body") or ""),
                "labels": entry.get("labels") or (),
                "assigned": assigned,
                "branch": await self._writable_head(number),
            }

        for entry in await github.assigned_pull_requests(login):
            await remember(entry, assigned=True)
        for entry in await github.authored_pull_requests(login):
            await remember(entry, assigned=False)
        return pulls

    async def _writer(self, login: str) -> bool:
        """Whether an account may write to this repository.

        Cached for the pass: one conversation is usually one person, and a
        lookup per comment would spend requests on the same answer.
        """
        key = login.lower()
        if key not in self._writers:
            self._writers[key] = await github.may_push(login)
        return self._writers[key]

    async def _may_direct_changes(self, comments: list[dict[str, Any]]) -> bool:
        """Whether anyone in this conversation may direct a code change."""
        for comment in comments:
            author = str((comment.get("user") or {}).get("login") or "")
            if author and await self._writer(author):
                return True
        return False

    async def _writable_head(self, number: int) -> str | None:
        """The branch of a pull request the agent may push to, or None.

        Two rules, and only two. The head has to live in this repository —
        a fork's branch is not ours to push and the token could not do it
        anyway — and it must not be a protected branch, which no session may
        ever write to. The agent branch prefix is deliberately *not*
        required: a pull request handed over by a person keeps its own
        branch name, because renaming it would abandon the pull request it
        belongs to.
        """
        try:
            pull = await github.pull_request(number)
        except Exception as exc:
            logger.warning("could not read pull request %s: %s", number, exc)
            return None
        ref, repo = github.head_of(pull)
        if not ref:
            return None
        if repo != settings.repo_slug:
            logger.info("pull request %s comes from '%s'; the runner does not push to forks", number, repo or "?")
            return None
        if ref in settings.protected_branches or ref.rsplit("/", 1)[-1] in settings.protected_branches:
            logger.warning("pull request %s targets protected branch '%s'; refusing to work on it", number, ref)
            return None
        return ref

    async def _comment_candidates(
        self, now: datetime, responsible: dict[int, dict[str, Any]], consumed: set[int]
    ) -> list[dict[str, Any]]:
        """Comments the agent should answer, one candidate per conversation.

        Two kinds count: anything on a pull request it is responsible for,
        and anything anywhere that mentions it by name. Its own comments and
        those of bots are skipped — the first would be a conversation with
        itself, the second a stampede.

        A *conversation* is the unit, not a pull request: an inline thread is
        its own question, asked about one place in the diff and answered
        there, while ordinary comments on a thread are one running
        discussion. Grouping every inline thread of a pull request together
        would answer one of them and leave the rest without a reply.

        Comments already carried by a review task are skipped: they are being
        worked on, and answering them twice is not answering them better.
        """
        since = now - COMMENT_LOOKBACK
        threads: dict[tuple[str, int], dict[str, Any]] = {}

        def consider(comment: dict[str, Any], number: int, *, root: int | None) -> None:
            author = str((comment.get("user") or {}).get("login") or "")
            if not author or author.lower() == settings.github_login.lower() or is_bot(author):
                return
            comment_id = comment.get("id")
            if not isinstance(comment_id, int) or comment_id in consumed:
                return
            body = str(comment.get("body") or "")
            if number not in responsible and not mentions_agent(body):
                return
            key = ("inline", root) if root is not None else ("issue", number)
            thread = threads.setdefault(
                key,
                {"number": number, "comments": [], "newest_id": comment_id, "newest_at": None, "root": root},
            )
            thread["comments"].append(comment)
            # Newest by time, not by id: issue comments and review comments
            # have independent id sequences, so a newer one of either kind
            # can carry a smaller number than an older one of the other. Ids
            # decide only between two comments that carry no timestamp,
            # which within one thread means one kind and one sequence.
            written = github.created_at_of(comment)
            best = thread["newest_at"]
            if written is not None and (best is None or written >= best):
                thread["newest_at"], thread["newest_id"] = written, comment_id
            elif written is None and best is None and comment_id > thread["newest_id"]:
                thread["newest_id"] = comment_id

        for comment in await github.recent_issue_comments(since):
            number = github.issue_number_of(comment)
            if number is not None:
                consider(comment, number, root=None)
        for comment in await github.recent_review_comments(since):
            number = github.pull_number_of(comment)
            if number is not None:
                consider(comment, number, root=github.thread_root_of(comment))

        candidates: list[dict[str, Any]] = []
        for (kind, key), thread in threads.items():
            number = thread["number"]
            pull = responsible.get(number)
            title = pull["title"] if pull else f"#{number}"
            # Anybody may comment on a public repository; not everybody may
            # direct a change to it. A conversation with no writer in it is
            # answered in words and gets no branch, so the credentialed
            # finalizer cannot be made to push on a stranger's say-so.
            branch = pull["branch"] if pull else None
            if branch is not None and not await self._may_direct_changes(thread["comments"]):
                logger.info("comments on #%s come from outside the repository; answering without a branch", number)
                branch = None
            newest = thread["newest_id"]
            inline = kind == "inline"
            candidates.append(
                {
                    # The reference names the conversation and its latest
                    # word, so a later comment in it is new work and the same
                    # one never is. An inline thread carries its root, since
                    # one pull request has many of them.
                    "ref": (f"thread-{number}-inline-{key}-{newest}" if inline else f"thread-{number}-issue-{newest}"),
                    "kind": "comment",
                    "task": thread_task(number, title, thread["comments"], branch=branch),
                    "branch": branch,
                    "workspace": workspace_name("pr", number, title) if branch else None,
                    "urgency": priority.of("comment", pull["labels"] if pull else ()),
                    "reaction": (
                        f"/repos/{settings.repo_slug}/pulls/comments/{newest}"
                        if inline
                        else f"/repos/{settings.repo_slug}/issues/comments/{newest}"
                    ),
                    # An inline question is answered in its own thread, where
                    # the person who asked it is looking.
                    "reply_target": (f"review_comment:{number}:{key}" if inline else f"issue:{number}"),
                }
            )
        return candidates

    # --- queueing ---------------------------------------------------------

    async def _queue(self, candidate: dict[str, Any]) -> int | None:
        """Queue one session, making a workspace for it if none is free."""
        policy = model_policy.current()
        if not policy.ok:
            logger.info("not queueing %s: %s", candidate["ref"], policy.detail)
            return None
        urgency = candidate.get("urgency") or priority.of(candidate["kind"])
        if urgency.refused:
            # Checked here rather than per source: a review, a handover and
            # a question can all carry `blocked` or `wontfix` just as an
            # issue can, and this is the one place every kind passes
            # through.
            logger.info("not queueing %s: %s", candidate["ref"], urgency.reason)
            return None
        branch = candidate.get("branch")
        workspace_id = await self._free_workspace(
            base_branch=branch or "main",
            preferred_name=candidate.get("workspace"),
        )
        if workspace_id is None:
            # Every workspace is busy and the ceiling is reached. Nothing is
            # recorded, so the next pass — after a session has finished —
            # finds this again.
            logger.info("not queueing %s: no free workspace", candidate["ref"])
            return None
        try:
            session_id = await db.create_session(
                workspace_id=workspace_id,
                task=candidate["task"],
                model=None,
                created_by=CREATED_BY,
                # Work on an existing branch updates its pull request, and a
                # question is answered in words: only an assigned issue is
                # fresh work that needs a pull request of its own. A comment
                # session with no branch would otherwise open one for an
                # answer nobody asked to be a pull request.
                branch=branch,
                open_pull_request=candidate["kind"] == "issue",
                # A session the runner queued by itself does not touch a
                # shared environment: deploying is an operator's decision,
                # made per session in the UI.
                deploy_to_dev=False,
                screenshot_paths=[],
                trigger_kind=candidate["kind"],
                trigger_ref=candidate["ref"],
                reply_target=candidate.get("reply_target"),
                priority=urgency.value,
                priority_reason=urgency.reason,
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
                created = await db.create_workspace(
                    name=name, base_branch=base_branch, created_by=CREATED_BY, ephemeral=True
                )
            except ValueError:
                # The name belongs to a workspace that is currently
                # occupied — most often the one for this very pull request,
                # already working on an earlier request.
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
            "account": settings.github_login,
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
    "COMMENT_LOOKBACK",
    "POLL_INTERVAL_S",
    "REPLY_FILE",
    "TriggerPoller",
    "active_trigger_sessions",
    "is_bot",
    "issue_task",
    "max_active_sessions",
    "mentions_agent",
    "poller",
    "review_task",
    "takeover_task",
    "thread_task",
]
