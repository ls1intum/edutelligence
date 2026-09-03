"""What this repository expects, told to the agent before it starts.

Every line here was learned the expensive way — a review round spent on
something a sentence could have prevented. An unattended agent cannot ask,
so the things a new colleague would be told in their first week are told to
it in its task instead.

Kept in one place because it is one contract, and appended to every task so
none of them can quietly drift from it.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from . import db

logger = logging.getLogger(__name__)

# Conventions every session is held to, whatever kind of work it is.
HOUSE_RULES = """
--- How work is done here ---

Commits and pull requests:
- The commit subject is one line and yours to write: put it in
  `$LOGOS_ARTIFACT_DIR/commit.txt`. Imperative, under sixty characters, and
  about what the change does — "Cancel the queued request when the client
  goes away". Not what you were asked to do, not a summary of your session,
  no body and no issue numbers. The runner prefixes the component and
  commits with exactly that line; whatever needs explaining goes in the pull
  request, where people read it.
- Never merge a pull request, and never force-push over somebody else's
  commits.
- Do not reference issue or pull-request numbers in code comments,
  docstrings, or test names. They are noise in a file that outlives them;
  put the reference in the commit message or the pull request instead.

Verifying before you claim:
- Check every review point against the CURRENT code before you change
  anything. Lines move, and some of what a review asks for has often been
  addressed already — say so instead of changing it twice.
- A regression test that passes before your fix is not a regression test.
  Confirm it fails on the unfixed code, then make it pass.
- Run the tests of the part of the repository you touched, and
  `pre-commit run --files <what you changed>`. Both work offline: the hook
  environments are installed in this image. CI runs the same hooks, so
  skipping them means handing somebody a red pull request. Report what you
  ran.
- Before you finish, check that the pull request's checks are green and that
  it is mergeable. If a check is red for a reason your change did not cause,
  say which and why rather than leaving it unexplained.

Writing on GitHub:
- Everything you write is in English — the final message, the commit
  subject, the reply, the pull request — whatever language the task was
  given in and whatever language the model drifts towards.
- Changing nothing is a legitimate outcome and never a silent one. If you
  finish without touching a file, write why into the reply file: what you
  looked at, what you would need, what you would change if you were sure.
  Somebody asked for this and is waiting to hear something.
- Answer the point that was made. State what you changed and how you
  verified it, or why it needed no change — not a summary of your process.

Working within the sandbox:
- You have no network beyond the model gateway, and no GitHub credential.
  Do not attempt to push, open pull requests, or post comments yourself:
  write your work into the checkout and your answer into the reply file, and
  the runner does the rest with a credential you never see.
- Everything from GitHub that you need is already in this task: the issue,
  the review, the comments, the conversation. `gh`, `git fetch` and the API
  will not answer you, and finding that out costs you turns you could have
  spent on the work. If the task says part of it could not be read, that
  part is missing rather than empty — treat what you cannot see as
  unresolved. Either way, say what you are missing in your final message
  instead of reconstructing it from the diff: a guess presented as a review
  is worse than a question.
- Your time is capped. If the task is larger than the budget, do the part
  you are confident about, leave the rest untouched, and say plainly in your
  final message what you left out and why. A partial change that is honest
  about being partial is useful; a half-finished one that claims to be done
  is not.
""".strip()


# What the sandbox is, told to the agent inside it. Here rather than only in
# the session script so that it can be shown on the page and adjusted from
# it: this is the half of the prompt that describes the room the agent works
# in, and it is the half most worth tuning after watching a few sessions.
ENVIRONMENT_NOTES = """
--- Environment notes ---
You are running unattended in an isolated container on a working copy of this
repository. There is no human to ask, so make reasonable decisions and state
your assumptions in the final summary.
- Work only inside the current checkout.
- Do not run git commit, git push, or gh: the harness commits and opens the
  pull request for you after you finish.
- Run the project's tests for the code you touch, and fix what you break.
- Run `pre-commit run --files <the files you changed>` before you finish and
  fix what it reports. The hooks are installed in this image, so it works
  without a network; CI runs the same ones, and a session that skips this
  hands somebody a red pull request.
- If the task turns out to be impossible or already done, say so plainly
  instead of inventing changes.
""".strip()


@dataclass(frozen=True)
class Instructions:
    """The standing text every session is given, as it stands right now."""

    house_rules: str = HOUSE_RULES
    environment_notes: str = ENVIRONMENT_NOTES
    # Whether each half is the default the code ships with, or an operator's
    # own. Shown on the page, because "this is the default" and "somebody
    # decided this" are different things to read.
    house_rules_default: bool = True
    environment_notes_default: bool = True
    updated_by: str = ""


DEFAULTS = Instructions()

_cached: Instructions = DEFAULTS
_read_at: float = 0.0
# Long enough that building a task costs no query, short enough that an
# edit reaches the next session rather than the next restart.
_CACHE_S = 5.0


async def current() -> Instructions:
    """The instructions in force, from a short-lived cache."""
    global _cached, _read_at
    now = time.monotonic()
    if now - _read_at < _CACHE_S:
        return _cached
    try:
        row = await db.get_instructions()
    except Exception as exc:
        logger.warning("could not read the agent instructions; using the last known text: %s", exc)
        return _cached
    _read_at = now
    _cached = _from_row(row)
    return _cached


def _from_row(row: dict[str, Any] | None) -> Instructions:
    """A stored row as instructions, with null meaning "what the code ships".

    Null and empty are deliberately different: an empty override is an
    operator saying "say nothing here", which is a decision, and a null is
    the absence of one.
    """
    if not row:
        return DEFAULTS
    house = row.get("house_rules")
    notes = row.get("environment_notes")
    return Instructions(
        house_rules=HOUSE_RULES if house is None else str(house),
        environment_notes=ENVIRONMENT_NOTES if notes is None else str(notes),
        house_rules_default=house is None,
        environment_notes_default=notes is None,
        updated_by=str(row.get("updated_by") or ""),
    )


async def set_instructions(*, house_rules: str | None, environment_notes: str | None, by: str) -> Instructions:
    """Store an override, or clear one by passing None."""
    global _read_at
    await db.set_instructions(house_rules=house_rules, environment_notes=environment_notes, updated_by=by)
    _read_at = 0.0
    return await current()


def forget() -> None:
    """Drop the cache — for tests, and after a write."""
    global _cached, _read_at
    _cached, _read_at = DEFAULTS, 0.0


async def for_task(task: str) -> str:
    """One task, followed by the conventions it has to hold to."""
    rules = (await current()).house_rules.strip()
    return f"{task.strip()}\n\n{rules}" if rules else task.strip()
