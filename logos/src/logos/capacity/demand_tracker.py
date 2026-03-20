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
        """Multiply all scores by DECAY_FACTOR. Called once per planner cycle."""
        with self._lock:
            to_remove = []
            for model in self._demand:
                self._demand[model] *= self.DECAY_FACTOR
                if self._demand[model] < 0.01:
                    to_remove.append(model)
            for model in to_remove:
                del self._demand[model]

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
