"""How urgent a piece of work is, read from the labels already on it.

Sessions are admitted one per capacity reading, so the order they are
admitted in *is* what the platform works on first while it is busy. Arrival
order is the wrong answer to that: a security fix waiting behind a
documentation typo is exactly the failure this module exists to prevent.

Nothing new is invented for it. The repository already labels its issues, and
those labels already say what kind of work something is; this maps them onto
one number. Where a repository uses different words, the mapping is the one
place to change.

Two decisions are worth naming:

* **Answering beats starting.** A question has somebody waiting on it and
  costs one short session; a fresh issue has nobody waiting and costs an
  hour. So conversation outranks new work, and a review — which blocks a
  pull request from landing — outranks both.
* **Some labels mean "not now".** `blocked`, `wontfix`, `invalid`,
  `duplicate` and `stale` are not urgency, they are an answer: the runner
  does not pick that work up at all, and says which label stopped it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

# What each kind of trigger is worth before labels are taken into account.
# The numbers are only meaningful relative to each other.
BASE = {
    # A review holds a pull request shut; somebody is waiting for the
    # branch to move.
    "review": 80,
    # A question, with a person on the other end of it.
    "comment": 70,
    # Somebody handed over a pull request: work in progress, not a new idea.
    "takeover": 60,
    # A fresh issue.
    "issue": 50,
}

# Labels that raise or lower urgency, most urgent first. A thread carrying
# several of them takes the strongest.
LABEL_PRIORITY: tuple[tuple[str, int, str], ...] = (
    ("security fix", 40, "a security fix"),
    ("security", 40, "a security fix"),
    ("critical", 35, "labelled critical"),
    ("urgent", 30, "labelled urgent"),
    ("deployment-error", 30, "a broken deployment"),
    ("bug", 20, "a bug"),
    ("enhancement", 0, "an enhancement"),
    ("documentation", -10, "documentation"),
    ("question", -10, "a question"),
    ("good first issue", -15, "a good first issue"),
)

# Labels that mean the work is not the runner's to start, whatever else the
# thread says.
REFUSING_LABELS: tuple[str, ...] = ("blocked", "wontfix", "invalid", "duplicate", "stale")

# The floor and ceiling the database column allows.
MIN, MAX = 0, 100


@dataclass(frozen=True)
class Urgency:
    """What a candidate is worth, and the sentence explaining it."""

    value: int
    reason: str
    # Set when a label says the work should not be started at all.
    refused_by: str | None = None

    @property
    def refused(self) -> bool:
        return self.refused_by is not None


def _names(labels: Iterable[Any]) -> list[str]:
    """Label names from GitHub's shape, lowercased.

    Issues carry objects; some listings carry plain strings.
    """
    found: list[str] = []
    for label in labels or ():
        if isinstance(label, dict):
            name = label.get("name")
        else:
            name = label
        if isinstance(name, str) and name.strip():
            found.append(name.strip().lower())
    return found


def of(kind: str, labels: Iterable[Any] = ()) -> Urgency:
    """The urgency of one candidate.

    ``kind`` is the trigger kind ('issue', 'review', 'comment',
    'takeover'); ``labels`` are the labels on the issue or pull request it
    came from.
    """
    names = set(_names(labels))
    for refusing in REFUSING_LABELS:
        if refusing in names:
            return Urgency(value=BASE.get(kind, 50), reason=f"labelled {refusing}", refused_by=refusing)

    base = BASE.get(kind, 50)
    adjustment, why = 0, None
    for label, delta, description in LABEL_PRIORITY:
        if label in names:
            adjustment, why = delta, description
            break

    value = max(MIN, min(MAX, base + adjustment))
    if why is None:
        reason = f"{kind} work"
    else:
        reason = f"{kind} work on {why}"
    return Urgency(value=value, reason=reason)
