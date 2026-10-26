"""Records that put locked lanes back the way they were after a worker restart.

A worker that restarts comes back without its lanes. For a lane an operator
locked, and for every lane of a worker an operator locked, ``lane_locks``
keeps the lane as the worker last reported it (column ``restore_lanes``):
the lane config the worker started it with, which names its model, GPUs and
vLLM settings, and whether it slept. The capacity planner loads a recorded
lane that is missing from the worker's report again with that config, so it
lands on the same GPUs.

A record keeps a lane that is gone, because that is what it is for. It
forgets the lane only when an operator unloads it or the lock is released.
"""

from __future__ import annotations

from typing import Any, Iterable

# The lane id of a lock on a whole worker. No worker lane has this id.
WORKER_LOCK_ID = "*"

# Marks a lane put back awake that slept before the restart and is still to
# be put to sleep. Kept in the record, so it survives an orchestrator restart.
RESLEEP = "resleep"
# Marks a lane an operator is unloading, with one entry (the time it was
# sent) per unload still on its way: the lane is neither recorded again nor
# put back while any of them may still unload it.
UNLOADING = "unloading"

# A lane in these states, or in a transition, is not recorded: it is not in a
# state to put back.
_UNRECORDED_STATES = frozenset({"stopped", "error", "cold"})


def observed_lanes(runtime_lanes: Iterable[Any]) -> dict[str, dict[str, Any]]:
    """The lanes of a worker report that can be put back, as records by lane id."""
    observed: dict[str, dict[str, Any]] = {}
    for lane in runtime_lanes:
        if not isinstance(lane, dict):
            continue
        lane_config = lane.get("lane_config")
        lane_id = str(lane.get("lane_id") or "")
        if not lane_id or not isinstance(lane_config, dict) or not lane_config.get("model"):
            continue
        if lane.get("transition") or str(lane.get("runtime_state") or "") in _UNRECORDED_STATES:
            continue
        sleeping = lane.get("sleep_state") == "sleeping" or lane.get("runtime_state") == "sleeping"
        observed[lane_id] = {"lane_config": {**lane_config, "lane_id": lane_id}, "sleeping": sleeping}
    return observed


def updated_record(
    previous: dict[str, dict[str, Any]] | None,
    observed: dict[str, dict[str, Any]],
    lane_id: str,
    keep_sleeping: Iterable[str] = (),
) -> dict[str, dict[str, Any]]:
    """The record of a lock after a worker report.

    A lane lock records its own lane; a worker lock records every lane. Lanes
    in *keep_sleeping* keep their recorded sleep state: they were just put
    back awake and are about to be put to sleep again.
    """
    # A record is read back from the table: drop entries that cannot be put
    # back rather than fail the planner cycle on them. The rewrite repairs it.
    record = {lane_id: entry for lane_id, entry in (previous or {}).items() if _keepable(entry)}
    seen = observed if lane_id == WORKER_LOCK_ID else {k: v for k, v in observed.items() if k == lane_id}
    for seen_id, entry in seen.items():
        if UNLOADING in record.get(seen_id, {}):
            continue  # being unloaded: the report still shows it
        if seen_id in keep_sleeping and seen_id in record:
            entry = {**entry, "sleeping": record[seen_id].get("sleeping", False)}
            if record[seen_id].get(RESLEEP):
                entry[RESLEEP] = True
        record[seen_id] = entry
    return record


def _restorable(entry: Any) -> bool:
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("lane_config"), dict)
        and bool(entry["lane_config"].get("model"))
        and UNLOADING not in entry
    )


def _keepable(entry: Any) -> bool:
    return _restorable(entry) or (isinstance(entry, dict) and bool(unload_attempts(entry)))


def unload_attempts(entry: Any) -> list[float]:
    """The unloads of a lane still on their way, by the time each was sent."""
    value = entry.get(UNLOADING) if isinstance(entry, dict) else None
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, list):
        return [float(item) for item in value if isinstance(item, (int, float))]
    return []


def unloading_lanes(record: dict[str, dict[str, Any]] | None) -> dict[str, list[float]]:
    """Lanes of a record an operator is unloading, with their unloads still on their way."""
    return {lane_id: attempts for lane_id, entry in (record or {}).items() if (attempts := unload_attempts(entry))}


def missing_lanes(
    record: dict[str, dict[str, Any]] | None,
    present_lane_ids: Iterable[str],
) -> list[tuple[str, dict[str, Any]]]:
    """Recorded lanes the worker does not report, in record order."""
    present = set(present_lane_ids)
    return [
        (lane_id, entry) for lane_id, entry in (record or {}).items() if lane_id not in present and _restorable(entry)
    ]
