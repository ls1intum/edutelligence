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
session is safe to start is the deployment that session will actually be
served by — so the reading counts exactly the deployments the runner's key
can reach, by provider and model id rather than by name. A name is not
enough: the same model is served by providers this key has no permission
for, and their idle slots would make a busy lane look free.

It falls back to the fleet-wide figure only when none of those deployments
is resident — there is nothing of ours to measure then, and the older signal
is the better of the two available answers. A key that reaches *nothing*
is a different thing entirely, and fails closed.
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


async def read_load(timeout_s: float = 5.0, lane: frozenset[tuple[str, str]] | None = None) -> Reading:
    """Ask the orchestrator how busy the serving lane we would use is.

    ``lane`` holds the (provider id, model id) pairs the runner's key can be
    served by. ``None`` asks for the fleet-wide figure, which is what this
    answered before it knew about lanes; an empty set says the key reaches
    nothing at all, which is not the same question and is refused.
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

    return parse_scheduler_state(payload, lane=lane)


def parse_scheduler_state(payload: dict, lane: frozenset[tuple[str, str]] | None = None) -> Reading:
    """Turn the orchestrator's debug payload into a single load figure.

    Kept separate from the HTTP call so it can be tested against recorded
    payloads, and so a change in the orchestrator's shape surfaces as a test
    failure rather than as a runner that silently believes the fleet is idle.

    ``lane`` narrows the ratio to the deployments the runner's sessions are
    served by, matched on the payload's own provider and model ids. The
    queue is deliberately *not* narrowed: models share GPUs, so a person
    waiting on any of them is a person this runner should get out of the way
    of.
    """
    if lane is not None and not lane:
        # A key that reaches no local deployment has no lane to measure and
        # nothing it could legitimately run on. Refusing here rather than
        # measuring the fleet keeps a paused session from being resumed into
        # a permission it no longer has.
        return Reading(
            load=1.0,
            busy_slots=0,
            total_slots=0,
            queue_total=int(payload.get("queue_total") or 0),
            ok=True,
            detail="the runner's key reaches no local deployment",
            reclaimable=False,
        )
    wanted = set(lane or ())
    queue_total = int(payload.get("queue_total") or 0)
    # Counted per model as well as in total: a lane holding a saturated
    # model and an idle one is not half busy — a session bound for the
    # saturated one has nowhere to go, and the average would hide that.
    per_model: dict[str, list[int]] = {}
    providers = ((payload.get("logosnode") or {}).get("providers")) or {}

    busy = 0
    total = 0
    fleet_busy = 0
    fleet_total = 0
    for provider_id, provider in providers.items():
        deployments = (provider or {}).get("models") or {}
        for model_id, model in deployments.items():
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
            if wanted and (str(provider_id), str(model_id)) not in wanted:
                continue
            total += capacity
            busy += active
            name = str(model.get("model_name") or model_id)
            slots = per_model.setdefault(name, [0, 0])
            slots[0] += active
            slots[1] += capacity

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

    if wanted and not fell_back and len(per_model) > 1:
        # The busiest of them decides. Being kept out of an idle model
        # because another is full costs this runner some capacity; letting a
        # session into a full one costs a user their turn.
        name, (model_busy, model_total) = max(
            per_model.items(), key=lambda item: (item[1][0] / item[1][1]) if item[1][1] else 0.0
        )
        return Reading(
            load=model_busy / model_total,
            busy_slots=model_busy,
            total_slots=model_total,
            queue_total=queue_total,
            ok=True,
            detail=f"{model_busy}/{model_total} slots busy on {name}, the busiest model this runner may use",
        )

    if not wanted:
        lane_note = ""
    elif fell_back:
        lane_note = " across the fleet (none of the runner's own models is resident)"
    else:
        lane_note = " on the model this runner uses"
    return Reading(
        load=busy / total,
        busy_slots=busy,
        total_slots=total,
        queue_total=queue_total,
        ok=True,
        detail=f"{busy}/{total} slots busy{lane_note}",
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
