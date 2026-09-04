"""What this repository expects, told to the agent before it starts.

Every line here was learned the expensive way — a review round spent on
something a sentence could have prevented. An unattended agent cannot ask,
so the things a new colleague would be told in their first week are told to
it in its task instead.

Kept in one place because it is one contract, and appended to every task so
none of them can quietly drift from it.
"""

from __future__ import annotations

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
- Run the tests and linters of the part of the repository you touched, and
  the repository's pre-commit hooks. Report what you ran.
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


def for_task(task: str) -> str:
    """One task, followed by the conventions it has to hold to."""
    return f"{task.strip()}\n\n{HOUSE_RULES}"
