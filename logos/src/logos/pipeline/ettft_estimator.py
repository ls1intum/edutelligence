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
_BUSY_QUEUE_MULTIPLIER = 1.0  # legacy linear multiplier (unused, kept for reference)
_BUSY_QUEUE_EXPONENT_BASE = 1.3  # exponential backoff: penalty = base_ttft * (1.3^depth - 1)


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


def estimate_ettft_local(
    view: ModelSchedulerView,
    eviction_cost_ms: float = 0.0,
) -> EttftEstimate:
    """Estimate ETTFT for a local (logosnode) model from its scheduler view.

    Args:
        view: Current model scheduler state.
        eviction_cost_ms: Additional latency if loading this model requires
            evicting another lane to free VRAM. Only applied to COLD tier.

    Decision tree:
    1. No lanes → UNAVAILABLE
    2. All lanes stopped (no error) → UNAVAILABLE
    3. All lanes in error/stopped but at least one error → COLD (recovery cold-load)
    4. All lanes cold/starting → COLD (~45s + eviction_cost_ms)
    5. Best lane sleeping → SLEEPING (~2s wake time)
    6. Best lane loaded, queue_waiting > 0 → BUSY (TTFT * (1 + queue_depth))
    7. Best lane loaded, low queue → WARM (measured TTFT or 200ms default)
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
        if "error" in active_states:
            # Error is transient (e.g. OOM crash). The capacity planner can cold-load
            # a fresh lane — don't return UNAVAILABLE. Treat as COLD so the request
            # reaches context resolution where prepare_lane_for_request will attempt
            # recovery. If VRAM is still insufficient the cold-load fails there and
            # the request gets a 503 only after genuinely exhausting options.
            ettft_ms = _DEFAULT_COLD_MS + eviction_cost_ms
            tier, penalty = classify_tier(ettft_ms)
            return EttftEstimate(
                ettft_ms=ettft_ms,
                tier=tier,
                penalty=penalty,
                reasoning=f"Lanes in error — cold-load recovery will be attempted (states: {active_states})",
            )
        # All lanes intentionally stopped — nothing will recover them without
        # external intervention; no point queuing.
        return EttftEstimate(
            ettft_ms=float("inf"),
            tier=ReadinessTier.UNAVAILABLE,
            penalty=TIER_THRESHOLDS[ReadinessTier.UNAVAILABLE]["penalty"],
            reasoning=f"All lanes stopped: {active_states}",
        )

    best_state = view.best_lane_state

    # Cold: no loaded/running lanes
    if best_state in ("cold", "starting"):
        ettft_ms = _DEFAULT_COLD_MS + eviction_cost_ms
        eviction_note = f" +{eviction_cost_ms:.0f}ms eviction" if eviction_cost_ms > 0 else ""
        tier, penalty = classify_tier(ettft_ms)
        return EttftEstimate(
            ettft_ms=ettft_ms,
            tier=tier,
            penalty=penalty,
            reasoning=f"Best lane state is '{best_state}', cold-start estimated at {ettft_ms:.0f}ms{eviction_note}",
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
        # Exponential backoff: penalty grows super-linearly with queue depth.
        # Cap at _DEFAULT_COLD_MS so hot+queued never scores worse than cold start.
        queue_depth = view.aggregate_queue_waiting
        queue_delay = base_ttft_ms * (_BUSY_QUEUE_EXPONENT_BASE ** queue_depth - 1)
        queue_delay = min(queue_delay, _DEFAULT_COLD_MS)
        ettft_ms = base_ttft_ms + queue_delay
        tier, penalty = classify_tier(ettft_ms)
        return EttftEstimate(
            ettft_ms=ettft_ms,
            tier=tier,
            penalty=penalty,
            reasoning=f"Loaded with queue_waiting={queue_depth:.0f}, "
                      f"base_ttft={base_ttft_ms:.0f}ms, queue_penalty={queue_delay:.0f}ms, total={ettft_ms:.0f}ms",
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
