# src/logos/pipeline/scheduler_interface.py
"""
Abstract scheduler interface for model selection.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict, Any

from logos.dbutils.types import Deployment


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

    def __post_init__(self):
        if self.provider_metrics is None:
            self.provider_metrics = {}


@dataclass
class SchedulingRequest:
    """Input for the scheduler."""
    request_id: str
    payload: Dict[str, Any]
    deployments: list[Deployment]
    classified_models: Optional[List[Tuple[int, float, int, int]]] = None  # (model_id, weight, priority, parallel)
    timeout_s: Optional[float] = None


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
    def update_provider_stats(self, model_id: int, headers: Dict[str, str]) -> None:
        """Update provider-specific statistics (e.g., rate limits) from response headers."""
        raise NotImplementedError
