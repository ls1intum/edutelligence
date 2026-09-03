"""Reading spare serving capacity off the orchestrator.

The point of this runner is to spend capacity that would otherwise sit idle.
That only works if it can tell idle from busy, and if it gives the capacity
back the moment a user needs it. Both decisions are made here.

The orchestrator already knows the answer: every local provider reports, per
model, how many requests are in flight (``active``) against how many it can
serve concurrently (``max_capacity``), plus the depth of the queue waiting for
it. We read that, and treat a non-empty queue as saturation regardless of the
ratio — a user waiting is the strongest possible signal that there is nothing
spare to give away.

**Measured on the agent's own lane.** Summing every resident model in the
fleet answers a question nobody asked: an embedding model, a reranker and a
120B chat model share nothing but a building, and "1 of 60 slots busy" says
only that most of the fleet is asleep. What decides whether another agent
session is safe to start is the model that session will actually be served
by — so the reading is filtered to the models the runner's own key can
reach, and falls back to the fleet-wide figure only when none of them is
resident (there is nothing of ours to measure, and the old signal is the
better of the two available answers).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from .config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Reading:
    """One observation of the platform's serving load."""

    load: float  # 0..1; 1.0 means saturated or unknown
    busy_slots: int
    total_slots: int
    queue_total: int
    ok: bool  # False when the orchestrator could not be read
    detail: str = ""
    # False when no model is loaded anywhere: an empty fleet has no idle
    # capacity to spend, so there is nothing for the runner to reclaim.
    # Warming a lane in that situation is a different product decision, and
    # it must stay opt-in rather than the default.
    reclaimable: bool = True

    @property
    def saturated(self) -> bool:
        return self.queue_total > 0 or self.load >= 1.0


# When the orchestrator cannot be reached we must not assume the platform is
# idle: the safe failure mode for a scavenger is to stop scavenging.
UNKNOWN = Reading(load=1.0, busy_slots=0, total_slots=0, queue_total=0, ok=False, detail="orchestrator unreachable")


async def read_load(timeout_s: float = 5.0, models: frozenset[str] | None = None) -> Reading:
    """Ask the orchestrator how busy the serving lane we would use is.

    ``models`` are the names the runner's key can be served by; without them
    the reading is fleet-wide, which is what it was before and what it falls
    back to when none of ours is loaded.
    """
    if not settings.agent_api_key:
        return Reading(
            load=1.0,
            busy_slots=0,
            total_slots=0,
            queue_total=0,
            ok=False,
            detail="LOGOS_AGENT_API_KEY not configured",
        )

    url = f"{settings.orchestrator_url.rstrip('/')}/logosdb/scheduler_state"
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.get(url, headers={"Authorization": f"Bearer {settings.agent_api_key}"})
        if response.status_code != 200:
            return Reading(
                load=1.0,
                busy_slots=0,
                total_slots=0,
                queue_total=0,
                ok=False,
                detail=f"scheduler_state returned {response.status_code}",
            )
        payload = response.json()
    except Exception as exc:  # network, JSON, anything
        logger.warning("capacity read failed: %s", exc)
        return UNKNOWN

    return parse_scheduler_state(payload, models=models)


def parse_scheduler_state(payload: dict, models: frozenset[str] | None = None) -> Reading:
    """Turn the orchestrator's debug payload into a single load figure.

    Kept separate from the HTTP call so it can be tested against recorded
    payloads, and so a change in the orchestrator's shape surfaces as a test
    failure rather than as a runner that silently believes the fleet is idle.

    ``models`` narrows the ratio to the lane the runner's sessions are served
    by. The queue is deliberately *not* narrowed: models share GPUs, so a
    person waiting on any of them is a person this runner should get out of
    the way of.
    """
    wanted = {name.strip().lower() for name in (models or frozenset()) if name and name.strip()}
    queue_total = int(payload.get("queue_total") or 0)
    providers = ((payload.get("logosnode") or {}).get("providers")) or {}

    busy = 0
    total = 0
    fleet_busy = 0
    fleet_total = 0
    for provider in providers.values():
        deployments = (provider or {}).get("models") or {}
        for model in deployments.values():
            if not isinstance(model, dict):
                continue
            # Only loaded models hold capacity. An unloaded one contributes
            # nothing to either side of the ratio: its slots do not exist yet,
            # and counting them would make an idle-looking fleet out of a node
            # that simply has nothing resident.
            if not model.get("loaded"):
                continue
            capacity = int(model.get("max_capacity") or 0)
            if capacity <= 0:
                continue
            active = min(int(model.get("active") or 0), capacity)
            queue_total += int(model.get("queue_depth") or 0)
            fleet_total += capacity
            fleet_busy += active
            if wanted and str(model.get("model_name") or "").strip().lower() not in wanted:
                continue
            total += capacity
            busy += active

    fell_back = False
    if wanted and total == 0 and fleet_total > 0:
        # None of our models is resident, but the fleet is warm. There is
        # nothing of ours to measure, so the fleet-wide ratio decides — the
        # answer this function gave before it knew about lanes.
        busy, total, fell_back = fleet_busy, fleet_total, True

    if total == 0:
        # Nothing resident anywhere, so there is no idle capacity to reclaim —
        # the fleet is not busy either, but starting a session here would
        # create demand (a session loads a model and occupies GPUs nobody was
        # using), which is the opposite of what this runner exists to do.
        return Reading(
            load=0.0,
            busy_slots=0,
            total_slots=0,
            queue_total=queue_total,
            ok=True,
            detail="no loaded models",
            reclaimable=False,
        )

    if not wanted:
        lane = ""
    elif fell_back:
        lane = " across the fleet (none of the runner's own models is resident)"
    else:
        lane = " on the models the runner uses"
    return Reading(
        load=busy / total,
        busy_slots=busy,
        total_slots=total,
        queue_total=queue_total,
        ok=True,
        detail=f"{busy}/{total} slots busy{lane}",
    )


def start_decision(reading: Reading, *, running: int, paused: int, max_parallel: int | None = None) -> tuple[bool, str]:
    """Whether another session may start now, and why.

    ``max_parallel`` is the ceiling in force at this moment: an operator can
    lower it while the runner is running (see :mod:`controls`), so the
    decision takes it as an argument rather than reading the configured
    value here.
    """
    ceiling = settings.max_parallel_sessions if max_parallel is None else max_parallel
    if not reading.ok:
        return False, f"capacity unknown ({reading.detail})"
    if not reading.reclaimable:
        return False, f"nothing to reclaim ({reading.detail})"
    if ceiling <= 0:
        return False, "the parallel ceiling is set to zero"
    if running + paused >= ceiling:
        return False, (f"at the parallel-session ceiling " f"({running + paused}/{ceiling})")
    if reading.queue_total > 0:
        return False, f"users are queueing ({reading.queue_total} waiting)"
    if reading.load >= settings.start_below_load:
        return False, (
            f"load {reading.load:.0%} is at or above the start threshold " f"{settings.start_below_load:.0%}"
        )
    return True, f"load {reading.load:.0%}, {reading.detail}"


def pause_decision(reading: Reading) -> tuple[bool, str]:
    """Whether running sessions should be paused to return capacity."""
    if not reading.ok:
        # Unknown load with sessions running: pause. If the orchestrator is
        # unreachable something is wrong, and agent work is the cheapest thing
        # in the system to interrupt.
        return True, f"capacity unknown ({reading.detail})"
    if reading.queue_total > 0:
        return True, f"users are queueing ({reading.queue_total} waiting)"
    if reading.load >= settings.pause_above_load:
        return True, (f"load {reading.load:.0%} is at or above the pause threshold " f"{settings.pause_above_load:.0%}")
    return False, f"load {reading.load:.0%}"


def resume_decision(reading: Reading) -> tuple[bool, str]:
    """Whether a paused session may resume.

    Uses the *start* threshold rather than the pause threshold, so a session
    does not resume into the same load that just paused it and immediately
    pause again.
    """
    if not reading.ok:
        return False, f"capacity unknown ({reading.detail})"
    if not reading.reclaimable:
        # A paused session resumed into an empty fleet would be the only
        # thing running on it — demand created, not reclaimed.
        return False, f"nothing to reclaim ({reading.detail})"
    if reading.queue_total > 0:
        return False, f"users are queueing ({reading.queue_total} waiting)"
    if reading.load >= settings.start_below_load:
        return False, f"load {reading.load:.0%} still above resume threshold"
    return True, f"load {reading.load:.0%}"
