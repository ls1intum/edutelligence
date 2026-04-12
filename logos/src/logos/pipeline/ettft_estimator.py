# src/logos/pipeline/ettft_estimator.py
"""
Estimated Time To First Token (ETTFT) estimation and range-scaled correction.

Pure-function module with no state — fully unit-testable.
Maps runtime signals to latency estimates and range-scaled scheduling penalties.

Design: Range-scaled additive correction
  corrected = classification_weight - penalty
  penalty = min(expected_wait_s / NORMALIZATION_HORIZON_S, 1.0)
            × weight_span × CORRECTION_STRENGTH

This preserves same-state ordering (two models in the same infrastructure state
get identical penalty → classification ordering preserved) while making the
correction proportional to the weight span of the candidate set.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from logos.sdi.models import ModelSchedulerView, AzureCapacity


# ── Correction tuning knobs ─────────────────────────────────────────────

NORMALIZATION_HORIZON_S = 60.0      # Maximum expected wait before penalty saturates
CORRECTION_STRENGTH = 1.5           # Multiplier on the penalty fraction

# ── Infrastructure overhead constants (seconds) ────────────────────────

OVERHEAD_WARM_S = 0.0               # Loaded model → serve immediately
OVERHEAD_SLEEPING_S = 2.5           # Sleep → wake transition
OVERHEAD_COLD_S = 45.0              # Cold load from disk
OVERHEAD_RECLAIM_S = 8.0            # Additional cost when VRAM eviction needed
CLOUD_OVERHEAD_S = 0.3              # Azure/cloud baseline latency
CLOUD_LOW_HEADROOM_S = 5.0          # Azure near rate limit

# ── Weight span floor ──────────────────────────────────────────────────

MIN_SPAN_FRACTION = 0.2             # Floor as fraction of max(|w_max|, |w_min|)
MIN_SPAN_FLOOR = 1.0                # Absolute floor for weight span

# ── Queue estimation ───────────────────────────────────────────────────

DEFAULT_GENERATION_TIME_S = 3.0     # Fallback generation time per request


class ReadinessTier(Enum):
    WARM = "warm"                          # loaded, serve immediately
    SLEEPING = "sleeping"                  # sleeping lane, ~2.5s wake
    BUSY = "busy"                          # legacy compat: loaded + queue pressure
    COLD = "cold"                          # not loaded, ~45s load
    COLD_RECLAIM = "cold_reclaim"          # cold + must evict another model first
    SLEEPING_RECLAIM = "sleeping_reclaim"  # sleeping + must reclaim KV cache first
    UNAVAILABLE = "unavailable"            # no lanes / error


@dataclass(frozen=True)
class EttftEstimate:
    """ETTFT estimation result with infrastructure-aware wait decomposition."""

    expected_wait_s: float
    tier: ReadinessTier
    reasoning: str
    state_overhead_s: float = 0.0
    queue_wait_s: float = 0.0
    needs_reclaim: bool = False

    @property
    def ettft_ms(self) -> float:
        """Backward-compatible ETTFT in milliseconds."""
        if self.expected_wait_s == float("inf"):
            return float("inf")
        return self.expected_wait_s * 1000.0


# ── Weight span computation ────────────────────────────────────────────


def compute_weight_span(weights: list[float]) -> float:
    """Compute the dynamic range of classification weights.

    Handles: negative weights, identical weights, single candidate, empty list.
    The span is floored to prevent trivially small corrections.

    Returns max(spread, abs_floor, MIN_SPAN_FLOOR) where:
    - spread = max(weights) - min(weights)
    - abs_floor = max(|w_max|, |w_min|) × MIN_SPAN_FRACTION
    """
    if not weights:
        return MIN_SPAN_FLOOR
    w_max = max(weights)
    w_min = min(weights)
    spread = w_max - w_min
    abs_floor = max(abs(w_max), abs(w_min)) * MIN_SPAN_FRACTION
    return max(spread, abs_floor, MIN_SPAN_FLOOR)


# ── Corrected score computation ────────────────────────────────────────


def compute_corrected_score(
    classification_weight: float,
    expected_wait_s: float,
    weight_span: float,
) -> float:
    """Range-scaled additive correction.

    corrected = classification_weight - penalty
    penalty = min(expected_wait_s / NORMALIZATION_HORIZON_S, 1.0)
              × weight_span × CORRECTION_STRENGTH

    Properties:
    - Same-state ordering: two models with identical expected_wait_s get
      the same penalty → classification ordering preserved.
    - Bounded: maximum penalty = weight_span × CORRECTION_STRENGTH.
    - Zero pass-through: expected_wait_s ≤ 0 → no penalty.
    - Infinite wait: expected_wait_s = inf → full-span penalty.
    """
    if weight_span <= 0 or expected_wait_s <= 0:
        return classification_weight
    if expected_wait_s == float("inf"):
        return classification_weight - weight_span * CORRECTION_STRENGTH
    penalty_fraction = min(expected_wait_s / NORMALIZATION_HORIZON_S, 1.0)
    penalty = penalty_fraction * weight_span * CORRECTION_STRENGTH
    return classification_weight - penalty


# ── Queue wait estimation ──────────────────────────────────────────────


def _estimate_queue_wait_s(
    scheduler_queue_depth: int,
    effective_parallel: int,
    generation_time_s: float,
) -> float:
    """Estimate queue wait from depth, parallelism, and generation time.

    queue_rounds = scheduler_queue_depth / effective_parallel
    queue_wait_s = queue_rounds × generation_time_s
    """
    if scheduler_queue_depth <= 0:
        return 0.0
    parallel = max(effective_parallel, 1)
    queue_rounds = scheduler_queue_depth / parallel
    return queue_rounds * generation_time_s


# ── Local (logosnode) estimation ───────────────────────────────────────


def estimate_ettft_local(
    view: ModelSchedulerView,
    effective_parallel: int = 1,
    generation_time_s: float = DEFAULT_GENERATION_TIME_S,
    available_vram_mb: float = float("inf"),
    model_vram_mb: float = 0.0,
    kv_budget_mb: float = 0.0,
    scheduler_queue_depth: int = 0,
) -> EttftEstimate:
    """Estimate ETTFT for a local (logosnode) model from its scheduler view.

    Decision tree:
    1. No lanes or all stopped/error → UNAVAILABLE
    2. All lanes cold/starting:
       a. model_vram_mb > available_vram_mb → COLD_RECLAIM (45s + 8s)
       b. otherwise → COLD (45s)
    3. Best lane sleeping:
       a. kv_budget_mb > available_vram_mb → SLEEPING_RECLAIM (2.5s + 8s)
       b. otherwise → SLEEPING (2.5s)
    4. Best lane loaded/running → WARM (0s)
    5. Queue penalty added in all non-UNAVAILABLE cases:
       queue_wait_s = (scheduler_queue_depth / effective_parallel) × generation_time_s
    """
    if not view.lanes:
        return EttftEstimate(
            expected_wait_s=float("inf"),
            tier=ReadinessTier.UNAVAILABLE,
            reasoning="No lanes available",
        )

    active_states = {s.runtime_state for s in view.lanes}
    if active_states <= {"stopped", "error"}:
        return EttftEstimate(
            expected_wait_s=float("inf"),
            tier=ReadinessTier.UNAVAILABLE,
            reasoning=f"All lanes in non-routable states: {active_states}",
        )

    best_state = view.best_lane_state
    queue_wait_s = _estimate_queue_wait_s(
        scheduler_queue_depth, effective_parallel, generation_time_s,
    )

    # ── Cold: no loaded/running lanes ──────────────────────────────────
    if best_state in ("cold", "starting"):
        needs_reclaim = model_vram_mb > 0 and model_vram_mb > available_vram_mb
        if needs_reclaim:
            overhead = OVERHEAD_COLD_S + OVERHEAD_RECLAIM_S
            tier = ReadinessTier.COLD_RECLAIM
            reason = (
                f"Cold + reclaim: model needs {model_vram_mb:.0f}MB, "
                f"available {available_vram_mb:.0f}MB"
            )
        else:
            overhead = OVERHEAD_COLD_S
            tier = ReadinessTier.COLD
            reason = f"Best lane state is '{best_state}', cold-start ~{OVERHEAD_COLD_S:.0f}s"

        expected = overhead + queue_wait_s
        if queue_wait_s > 0:
            reason += f" + queue {queue_wait_s:.1f}s ({scheduler_queue_depth}q/{effective_parallel}p)"

        return EttftEstimate(
            expected_wait_s=expected,
            tier=tier,
            reasoning=reason,
            state_overhead_s=overhead,
            queue_wait_s=queue_wait_s,
            needs_reclaim=needs_reclaim,
        )

    # ── Sleeping: best lane is sleeping, needs wake ────────────────────
    if best_state == "sleeping":
        needs_reclaim = kv_budget_mb > 0 and kv_budget_mb > available_vram_mb
        if needs_reclaim:
            overhead = OVERHEAD_SLEEPING_S + OVERHEAD_RECLAIM_S
            tier = ReadinessTier.SLEEPING_RECLAIM
            reason = (
                f"Sleeping + reclaim: KV cache needs {kv_budget_mb:.0f}MB, "
                f"available {available_vram_mb:.0f}MB"
            )
        else:
            overhead = OVERHEAD_SLEEPING_S
            tier = ReadinessTier.SLEEPING
            reason = f"Best lane is sleeping, wake ~{OVERHEAD_SLEEPING_S:.1f}s"

        expected = overhead + queue_wait_s
        if queue_wait_s > 0:
            reason += f" + queue {queue_wait_s:.1f}s ({scheduler_queue_depth}q/{effective_parallel}p)"

        return EttftEstimate(
            expected_wait_s=expected,
            tier=tier,
            reasoning=reason,
            state_overhead_s=overhead,
            queue_wait_s=queue_wait_s,
            needs_reclaim=needs_reclaim,
        )

    # ── Loaded or running → WARM ──────────────────────────────────────
    overhead = OVERHEAD_WARM_S
    expected = overhead + queue_wait_s
    reason = "Loaded and warm"
    if queue_wait_s > 0:
        reason += f", queue {queue_wait_s:.1f}s ({scheduler_queue_depth}q/{effective_parallel}p)"

    return EttftEstimate(
        expected_wait_s=expected,
        tier=ReadinessTier.WARM,
        reasoning=reason,
        state_overhead_s=overhead,
        queue_wait_s=queue_wait_s,
    )


# ── Azure estimation ──────────────────────────────────────────────────


def estimate_ettft_azure(capacity: Optional[AzureCapacity]) -> EttftEstimate:
    """Estimate ETTFT for an Azure model from rate limit state.

    - has_capacity=True, remaining_requests > 10 → WARM (0.3s)
    - has_capacity=True, remaining_requests ≤ 10 → WARM (5.0s, low headroom)
    - has_capacity=False or None → UNAVAILABLE
    """
    if capacity is None or not capacity.has_capacity:
        return EttftEstimate(
            expected_wait_s=float("inf"),
            tier=ReadinessTier.UNAVAILABLE,
            reasoning="Azure: no capacity or rate-limited",
        )

    remaining = capacity.rate_limit_remaining_requests
    if remaining is not None and remaining <= 10:
        return EttftEstimate(
            expected_wait_s=CLOUD_LOW_HEADROOM_S,
            tier=ReadinessTier.WARM,
            reasoning=f"Azure: low headroom (remaining_requests={remaining})",
            state_overhead_s=CLOUD_LOW_HEADROOM_S,
        )

    return EttftEstimate(
        expected_wait_s=CLOUD_OVERHEAD_S,
        tier=ReadinessTier.WARM,
        reasoning=f"Azure: healthy capacity (remaining_requests={remaining})",
        state_overhead_s=CLOUD_OVERHEAD_S,
    )
