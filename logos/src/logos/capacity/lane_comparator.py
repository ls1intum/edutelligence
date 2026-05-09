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
    if not lanes:
        return None
    return min(lanes, key=lane_sort_key)
