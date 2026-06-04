# src/logos/capacity/demand_tracker.py
"""Per-model request demand with exponential decay.

Tracks which models are receiving traffic so the capacity planner
can proactively wake or load lanes.
"""

import collections
import math
import threading
import time
from typing import List, Tuple


class DemandTracker:
    """Exponential-decay demand histogram per model name."""

    # Half-life ≈ log(0.5)/log(DECAY_FACTOR) cycles × cycle_seconds.
    # Was 0.95 (half-life ~135 s at 10 s cycle) — too gentle: a
    # model that just served a burst kept its score warm for minutes,
    # blocking other models from competing on the wake/load contention
    # check (eff(target) > eff(victim)*ratio) and forcing 60-90 s wait
    # for the natural crossover. 0.7 gives a half-life of ~19 s — an
    # idle incumbent's grip on VRAM fades within ~30 s so legitimate
    # rotation requests don't starve. Anti-thrash for genuinely
    # co-active models is preserved by LANE_MIN_TENURE_SECONDS and
    # the queue-depth contribution to effective demand (which doesn't
    # decay), so a model still actively serving requests keeps a
    # high eff even with aggressive base decay.
    DECAY_FACTOR = 0.7
    STALE_THRESHOLD_SECONDS = 3600  # Clean up metadata after 1 hour of inactivity

    # Burst detection parameters
    BURST_WINDOW_SECONDS = 10.0
    BURST_THRESHOLD = 5
    BURST_DEMAND_MULTIPLIER = 1.5  # super-linear scaling during bursts

    # Loadavg time constants (seconds), modeled on Linux 1/5/15-minute loadavg.
    # Each EWMA reports requests-per-minute: a constant rate r req/sec converges
    # to 60·r in steady state because each request bumps EWMA[tau] by 60/tau.
    LOAD_TAUS_SECONDS: tuple[tuple[str, float], ...] = (
        ("1m", 60.0),
        ("5m", 300.0),
        ("15m", 900.0),
    )

    def __init__(self) -> None:
        self._demand: dict[str, float] = {}
        self._raw_count: dict[str, int] = {}
        self._last_request: dict[str, float] = {}
        self._request_timestamps: dict[str, collections.deque] = {}
        self._load_avg: dict[str, dict[str, float]] = {}
        self._load_avg_last_update: dict[str, float] = {}
        self._lock = threading.Lock()

    def _decay_load_locked(self, model_name: str, now: float) -> dict[str, float]:
        """Decay this model's load EWMAs to `now`. Caller must hold ``self._lock``."""
        loads = self._load_avg.setdefault(
            model_name, {window: 0.0 for window, _ in self.LOAD_TAUS_SECONDS}
        )
        last = self._load_avg_last_update.get(model_name)
        if last is not None:
            dt = max(0.0, now - last)
            if dt > 0.0:
                for window, tau in self.LOAD_TAUS_SECONDS:
                    loads[window] *= math.exp(-dt / tau)
        self._load_avg_last_update[model_name] = now
        return loads

    def _record_load_locked(
        self, model_name: str, increment: float, now: float
    ) -> None:
        """Decay then add ``increment`` requests to the EWMAs. Caller must hold the lock."""
        loads = self._decay_load_locked(model_name, now)
        for window, tau in self.LOAD_TAUS_SECONDS:
            loads[window] += increment * (60.0 / tau)

    # Latent demand: half-weight signal for models that classification wanted
    # but the scheduler couldn't serve due to availability penalties.
    LATENT_DEMAND_WEIGHT = 0.5

    def record_request(self, model_name: str) -> None:
        """Increment demand for model. Called from pipeline after scheduling.

        During bursts (>BURST_THRESHOLD requests in BURST_WINDOW_SECONDS),
        demand increments are scaled by BURST_DEMAND_MULTIPLIER to prevent
        the planner from sleeping a model that's about to get hammered.
        """
        now = time.time()
        with self._lock:
            # Track timestamps for burst detection
            if model_name not in self._request_timestamps:
                self._request_timestamps[model_name] = collections.deque()
            ts_deque = self._request_timestamps[model_name]
            ts_deque.append(now)
            # Trim old entries outside the burst window
            cutoff = now - self.BURST_WINDOW_SECONDS
            while ts_deque and ts_deque[0] < cutoff:
                ts_deque.popleft()

            # Scale demand increment during bursts
            increment = (
                self.BURST_DEMAND_MULTIPLIER
                if len(ts_deque) >= self.BURST_THRESHOLD
                else 1.0
            )
            self._demand[model_name] = self._demand.get(model_name, 0.0) + increment
            self._raw_count[model_name] = self._raw_count.get(model_name, 0) + 1
            self._last_request[model_name] = now
            # Loadavg uses raw requests (not the burst multiplier) so that the
            # rendered req/min figure stays calibrated against actual traffic.
            self._record_load_locked(model_name, 1.0, now)

    def record_latent_demand(self, model_name: str) -> None:
        """Record that classification preferred this model but the scheduler picked another.

        Weaker signal than a real request (LATENT_DEMAND_WEIGHT = 0.5) — enough to
        accumulate over time so the capacity planner can drain/wake the model before
        it fully starves, without triggering thrashing on every single request.
        """
        with self._lock:
            self._demand[model_name] = (
                self._demand.get(model_name, 0.0) + self.LATENT_DEMAND_WEIGHT
            )
            self._raw_count[model_name] = self._raw_count.get(model_name, 0) + 1
            self._last_request[model_name] = time.time()

    def decay_all(self) -> None:
        """Multiply all scores by DECAY_FACTOR. Called once per planner cycle.

        Also cleans up stale metadata (raw_count, last_request) for models
        that have decayed to zero and haven't been requested in over an hour.
        """
        now = time.time()
        with self._lock:
            to_remove = []
            for model in self._demand:
                self._demand[model] *= self.DECAY_FACTOR
                if self._demand[model] < 0.01:
                    to_remove.append(model)
            for model in to_remove:
                del self._demand[model]

            # Clean up stale metadata for models no longer in demand
            stale_models = [
                model
                for model, last in self._last_request.items()
                if model not in self._demand
                and (now - last) > self.STALE_THRESHOLD_SECONDS
            ]
            for model in stale_models:
                self._raw_count.pop(model, None)
                self._last_request.pop(model, None)
                self._request_timestamps.pop(model, None)
                self._load_avg.pop(model, None)
                self._load_avg_last_update.pop(model, None)

    def get_ranked_models(self) -> List[Tuple[str, float]]:
        """Return (model_name, score) sorted by score descending."""
        with self._lock:
            items = list(self._demand.items())
        items.sort(key=lambda x: x[1], reverse=True)
        return items

    def get_score(self, model_name: str) -> float:
        """Return current demand score for a model (0.0 if untracked)."""
        with self._lock:
            return self._demand.get(model_name, 0.0)

    def get_loadavg(self, model_name: str) -> Tuple[float, float, float]:
        """Return (1m, 5m, 15m) request-per-minute EWMAs for a model.

        Loadavg is decayed lazily on read so values reflect time elapsed since
        the last request, not just request counts.
        """
        now = time.time()
        with self._lock:
            if model_name not in self._load_avg_last_update:
                return (0.0, 0.0, 0.0)
            loads = self._decay_load_locked(model_name, now)
            return (loads["1m"], loads["5m"], loads["15m"])

    def get_raw_count(self, model_name: str) -> int:
        """Return total request count for a model (not decayed)."""
        with self._lock:
            return self._raw_count.get(model_name, 0)

    def is_burst(
        self,
        model_name: str,
        window_seconds: float | None = None,
        threshold: int | None = None,
    ) -> bool:
        """Check if a model is in a request burst.

        Args:
            model_name: Model to check.
            window_seconds: Override for BURST_WINDOW_SECONDS.
            threshold: Override for BURST_THRESHOLD.

        Returns:
            True if request count in the window meets or exceeds the threshold.
        """
        window = (
            window_seconds if window_seconds is not None else self.BURST_WINDOW_SECONDS
        )
        thresh = threshold if threshold is not None else self.BURST_THRESHOLD
        now = time.time()
        with self._lock:
            ts_deque = self._request_timestamps.get(model_name)
            if ts_deque is None:
                return False
            cutoff = now - window
            count = sum(1 for t in ts_deque if t >= cutoff)
            return count >= thresh

    def get_stats(self) -> dict:
        """Return demand state for debugging."""
        now = time.time()
        with self._lock:
            bursts = {}
            for model_name, ts_deque in self._request_timestamps.items():
                cutoff = now - self.BURST_WINDOW_SECONDS
                count = sum(1 for t in ts_deque if t >= cutoff)
                if count > 0:
                    bursts[model_name] = count
            return {
                "scores": dict(self._demand),
                "raw_counts": dict(self._raw_count),
                "last_request": dict(self._last_request),
                "burst_counts": bursts,
            }
