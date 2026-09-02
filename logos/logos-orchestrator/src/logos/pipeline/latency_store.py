# src/logos/pipeline/latency_store.py
"""
EWMA-based latency store for per-model, per-provider, per-tier load overheads
and per-model TTFT / e2e latency.

Design
------
All values are maintained as exponentially weighted moving averages (EWMA).
On first observation the EWMA is seeded directly with that sample so it
starts meaningful immediately rather than blending with a zero baseline.

Overhead (load / wake times) is keyed by (model_name, provider_id, tier)
because the same model loads at different speeds on different nodes (disk
bandwidth, tensor-parallel shard count) and takes structurally different
paths for each ReadinessTier.

TTFT and e2e latency are keyed by model_name only: once the model is warm
these values are hardware-independent (for homogeneous GPU fleets) and
pooling observations across providers gives faster convergence.

Prior computation
-----------------
When no learned value exists yet the store returns a prior:

  COLD   : (loaded_vram_mb / tensor_parallel_size) / io_bandwidth_mb_s
            Falls back to the static OVERHEAD_COLD_S constant when VRAM or
            bandwidth are unknown.
  COLD_RECLAIM : COLD prior + RECLAIM_IDLE_EVICT_S
  SLEEPING     : static OVERHEAD_SLEEPING_S
  SLEEPING_RECLAIM : OVERHEAD_SLEEPING_S + RECLAIM_IDLE_EVICT_S
  WARM / BUSY  : 0.0 (no prior needed)
  UNAVAILABLE  : inf
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional

from logos.pipeline.ettft_estimator import (
    DEFAULT_GENERATION_TIME_S,
    OVERHEAD_COLD_S,
    OVERHEAD_SLEEPING_S,
    RECLAIM_IDLE_EVICT_S,
    ReadinessTier,
)

# Default EWMA smoothing factor.
# α = 0.2 means a new sample carries 20 % weight; the estimate reaches
# ~87 % of a sustained step change after roughly 8 observations.
DEFAULT_ALPHA: float = 0.2

# Minimum plausible load time (seconds). Observations below this are
# likely measurement noise from a status-poll race and are discarded.
_MIN_PLAUSIBLE_S: float = 0.1

_ZERO_TIERS = frozenset({ReadinessTier.WARM, ReadinessTier.BUSY})


@dataclass
class _EWMAState:
    value: float
    n: int = 1


class LatencyStore:
    """Thread-safe EWMA store for learned infrastructure latency values."""

    def __init__(
        self,
        alpha: float = DEFAULT_ALPHA,
        io_bandwidth_mb_s: float = 750.0,
    ) -> None:
        self._alpha = alpha
        self._io_bandwidth_mb_s = io_bandwidth_mb_s
        self._lock = threading.Lock()
        # (model_name, provider_id, ReadinessTier) → EWMAState
        self._overhead: dict[tuple[str, int, ReadinessTier], _EWMAState] = {}
        # model_name → EWMAState (seconds)
        self._ttft: dict[str, _EWMAState] = {}
        # model_name → EWMAState (seconds)
        self._e2e_latency: dict[str, _EWMAState] = {}

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_overhead(
        self,
        model_name: str,
        provider_id: int,
        tier: ReadinessTier,
        duration_s: float,
    ) -> None:
        """Record an observed load / wake duration for a (model, node, tier)."""
        if tier in _ZERO_TIERS or tier == ReadinessTier.UNAVAILABLE:
            return
        if duration_s < _MIN_PLAUSIBLE_S:
            return
        key = (model_name, int(provider_id), tier)
        with self._lock:
            state = self._overhead.get(key)
            if state is None:
                self._overhead[key] = _EWMAState(value=duration_s)
            else:
                state.value = self._alpha * duration_s + (1.0 - self._alpha) * state.value
                state.n += 1

    def record_ttft(self, model_name: str, ttft_s: float) -> None:
        """Record an observed TTFT sample for a model."""
        if ttft_s < _MIN_PLAUSIBLE_S:
            return
        with self._lock:
            state = self._ttft.get(model_name)
            if state is None:
                self._ttft[model_name] = _EWMAState(value=ttft_s)
            else:
                state.value = self._alpha * ttft_s + (1.0 - self._alpha) * state.value
                state.n += 1

    def record_e2e_latency(self, model_name: str, e2e_s: float) -> None:
        """Record an observed end-to-end request latency for a model."""
        if e2e_s < _MIN_PLAUSIBLE_S:
            return
        with self._lock:
            state = self._e2e_latency.get(model_name)
            if state is None:
                self._e2e_latency[model_name] = _EWMAState(value=e2e_s)
            else:
                state.value = self._alpha * e2e_s + (1.0 - self._alpha) * state.value
                state.n += 1

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def get_overhead_s(
        self,
        model_name: str,
        provider_id: int,
        tier: ReadinessTier,
        *,
        model_vram_mb: float = 0.0,
        tp_size: int = 1,
    ) -> float:
        """Return the best available overhead estimate for a (model, node, tier).

        Priority:
          1. Learned EWMA value (most accurate)
          2. Size-derived prior for COLD tiers
          3. Static fallback constant
        """
        if tier in _ZERO_TIERS:
            return 0.0
        if tier == ReadinessTier.UNAVAILABLE:
            return float("inf")

        key = (model_name, int(provider_id), tier)
        with self._lock:
            state = self._overhead.get(key)
        if state is not None:
            return state.value

        return self._compute_prior(tier, model_vram_mb=model_vram_mb, tp_size=tp_size)

    def get_ttft_s(self, model_name: str) -> Optional[float]:
        """Return the learned TTFT for a model, or None when unknown."""
        with self._lock:
            state = self._ttft.get(model_name)
        return state.value if state is not None else None

    def get_e2e_latency_s(self, model_name: str) -> Optional[float]:
        """Return the learned e2e latency for a model, or None when unknown."""
        with self._lock:
            state = self._e2e_latency.get(model_name)
        return state.value if state is not None else None

    def get_observation_count(
        self,
        model_name: str,
        provider_id: int,
        tier: ReadinessTier,
    ) -> int:
        """Return how many overhead observations have been recorded."""
        key = (model_name, int(provider_id), tier)
        with self._lock:
            state = self._overhead.get(key)
        return state.n if state is not None else 0

    # ------------------------------------------------------------------
    # Prior computation
    # ------------------------------------------------------------------

    def _cold_prior_s(self, model_vram_mb: float, tp_size: int) -> float:
        """Estimate cold load time from model size and configured I/O bandwidth.

        With pre-sharded checkpoints each GPU rank loads its own shard in
        parallel, so the effective load per rank is vram_mb / tp_size.
        Falls back to the static constant when size or bandwidth are unknown.
        """
        if model_vram_mb > 0 and self._io_bandwidth_mb_s > 0:
            return (model_vram_mb / max(tp_size, 1)) / self._io_bandwidth_mb_s
        return OVERHEAD_COLD_S

    def _compute_prior(
        self,
        tier: ReadinessTier,
        *,
        model_vram_mb: float = 0.0,
        tp_size: int = 1,
    ) -> float:
        cold_s = self._cold_prior_s(model_vram_mb, tp_size)
        if tier == ReadinessTier.COLD:
            return cold_s
        if tier == ReadinessTier.COLD_RECLAIM:
            return cold_s + RECLAIM_IDLE_EVICT_S
        if tier == ReadinessTier.SLEEPING:
            return OVERHEAD_SLEEPING_S
        if tier == ReadinessTier.SLEEPING_RECLAIM:
            return OVERHEAD_SLEEPING_S + RECLAIM_IDLE_EVICT_S
        return OVERHEAD_COLD_S
