"""Per-request SLA headers and workflow-tag attribution.

Applications may send ``X-Logos-SLA`` to set queue priority for one request, or
``X-Logos-Workflow-Tag`` so Logos looks up the matching workflow/step SLA.
Precedence over the key/team/policy chain is defined by
``resolve_request_priority``.
"""

from __future__ import annotations

from typing import Mapping, Optional

VALID_SLAS = frozenset({"ux-critical", "ux-high-prio", "ux-background"})

_SLA_TO_PRIORITY = {
    "ux-critical": 10,
    "ux-high-prio": 5,
    "ux-background": 1,
}

_SLA_HEADER_NAMES = ("x-logos-sla", "logos-sla")
_WORKFLOW_TAG_HEADER_NAMES = ("x-logos-workflow-tag", "logos-workflow-tag")


def sla_to_priority(sla: str) -> int:
    """Map an SLA string to the 1/5/10 queue priority scale.

    Args:
        sla: One of ``VALID_SLAS``.

    Returns:
        10 for ux-critical, 5 for ux-high-prio, 1 for ux-background.

    Raises:
        KeyError: When ``sla`` is not a known SLA string.
    """
    return _SLA_TO_PRIORITY[sla]


def _header_value(headers: Mapping[str, str], names: tuple[str, ...]) -> Optional[str]:
    """Return the first non-empty header value among ``names`` (case-insensitive)."""
    if not headers:
        return None
    lowered = {str(key).lower(): value for key, value in headers.items()}
    for name in names:
        value = lowered.get(name)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def parse_request_sla_header(headers: Optional[Mapping[str, str]]) -> Optional[str]:
    """Parse ``X-Logos-SLA`` (or ``logos-sla``) into a validated SLA string.

    Args:
        headers: Request headers (case-insensitive).

    Returns:
        A member of ``VALID_SLAS``, or None when absent / unrecognised.
    """
    raw = _header_value(headers or {}, _SLA_HEADER_NAMES)
    if raw is None:
        return None
    sla = raw.lower()
    return sla if sla in VALID_SLAS else None


def parse_workflow_tag_header(headers: Optional[Mapping[str, str]]) -> Optional[str]:
    """Parse ``X-Logos-Workflow-Tag`` (or ``logos-workflow-tag``).

    Args:
        headers: Request headers (case-insensitive).

    Returns:
        The trimmed tag string, or None when absent.
    """
    return _header_value(headers or {}, _WORKFLOW_TAG_HEADER_NAMES)


def resolve_request_priority(
    header_sla: Optional[str],
    tag_sla: Optional[str],
    default_priority: Optional[int],
    team_priority: Optional[int],
    policy_priority: Optional[int],
) -> int:
    """Resolve queue priority with SLA headers above the key/team/policy chain.

    Precedence: per-request SLA header > workflow-tag step SLA > API key
    ``default_priority`` > team priority > policy priority.

    Args:
        header_sla: Validated SLA from ``X-Logos-SLA``, or None.
        tag_sla: SLA from a workflow-step tag lookup, or None.
        default_priority: Key owner's configured priority (0 = unset).
        team_priority: Team admin priority (0 = unset).
        policy_priority: Policy-level priority (may be 0/None).

    Returns:
        Effective integer priority on the 1/5/10 scale (or NORMAL when unset).
    """
    if header_sla:
        return sla_to_priority(header_sla)
    if tag_sla:
        return sla_to_priority(tag_sla)
    # Lazy import: pipeline imports this module for header parsing at classify time.
    from logos.pipeline.pipeline import resolve_queue_priority

    return resolve_queue_priority(default_priority, team_priority, policy_priority)
