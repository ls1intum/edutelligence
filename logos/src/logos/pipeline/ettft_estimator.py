# src/logos/pipeline/ettft_estimator.py
"""
Readiness classification module for scheduling decisions.

Pure-function module with no state — fully unit-testable.
Maps runtime signals to a ReadinessTier that the scheduler uses for
candidate selection (no numerical penalties, no ETTFT math).
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from logos.sdi.models import ModelSchedulerView, AzureCapacity
from logos.sdi.logos_peer_facade import PeerCapacity


class ReadinessTier(Enum):
    READY = "ready"              # loaded/running, queue_waiting == 0
    QUEUEING = "queueing"        # loaded/running, queue_waiting > 0
    SLEEPING = "sleeping"        # sleeping lane, needs wake
    COLD = "cold"                # not loaded, cold/starting
    UNAVAILABLE = "unavailable"  # no lanes / all stopped/error


@dataclass(frozen=True)
class ReadinessSignal:
    tier: ReadinessTier
    reasoning: str


def classify_local(view: ModelSchedulerView) -> ReadinessSignal:
    """Classify readiness for a local (logosnode) model from its scheduler view.

    Decision tree:
    1. No lanes or all stopped/error -> UNAVAILABLE
    2. Best lane cold/starting -> COLD
    3. Best lane sleeping -> SLEEPING
    4. Best lane loaded/running, aggregate queue_waiting > 0 -> QUEUEING
    5. Best lane loaded/running, queue_waiting == 0 -> READY
    """
    if not view.lanes:
        return ReadinessSignal(
            tier=ReadinessTier.UNAVAILABLE,
            reasoning="No lanes available",
        )

    active_states = {s.runtime_state for s in view.lanes}
    if active_states <= {"stopped", "error"}:
        return ReadinessSignal(
            tier=ReadinessTier.UNAVAILABLE,
            reasoning=f"All lanes in non-routable states: {active_states}",
        )

    best_state = view.best_lane_state

    if best_state in ("cold", "starting"):
        return ReadinessSignal(
            tier=ReadinessTier.COLD,
            reasoning=f"Best lane state is '{best_state}', cold-start required",
        )

    if best_state == "sleeping":
        return ReadinessSignal(
            tier=ReadinessTier.SLEEPING,
            reasoning=f"Best lane is sleeping (sleep_state={view.best_sleep_state})",
        )

    # Loaded or running
    if view.aggregate_queue_waiting > 0:
        return ReadinessSignal(
            tier=ReadinessTier.QUEUEING,
            reasoning=f"Loaded but vLLM queue_waiting={view.aggregate_queue_waiting:.0f}",
        )

    return ReadinessSignal(
        tier=ReadinessTier.READY,
        reasoning="Loaded and queue_waiting=0",
    )


def classify_azure(capacity: Optional[AzureCapacity]) -> ReadinessSignal:
    """Classify readiness for an Azure model from rate limit state.

    - has_capacity=True -> READY
    - has_capacity=False or None -> UNAVAILABLE
    """
    if capacity is None or not capacity.has_capacity:
        return ReadinessSignal(
            tier=ReadinessTier.UNAVAILABLE,
            reasoning="Azure: no capacity or rate-limited",
        )

    remaining = capacity.rate_limit_remaining_requests
    return ReadinessSignal(
        tier=ReadinessTier.READY,
        reasoning=f"Azure: healthy capacity (remaining_requests={remaining})",
    )


def classify_peer(capacity: Optional[PeerCapacity]) -> ReadinessSignal:
    """Classify readiness for a `logos_peer` upstream from its capacity snapshot.

    - capacity is None / peer unhealthy / model not exposed -> UNAVAILABLE
    - peer healthy but free_slots == 0 / queue_depth > 0     -> QUEUEING
    - peer healthy with capacity                             -> READY
    """
    if capacity is None or not capacity.is_healthy:
        return ReadinessSignal(
            tier=ReadinessTier.UNAVAILABLE,
            reasoning="logos_peer: unhealthy or unregistered",
        )
    if not capacity.has_capacity:
        return ReadinessSignal(
            tier=ReadinessTier.QUEUEING,
            reasoning=(
                f"logos_peer: healthy but no free slots "
                f"(free_slots={capacity.free_slots}, queue_depth={capacity.queue_depth})"
            ),
        )
    if capacity.queue_depth > 0:
        return ReadinessSignal(
            tier=ReadinessTier.QUEUEING,
            reasoning=f"logos_peer: healthy with queue_depth={capacity.queue_depth}",
        )
    return ReadinessSignal(
        tier=ReadinessTier.READY,
        reasoning=f"logos_peer: healthy (free_slots={capacity.free_slots})",
    )
