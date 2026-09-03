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
- Commit messages start with the component in backticks, then an imperative
  summary of what changed: `Logos`: Close the session before its volume is
  removed. The body explains why the change is right, not what the diff
  already shows.
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
- Everything you write on GitHub is in English, whatever language the task
  was given in.
- Answer the point that was made. State what you changed and how you
  verified it, or why it needed no change — not a summary of your process.

Working within the sandbox:
- You have no network beyond the model gateway, and no GitHub credential.
  Do not attempt to push, open pull requests, or post comments yourself:
  write your work into the checkout and your answer into the reply file, and
  the runner does the rest with a credential you never see.
- Your time is capped. If the task is larger than the budget, do the part
  you are confident about, leave the rest untouched, and say plainly in your
  final message what you left out and why. A partial change that is honest
  about being partial is useful; a half-finished one that claims to be done
  is not.
""".strip()


def for_task(task: str) -> str:
    """One task, followed by the conventions it has to hold to."""
    return f"{task.strip()}\n\n{HOUSE_RULES}"
