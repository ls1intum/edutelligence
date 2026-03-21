# src/logos/capacity/demand_tracker.py
"""Per-model request demand with exponential decay.

Tracks which models are receiving traffic so the capacity planner
can proactively wake or load lanes.
"""

import threading
import time
from typing import List, Tuple


class DemandTracker:
    """Exponential-decay demand histogram per model name."""

    DECAY_FACTOR = 0.95
    STALE_THRESHOLD_SECONDS = 3600  # Clean up metadata after 1 hour of inactivity

    def __init__(self) -> None:
        self._demand: dict[str, float] = {}
        self._raw_count: dict[str, int] = {}
        self._last_request: dict[str, float] = {}
        self._lock = threading.Lock()

    def record_request(self, model_name: str) -> None:
        """Increment demand for model. Called from pipeline after scheduling."""
        with self._lock:
            self._demand[model_name] = self._demand.get(model_name, 0.0) + 1.0
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
                model for model, last in self._last_request.items()
                if model not in self._demand and (now - last) > self.STALE_THRESHOLD_SECONDS
            ]
            for model in stale_models:
                self._raw_count.pop(model, None)
                self._last_request.pop(model, None)

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

    def get_raw_count(self, model_name: str) -> int:
        """Return total request count for a model (not decayed)."""
        with self._lock:
            return self._raw_count.get(model_name, 0)

    def get_stats(self) -> dict:
        """Return demand state for debugging."""
        with self._lock:
            return {
                "scores": dict(self._demand),
                "raw_counts": dict(self._raw_count),
                "last_request": dict(self._last_request),
            }
