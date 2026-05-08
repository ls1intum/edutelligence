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

ETTFT decomposes into three additive phases:
  1. State overhead  — wake or cold-load latency
  2. Reclaim overhead — VRAM eviction cost, context-aware:
     idle/sleeping eviction is cheap, draining busy lanes is expensive
  3. Queue wait — queued requests × observed per-request service time
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, List

from logos.sdi.models import ModelSchedulerView, AzureCapacity, LaneSchedulerSignals


# ── Correction tuning knobs ─────────────────────────────────────────────

NORMALIZATION_HORIZON_S = 60.0      # Maximum expected wait before penalty saturates
CORRECTION_STRENGTH = 1.5           # Multiplier on the penalty fraction

# ── Infrastructure overhead constants (seconds) ────────────────────────

OVERHEAD_WARM_S = 0.0               # Loaded model → serve immediately
OVERHEAD_SLEEPING_S = 2.5           # Sleep → wake transition
OVERHEAD_COLD_S = 45.0              # Cold load from disk
CLOUD_OVERHEAD_S = 0.3              # Azure/cloud baseline latency
CLOUD_LOW_HEADROOM_S = 5.0          # Azure near rate limit

# ── Reclaim overhead (context-aware) ──────────────────────────────────

RECLAIM_IDLE_EVICT_S = 3.0          # Evicting idle/sleeping lanes (fast)
RECLAIM_BUSY_DRAIN_S = 30.0         # Draining busy lanes (up to 60s timeout, avg ~30s)

# ── Weight span floor ──────────────────────────────────────────────────

MIN_SPAN_FRACTION = 0.2             # Floor as fraction of max(|w_max|, |w_min|)
MIN_SPAN_FLOOR = 1.0                # Absolute floor for weight span

# ── Queue estimation ───────────────────────────────────────────────────

DEFAULT_GENERATION_TIME_S = 3.0     # Fallback generation time when no observed data


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
    reclaim_overhead_s: float = 0.0
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


# ── Service time estimation ───────────────────────────────────────────


def _effective_service_time_s(
    observed_e2e_p50_s: float,
    fallback_s: float = DEFAULT_GENERATION_TIME_S,
) -> float:
    """Return the best available per-request service time estimate.

    Uses the observed e2e latency p50 from vLLM metrics when available,
    falling back to the configured constant when the model has no history
    (e.g. just loaded, or histogram not yet populated).
    """
    if observed_e2e_p50_s > 0:
        return observed_e2e_p50_s
    return fallback_s


# ── Queue wait estimation ──────────────────────────────────────────────


def _estimate_queue_wait_s(
    scheduler_queue_depth: int,
    effective_parallel: int,
    service_time_s: float,
) -> float:
    """Estimate queue wait from depth, parallelism, and service time.

    queue_rounds = scheduler_queue_depth / effective_parallel
    queue_wait_s = queue_rounds × service_time_s
    """
    if scheduler_queue_depth <= 0:
        return 0.0
    parallel = max(effective_parallel, 1)
    queue_rounds = scheduler_queue_depth / parallel
    return queue_rounds * service_time_s


# ── Reclaim overhead estimation ───────────────────────────────────────


def _estimate_reclaim_overhead_s(
    sibling_lanes: List[LaneSchedulerSignals],
    target_model_name: str,
) -> float:
    """Estimate VRAM reclaim cost based on what sibling lanes are doing.

    Examines other lanes on the same provider to determine whether reclaim
    would require evicting idle/sleeping lanes (fast) or draining busy
    lanes (slow).

    Returns:
        Estimated reclaim overhead in seconds.
    """
    if not sibling_lanes:
        # No visibility into sibling state — use conservative idle estimate
        return RECLAIM_IDLE_EVICT_S

    # Look at siblings that are NOT the target model (potential eviction victims)
    evictable_idle = False
    must_drain_busy = True  # assume worst case, disprove below

    for lane in sibling_lanes:
        if lane.model_name == target_model_name:
            continue
        # A lane is cheaply evictable if it's sleeping or idle (no active requests)
        if lane.runtime_state == "sleeping":
            evictable_idle = True
            must_drain_busy = False
        elif lane.runtime_state in ("loaded", "running") and lane.active_requests == 0:
            evictable_idle = True
            must_drain_busy = False

    if evictable_idle:
        return RECLAIM_IDLE_EVICT_S
    if must_drain_busy:
        return RECLAIM_BUSY_DRAIN_S

    # Fallback
    return RECLAIM_IDLE_EVICT_S


# ── Local (logosnode) estimation ───────────────────────────────────────


def estimate_ettft_local(
    view: ModelSchedulerView,
    effective_parallel: int = 1,
    generation_time_s: float = DEFAULT_GENERATION_TIME_S,
    available_vram_mb: float = float("inf"),
    model_vram_mb: float = 0.0,
    kv_budget_mb: float = 0.0,
    scheduler_queue_depth: int = 0,
    observed_e2e_p50_s: float = 0.0,
    all_provider_lanes: Optional[List[LaneSchedulerSignals]] = None,
) -> EttftEstimate:
    """Estimate ETTFT for a local (logosnode) model from its scheduler view.

    The estimate decomposes into three additive phases:
      ETTFT = state_overhead + reclaim_overhead + queue_wait

    State overhead depends on the warmest lane state (warm/sleeping/cold).
    Reclaim overhead is context-aware: it inspects sibling lanes to determine
    whether eviction targets are idle (fast, ~3s) or busy (slow, ~30s).
    Queue wait uses the observed e2e latency p50 as service time when available,
    falling back to a configured constant.

    Decision tree:
    1. No lanes or all stopped/error → UNAVAILABLE
    2. All lanes cold/starting:
       a. model_vram_mb > available_vram_mb → COLD_RECLAIM
       b. otherwise → COLD
    3. Best lane sleeping:
       a. kv_budget_mb > available_vram_mb → SLEEPING_RECLAIM
       b. otherwise → SLEEPING
    4. Best lane loaded/running → WARM
    5. Queue wait added in all non-UNAVAILABLE cases
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
    service_time = _effective_service_time_s(observed_e2e_p50_s, generation_time_s)
    queue_wait_s = _estimate_queue_wait_s(
        scheduler_queue_depth, effective_parallel, service_time,
    )
    queue_suffix = (
        f" + queue {queue_wait_s:.1f}s ({scheduler_queue_depth}q/{effective_parallel}p"
        f", svc={service_time:.1f}s)"
        if queue_wait_s > 0 else ""
    )

    # ── Cold: no loaded/running lanes ──────────────────────────────────
    if best_state in ("cold", "starting"):
        needs_reclaim = model_vram_mb > 0 and model_vram_mb > available_vram_mb
        if needs_reclaim:
            reclaim_s = _estimate_reclaim_overhead_s(
                all_provider_lanes or [], view.model_name,
            )
            overhead = OVERHEAD_COLD_S
            tier = ReadinessTier.COLD_RECLAIM
            reason = (
                f"Cold + reclaim: model needs {model_vram_mb:.0f}MB, "
                f"available {available_vram_mb:.0f}MB, "
                f"reclaim ~{reclaim_s:.0f}s"
            )
        else:
            overhead = OVERHEAD_COLD_S
            reclaim_s = 0.0
            tier = ReadinessTier.COLD
            reason = f"Best lane state is '{best_state}', cold-start ~{OVERHEAD_COLD_S:.0f}s"

        expected = overhead + reclaim_s + queue_wait_s
        reason += queue_suffix

        return EttftEstimate(
            expected_wait_s=expected,
            tier=tier,
            reasoning=reason,
            state_overhead_s=overhead,
            reclaim_overhead_s=reclaim_s,
            queue_wait_s=queue_wait_s,
            needs_reclaim=needs_reclaim,
        )

    # ── Sleeping: best lane is sleeping, needs wake ────────────────────
    if best_state == "sleeping":
        needs_reclaim = kv_budget_mb > 0 and kv_budget_mb > available_vram_mb
        if needs_reclaim:
            reclaim_s = _estimate_reclaim_overhead_s(
                all_provider_lanes or [], view.model_name,
            )
            overhead = OVERHEAD_SLEEPING_S
            tier = ReadinessTier.SLEEPING_RECLAIM
            reason = (
                f"Sleeping + reclaim: KV cache needs {kv_budget_mb:.0f}MB, "
                f"available {available_vram_mb:.0f}MB, "
                f"reclaim ~{reclaim_s:.0f}s"
            )
        else:
            overhead = OVERHEAD_SLEEPING_S
            reclaim_s = 0.0
            tier = ReadinessTier.SLEEPING
            reason = f"Best lane is sleeping, wake ~{OVERHEAD_SLEEPING_S:.1f}s"

        expected = overhead + reclaim_s + queue_wait_s
        reason += queue_suffix

        return EttftEstimate(
            expected_wait_s=expected,
            tier=tier,
            reasoning=reason,
            state_overhead_s=overhead,
            reclaim_overhead_s=reclaim_s,
            queue_wait_s=queue_wait_s,
            needs_reclaim=needs_reclaim,
        )

    # ── Loaded or running → WARM ──────────────────────────────────────
    overhead = OVERHEAD_WARM_S
    expected = overhead + queue_wait_s
    reason = "Loaded and warm"
    reason += queue_suffix

    return EttftEstimate(
        expected_wait_s=expected,
        tier=ReadinessTier.WARM,
        reasoning=reason,
        state_overhead_s=overhead,
        reclaim_overhead_s=0.0,
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
