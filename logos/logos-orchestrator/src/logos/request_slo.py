"""Request-level service-level objectives for queue scheduling.

Logos already expresses queue urgency as an SLO on the API key
(``ux-critical`` / ``ux-high-prio`` / ``ux-background`` →
``default_priority`` 10 / 5 / 1; see logos-ui ``key-slo.ts`` and
webservice ``AiWorkflowAnalysisService.sloToPriority``). This module is
the orchestrator's matching request-side view of that same concept:

* An optional ``X-Logos-SLO`` / ``logos-slo`` header overrides the
  key/team/policy priority for this request only, using the same three
  tier names and numeric values the key SLO uses.
* ``x-app: cli-bg`` (Claude Code background agents) does **not** claim a
  higher tier — that would jump priority buckets and starve ordinary
  same-bucket traffic. Instead it marks the request for the queue's
  same-bucket fast lane: the bounded 1:2 interleave the priority queue
  already uses so latency-sensitive background calls get precedence
  without a monopoly.

The key/team/policy integer from ``resolve_queue_priority`` remains the
base; this module only layers the request-level SLO header and the
cli-bg fast-lane attribute on top.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

# Same tier → priority map as logos-ui key-slo.ts and
# AiWorkflowAnalysisService.sloToPriority.
SLO_PRIORITY: dict[str, int] = {
    "ux-critical": 10,
    "ux-high-prio": 5,
    "ux-background": 1,
}

_SLO_HEADER_NAMES = frozenset({"x-logos-slo", "logos-slo"})
_DEFAULT_TIER = "ux-high-prio"


@dataclass(frozen=True)
class RequestSlo:
    """Resolved service-level objective for one request.

    ``tier`` is one of the three key-SLO names (or the default when the
    base priority is not an exact tier value). ``priority`` is the raw
    queue priority the scheduler enqueues with. ``fast_lane`` is True
    when this request joins the same-bucket bounded interleave (cli-bg).
    """

    tier: str
    priority: int
    fast_lane: bool = False


def slo_of_priority(priority: int) -> str:
    """Tier name for an explicit stored/resolved priority (matches UI)."""
    if priority == SLO_PRIORITY["ux-critical"]:
        return "ux-critical"
    if priority == SLO_PRIORITY["ux-background"]:
        return "ux-background"
    return _DEFAULT_TIER


def parse_slo_header(headers: Mapping[str, str]) -> Optional[str]:
    """Recognised ``X-Logos-SLO`` / ``logos-slo`` value, or None.

    Comparison is case-insensitive in both name and value, as HTTP
    headers are. Unknown values are ignored so a typo cannot invent a
    priority.
    """
    for name, value in headers.items():
        if name.lower() not in _SLO_HEADER_NAMES:
            continue
        tier = value.strip().lower()
        if tier in SLO_PRIORITY:
            return tier
    return None


def is_cli_bg(headers: Mapping[str, str]) -> bool:
    """True when the caller marked the request as Claude Code background traffic.

    Claude Code sends ``x-app: cli`` for interactive sessions and
    ``x-app: cli-bg`` for its background agents; only the latter joins
    the same-bucket SLO fast lane. Case-insensitive in name and value.
    """
    for name, value in headers.items():
        if name.lower() == "x-app" and value.strip().lower() == "cli-bg":
            return True
    return False


def resolve_request_slo(
    headers: Mapping[str, str],
    base_priority: int,
) -> RequestSlo:
    """Resolve the request SLO from headers on top of a base priority.

    Precedence for ``priority``:

    1. Explicit ``X-Logos-SLO`` / ``logos-slo`` header, when it names a
       known tier — same integers the key SLO writes to
       ``default_priority``.
    2. Otherwise ``base_priority`` (key → team → policy → NORMAL).

    ``x-app: cli-bg`` never changes the priority bucket. It only sets
    ``fast_lane`` so the priority queue can give the request bounded
    same-bucket precedence (the existing 1-flagged : 2-regular
    interleave) without a parallel scheduling mechanism.
    """
    header_tier = parse_slo_header(headers)
    if header_tier is not None:
        priority = SLO_PRIORITY[header_tier]
        tier = header_tier
    else:
        priority = int(base_priority)
        tier = slo_of_priority(priority)
    return RequestSlo(
        tier=tier,
        priority=priority,
        fast_lane=is_cli_bg(headers),
    )
