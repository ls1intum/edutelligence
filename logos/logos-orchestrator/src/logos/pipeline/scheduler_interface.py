# src/logos/pipeline/scheduler_interface.py
"""
Abstract scheduler interface for model selection.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from logos.dbutils.types import Deployment
from logos.timeouts import global_timeout_s

# Default queue-wait bound for a request that did not set ``timeout_s`` — the
# point where a wait-mode timeout is declared. Shared with the internal retry
# policy, which clamps a re-queue to whatever time is left in its deadline.
DEFAULT_QUEUE_TIMEOUT_S = global_timeout_s(1200.0)


class QueueTimeoutError(Exception):
    """
    Raised when a queued request exceeds its wait timeout.
    """

    def __init__(
        self,
        request_id: str,
        model_id: int,
        provider_id: int,
        timeout_s: Optional[float],
    ) -> None:
        self.request_id = request_id
        self.model_id = model_id
        self.provider_id = provider_id
        self.timeout_s = timeout_s
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        if self.timeout_s:
            return f"Queue wait timeout after {self.timeout_s:.0f}s"
        return "Queue wait timeout"


@dataclass
class SchedulingResult:
    """Output from the scheduler."""

    model_id: int
    provider_id: int
    provider_type: str  # 'ollama' | 'azure'
    queue_entry_id: Optional[str]  # For local models with queue tracking
    was_queued: bool
    queue_depth_at_schedule: int
    queue_depth_at_arrival: Optional[int] = None
    utilization_at_arrival: Optional[float] = None
    available_vram_mb: Optional[int] = None
    azure_rate_remaining_requests: Optional[int] = None
    azure_rate_remaining_tokens: Optional[int] = None
    provider_metrics: Dict[str, Any] = None
    priority_when_scheduled: Optional[str] = None
    is_cold_start: Optional[bool] = None
    ettft_estimate_ms: Optional[float] = None
    ettft_tier: Optional[str] = None
    # Warmth of the chosen deployment at decision time:
    # -1 = cold, 0 = warm but idle, 1+x = running with x queued (None = cloud)
    warmth_state: Optional[int] = None

    def __post_init__(self):
        if self.provider_metrics is None:
            self.provider_metrics = {}


@dataclass
class SchedulingRequest:
    """Input for the scheduler."""

    request_id: str
    payload: Dict[str, Any]
    deployments: list[Deployment]
    classified_models: Optional[List[Tuple[int, float, int]]] = None  # (model_id, weight, priority)
    timeout_s: Optional[float] = None
    required_provider_id: Optional[int] = None
    """Trusted internal affinity. When set, scheduling and queue dispatch
    must never fall back to another provider."""
    eligible_provider_ids: Optional[frozenset[int]] = None
    """When set, only these providers may dequeue the request once it is
    queued. The pipeline derives it from a pinned request's filtered
    deployment list (internal retry / stream resume) so the model-wide queue
    honours the same cross-node failover eligibility the scheduling pass
    just established. Normal requests leave it unset and stay model-wide."""
    # Chained prefix-block hashes identifying the request's "stream"
    # (api key + actual prompt prefix), deepest block first. Used for
    # prefix-cache-aware placement; empty/None means "route as before".
    affinity_keys: Optional[List[str]] = None


class SchedulerInterface(ABC):
    """Abstract interface for model scheduling."""

    @abstractmethod
    async def schedule(self, request: SchedulingRequest) -> Optional[SchedulingResult]:
        """
        Select a model from candidates based on weights and availability.
        If no model is immediately available, may queue the request and await availability.

        Returns None if no model is available and queuing failed/timed out.
        """
        raise NotImplementedError

    @abstractmethod
    def release(self, model_id: int, provider_id: int, provider_type: str, request_id: str) -> None:
        """Called when a request completes to free capacity."""
        raise NotImplementedError

    @abstractmethod
    def get_total_queue_depth(self) -> int:
        """Get total number of queued requests across all models."""
        raise NotImplementedError

    @abstractmethod
    def update_provider_stats(self, model_id: int, provider_id: int, headers: Dict[str, str]) -> None:
        """Update provider-specific statistics (e.g., rate limits) from response headers."""
        raise NotImplementedError
