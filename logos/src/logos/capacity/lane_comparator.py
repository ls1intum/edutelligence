"""Canonical comparator for ranking lanes serving the same model.

The same ordering is used in three places that previously disagreed:
  - capacity_planner._pick_request_target_lane
  - capacity_planner wake-target selection (sleeping_lanes pick)
  - correcting_scheduler tie-break across logosnode candidates

Order (best first):
  state_rank, queue_waiting, requests_running, active_requests,
  ttft_p95_seconds, -effective_vram_mb, lane_id
"""
from __future__ import annotations

from logos.sdi.models import LaneSchedulerSignals

_STATE_RANK: dict[str, int] = {
    "running": 0,
    "loaded": 1,
    "sleeping": 2,
    "cold": 3,
    "starting": 4,
}


def lane_sort_key(lane: LaneSchedulerSignals) -> tuple:
    """Return the canonical sort key for ``lane`` (lower is better).

    Tuple ordering — every dimension breaks ties for the next:

      1. ``state_rank``        — running < loaded < sleeping < cold < starting
                                 (unknown states fall to the end via 99).
      2. ``queue_waiting``      — fewer queued requests preferred.
      3. ``requests_running``   — fewer in-flight preferred.
      4. ``active_requests``    — fewer admitted preferred.
      5. ``ttft_p95_seconds``   — faster first-token preferred.
      6. ``-effective_vram_mb`` — more resident VRAM preferred (negated so
                                  the natural-sort min picks the larger).
                                  ``None``/``0`` is treated as 0 MB.
      7. ``lane_id``            — alphabetical, stable final tiebreak.

    The returned tuple is intended for ``sorted(..., key=lane_sort_key)`` or
    ``min(..., key=lane_sort_key)``. Does not raise; relies on each named
    attribute being present on ``LaneSchedulerSignals``.
    """
    return (
        _STATE_RANK.get(lane.runtime_state, 99),
        lane.queue_waiting,
        lane.requests_running,
        lane.active_requests,
        lane.ttft_p95_seconds,
        -float(lane.effective_vram_mb or 0.0),
        lane.lane_id,
    )


def best_lane(lanes: list[LaneSchedulerSignals]) -> LaneSchedulerSignals | None:
    """Return the lane that ranks first under :func:`lane_sort_key`.

    Args:
        lanes: candidate lanes, all assumed to serve the same model.

    Returns:
        The single best lane, or ``None`` when ``lanes`` is empty. Never
        raises.
    """
    if not lanes:
        return None
    return min(lanes, key=lane_sort_key)
