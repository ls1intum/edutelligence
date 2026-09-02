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

Persistence
-----------
When a ``db_factory`` is provided (typically ``DBManager``), the store loads
its full state from the ``latency_observations`` table on initialisation and
writes back every EWMA update immediately (write-on-every-update, consistent
with the rest of the codebase).  Without a factory the store is in-memory only
and resets on restart.

TTFT and e2e observations use ``provider_id = -1`` and ``tier = "ttft"`` /
``tier = "e2e"`` in the DB so they share the same table and unique constraint
as overhead rows.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Optional

from logos.pipeline.ettft_estimator import (
    OVERHEAD_COLD_S,
    OVERHEAD_SLEEPING_S,
    RECLAIM_IDLE_EVICT_S,
    ReadinessTier,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Default EWMA smoothing factor.
# α = 0.2 means a new sample carries 20 % weight; the estimate reaches
# ~87 % of a sustained step change after roughly 8 observations.
DEFAULT_ALPHA: float = 0.2

# Minimum plausible load time (seconds). Observations below this are
# likely measurement noise from a status-poll race and are discarded.
_MIN_PLAUSIBLE_S: float = 0.1

_ZERO_TIERS = frozenset({ReadinessTier.WARM, ReadinessTier.BUSY})

# Sentinel provider_id used in the DB for model-only metrics (TTFT / e2e).
_MODEL_ONLY_PROVIDER_ID = -1

_TIER_TTFT = "ttft"
_TIER_E2E = "e2e"


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
        db_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._alpha = alpha
        self._io_bandwidth_mb_s = io_bandwidth_mb_s
        self._db_factory = db_factory
        self._lock = threading.Lock()
        # (model_name, provider_id, ReadinessTier) → EWMAState
        self._overhead: dict[tuple[str, int, ReadinessTier], _EWMAState] = {}
        # model_name → EWMAState (seconds)
        self._ttft: dict[str, _EWMAState] = {}
        # model_name → EWMAState (seconds)
        self._e2e_latency: dict[str, _EWMAState] = {}

        if self._db_factory is not None:
            self._load_from_db()

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
            state = self._overhead[key]
        self._persist_overhead(model_name, int(provider_id), tier, state)

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
            state = self._ttft[model_name]
        self._persist_model_metric(model_name, _TIER_TTFT, state)

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
            state = self._e2e_latency[model_name]
        self._persist_model_metric(model_name, _TIER_E2E, state)

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
    # Persistence helpers
    # ------------------------------------------------------------------

    def _load_from_db(self) -> None:
        """Populate in-memory state from the DB on startup."""
        if self._db_factory is None:
            return
        try:
            with self._db_factory() as db:
                rows = db.get_all_latency_observations()
        except Exception:
            logger.exception("LatencyStore: failed to load observations from DB")
            return

        loaded = 0
        with self._lock:
            for model_name, provider_id, tier_str, ewma_value, n in rows:
                state = _EWMAState(value=ewma_value, n=n)
                if tier_str == _TIER_TTFT:
                    self._ttft[model_name] = state
                elif tier_str == _TIER_E2E:
                    self._e2e_latency[model_name] = state
                else:
                    try:
                        tier = ReadinessTier(tier_str)
                    except ValueError:
                        logger.warning(
                            "LatencyStore: unknown tier %r in DB, skipping", tier_str
                        )
                        continue
                    self._overhead[(model_name, provider_id, tier)] = state
                loaded += 1
        logger.info("LatencyStore: loaded %d observations from DB", loaded)

    def _persist_overhead(
        self,
        model_name: str,
        provider_id: int,
        tier: ReadinessTier,
        state: _EWMAState,
    ) -> None:
        if self._db_factory is None:
            return
        try:
            with self._db_factory() as db:
                db.upsert_latency_observation(
                    model_name, provider_id, tier.value, state.value, state.n
                )
        except Exception:
            logger.exception(
                "LatencyStore: failed to persist overhead for %s/%s/%s",
                model_name,
                provider_id,
                tier,
            )

    def _persist_model_metric(
        self, model_name: str, tier_str: str, state: _EWMAState
    ) -> None:
        if self._db_factory is None:
            return
        try:
            with self._db_factory() as db:
                db.upsert_latency_observation(
                    model_name, _MODEL_ONLY_PROVIDER_ID, tier_str, state.value, state.n
                )
        except Exception:
            logger.exception(
                "LatencyStore: failed to persist %s for %s", tier_str, model_name
            )

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
