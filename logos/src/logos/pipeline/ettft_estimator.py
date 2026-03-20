# src/logos/pipeline/ettft_estimator.py
"""
Estimated Time To First Token (ETTFT) estimation module.

Pure-function module with no state — fully unit-testable.
Maps runtime signals to latency estimates and scheduling penalties.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from logos.sdi.models import ModelSchedulerView, AzureCapacity


class ReadinessTier(Enum):
    WARM = "warm"           # loaded, low queue → penalty 0
    SLEEPING = "sleeping"   # sleeping lane, 0.5-3s wake → penalty 2
    BUSY = "busy"           # loaded but queue pressure → penalty 8
    COLD = "cold"           # not loaded, 30-90s load → penalty 20
    UNAVAILABLE = "unavailable"  # no lanes / error → penalty inf


@dataclass(frozen=True)
class EttftEstimate:
    ettft_ms: float
    tier: ReadinessTier
    penalty: float
    reasoning: str


# Configurable tier thresholds (tuning knobs for thesis Chapter 6)
TIER_THRESHOLDS = {
    ReadinessTier.WARM:        {"max_ms": 500.0,    "penalty": 0.0},
    ReadinessTier.SLEEPING:    {"max_ms": 3000.0,   "penalty": 2.0},
    ReadinessTier.BUSY:        {"max_ms": 10000.0,  "penalty": 8.0},
    ReadinessTier.COLD:        {"max_ms": 60000.0,  "penalty": 20.0},
    ReadinessTier.UNAVAILABLE: {"max_ms": float("inf"), "penalty": float("inf")},
}

# Default ETTFT values for states where measurement is unavailable
_DEFAULT_WARM_MS = 200.0
_DEFAULT_SLEEPING_MS = 2000.0
_DEFAULT_COLD_MS = 45000.0
_BUSY_QUEUE_MULTIPLIER = 1.0  # each queued request adds ~1 TTFT worth of delay


def classify_tier(ettft_ms: float) -> tuple[ReadinessTier, float]:
    """Map raw ETTFT (ms) to tier and penalty.

    Iterates through tiers in warmth order; first whose max_ms >= ettft_ms wins.
    """
    for tier in (ReadinessTier.WARM, ReadinessTier.SLEEPING, ReadinessTier.BUSY, ReadinessTier.COLD):
        if ettft_ms <= TIER_THRESHOLDS[tier]["max_ms"]:
            return tier, TIER_THRESHOLDS[tier]["penalty"]
    return ReadinessTier.UNAVAILABLE, TIER_THRESHOLDS[ReadinessTier.UNAVAILABLE]["penalty"]


def compute_corrected_score(classification_weight: float, penalty: float) -> float:
    """corrected_score = classification_weight - penalty."""
    if penalty == float("inf"):
        return float("-inf")
    return classification_weight - penalty


def estimate_ettft_local(view: ModelSchedulerView) -> EttftEstimate:
    """Estimate ETTFT for a local (logosnode) model from its scheduler view.

    Decision tree:
    1. No lanes or all stopped/error → UNAVAILABLE
    2. All lanes cold/starting → COLD (~45s median cold-start)
    3. Best lane sleeping → SLEEPING (~2s wake time)
    4. Best lane loaded, queue_waiting > 0 → BUSY (TTFT * (1 + queue_depth))
    5. Best lane loaded, low queue → WARM (measured TTFT or 200ms default)
    """
    if not view.lanes:
        return EttftEstimate(
            ettft_ms=float("inf"),
            tier=ReadinessTier.UNAVAILABLE,
            penalty=TIER_THRESHOLDS[ReadinessTier.UNAVAILABLE]["penalty"],
            reasoning="No lanes available",
        )

    # Check if all lanes are in terminal non-routable states
    active_states = {s.runtime_state for s in view.lanes}
    if active_states <= {"stopped", "error"}:
        return EttftEstimate(
            ettft_ms=float("inf"),
            tier=ReadinessTier.UNAVAILABLE,
            penalty=TIER_THRESHOLDS[ReadinessTier.UNAVAILABLE]["penalty"],
            reasoning=f"All lanes in non-routable states: {active_states}",
        )

    best_state = view.best_lane_state

    # Cold: no loaded/running lanes
    if best_state in ("cold", "starting"):
        ettft_ms = _DEFAULT_COLD_MS
        tier, penalty = classify_tier(ettft_ms)
        return EttftEstimate(
            ettft_ms=ettft_ms,
            tier=tier,
            penalty=penalty,
            reasoning=f"Best lane state is '{best_state}', cold-start estimated at {ettft_ms:.0f}ms",
        )

    # Sleeping: best lane is sleeping, needs wake
    if best_state == "sleeping":
        ettft_ms = _DEFAULT_SLEEPING_MS
        tier, penalty = classify_tier(ettft_ms)
        return EttftEstimate(
            ettft_ms=ettft_ms,
            tier=tier,
            penalty=penalty,
            reasoning=f"Best lane is sleeping (sleep_state={view.best_sleep_state}), wake ~{ettft_ms:.0f}ms",
        )

    # Loaded or running — check queue pressure
    base_ttft_ms = (view.warmest_ttft_p95_seconds * 1000) if view.warmest_ttft_p95_seconds > 0 else _DEFAULT_WARM_MS

    if view.aggregate_queue_waiting > 0:
        queue_delay = view.aggregate_queue_waiting * base_ttft_ms * _BUSY_QUEUE_MULTIPLIER
        ettft_ms = base_ttft_ms + queue_delay
        tier, penalty = classify_tier(ettft_ms)
        return EttftEstimate(
            ettft_ms=ettft_ms,
            tier=tier,
            penalty=penalty,
            reasoning=f"Loaded with queue_waiting={view.aggregate_queue_waiting:.0f}, "
                      f"base_ttft={base_ttft_ms:.0f}ms, total={ettft_ms:.0f}ms",
        )

    # Warm: loaded, no queue pressure
    ettft_ms = base_ttft_ms
    tier, penalty = classify_tier(ettft_ms)
    return EttftEstimate(
        ettft_ms=ettft_ms,
        tier=tier,
        penalty=penalty,
        reasoning=f"Loaded and warm, ttft_p95={base_ttft_ms:.0f}ms",
    )


def estimate_ettft_azure(capacity: Optional[AzureCapacity]) -> EttftEstimate:
    """Estimate ETTFT for an Azure model from rate limit state.

    - has_capacity=True, remaining_requests > 10 → WARM (300ms, penalty=0)
    - has_capacity=True, remaining_requests <= 10 → BUSY (5000ms, penalty=8)
    - has_capacity=False or None → UNAVAILABLE
    """
    if capacity is None or not capacity.has_capacity:
        return EttftEstimate(
            ettft_ms=float("inf"),
            tier=ReadinessTier.UNAVAILABLE,
            penalty=TIER_THRESHOLDS[ReadinessTier.UNAVAILABLE]["penalty"],
            reasoning="Azure: no capacity or rate-limited",
        )

    remaining = capacity.rate_limit_remaining_requests
    if remaining is not None and remaining <= 10:
        ettft_ms = 5000.0
        tier, penalty = classify_tier(ettft_ms)
        return EttftEstimate(
            ettft_ms=ettft_ms,
            tier=tier,
            penalty=penalty,
            reasoning=f"Azure: low headroom (remaining_requests={remaining})",
        )

    ettft_ms = 300.0
    tier, penalty = classify_tier(ettft_ms)
    return EttftEstimate(
        ettft_ms=ettft_ms,
        tier=tier,
        penalty=penalty,
        reasoning=f"Azure: healthy capacity (remaining_requests={remaining})",
    )
