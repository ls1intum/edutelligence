"""Request-level service-level objectives for queue scheduling.

Logos already expresses queue urgency as an SLO on the API key
(``ux-critical`` / ``ux-high-prio`` / ``ux-background`` →
``default_priority`` 10 / 5 / 1; see logos-ui ``key-slo.ts`` and
webservice ``AiWorkflowAnalysisService.sloToPriority``). The orchestrator
resolves that SLO per request in
``pipeline.resolve_queue_priority`` (key → team → policy). This module is
the request-side view of the same concept, built on top of that existing
resolution rather than a parallel mechanism:

* The request's queue priority is exactly the resolved key/team/policy
  SLO priority — nothing here may widen or narrow it, so a request can
  never leave the bucket its key's SLO puts it in.
* ``x-app: cli-bg`` (Claude Code background agents) does **not** claim a
  higher tier — that would jump priority buckets and starve ordinary
  same-bucket traffic. Instead it marks the request for the queue's
  same-bucket fast lane: the bounded 1:2 interleave ``PriorityQueueManager``
  uses so latency-sensitive background calls get precedence without a
  monopoly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

# Same tier → priority map as logos-ui key-slo.ts and
# AiWorkflowAnalysisService.sloToPriority.
SLO_PRIORITY: dict[str, int] = {
    "ux-critical": 10,
    "ux-high-prio": 5,
    "ux-background": 1,
}

_DEFAULT_TIER = "ux-high-prio"


@dataclass(frozen=True)
class RequestSlo:
    """Resolved service-level objective for one request.

    ``tier`` is one of the three key-SLO names (or the default tier when
    the resolved priority is not an exact tier value). ``priority`` is the
    raw queue priority the request was resolved with — always the
    key/team/policy SLO value, never anything caller-supplied.
    ``fast_lane`` is True when this request joins the queue's same-bucket
    bounded interleave (today: ``x-app: cli-bg``).
    """

    tier: str
    priority: int
    fast_lane: bool = False


def slo_of_priority(priority: int) -> str:
    """Tier name for a resolved priority (matches the key-SLO display).

    Only 10 and 1 name a tier of their own; everything else reads as the
    default tier — the same rule as ``sloOfPriority`` in logos-ui
    ``key-slo.ts``, so the queue and the UI agree on the tier a stored or
    inherited priority stands for.
    """
    if priority == SLO_PRIORITY["ux-critical"]:
        return "ux-critical"
    if priority == SLO_PRIORITY["ux-background"]:
        return "ux-background"
    return _DEFAULT_TIER


def is_cli_bg(headers: Mapping[str, str]) -> bool:
    """True when the caller marked the request as Claude Code background traffic.

    Claude Code sends ``x-app: cli`` for interactive sessions and
    ``x-app: cli-bg`` for its background agents; only the latter joins
    the same-bucket SLO fast lane. The comparison is case-insensitive in
    both name and value, as HTTP headers are.
    """
    for name, value in headers.items():
        if name.lower() == "x-app" and value.strip().lower() == "cli-bg":
            return True
    return False


def resolve_request_slo(
    headers: Mapping[str, str],
    base_priority: int,
) -> RequestSlo:
    """Resolve the request SLO on top of the existing key/team/policy SLO.

    ``base_priority`` is the output of ``pipeline.resolve_queue_priority``
    — the key's SLO, else the team's, else the policy's. It is passed
    through unchanged: the SLO that exists is the key's, and a
    per-request override header would be a new caller-controlled channel
    into the queue (any key could claim ``ux-critical`` and jump into the
    HIGH bucket), so there is none here.

    ``x-app: cli-bg`` never changes the priority bucket. It only sets
    ``fast_lane`` so the priority queue can give the request bounded
    same-bucket precedence (the 1-fast-lane : 2-regular interleave)
    without a parallel scheduling mechanism.
    """
    return RequestSlo(
        tier=slo_of_priority(int(base_priority)),
        priority=int(base_priority),
        fast_lane=is_cli_bg(headers),
    )
