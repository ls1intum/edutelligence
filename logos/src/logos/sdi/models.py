"""
Data models for Scheduling Data Interface.

Type-safe data classes for SDI responses. These provide an alternative
to raw dictionaries with better IDE support and type checking.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List

# Import queue state from queue subsystem
from logos.queue.models import QueueStatePerPriority


@dataclass
class ModelStatus:
    """
    Status data for a single model.

    Provides raw data only - schedulers should derive predictions from this data.
    For example, to predict cold starts:
    - Ollama: Check if is_loaded=False or expires_at < now
    - Cloud: Always False (no cold starts in cloud providers)

    Queue State:
    - queue_state: Breakdown of queue depth by priority level
      * Ollama: Real 3-level breakdown (we control the queue)
      * Cloud: None (they control the queue, we have no visibility)
    - queue_depth: Total queue depth (computed property)
      * Returns 0 if queue_state is None (cloud providers)
    """

    model_id: int
    provider_id: int
    is_loaded: bool
    vram_mb: int
    expires_at: Optional[datetime]
    queue_state: Optional[QueueStatePerPriority]  # None for cloud providers
    active_requests: int
    provider_type: str  # 'ollama' | 'azure'

    @property
    def queue_depth(self) -> int:
        """
        Total queue depth across all priority levels.

        Returns 0 for cloud providers (no queue visibility).
        For Ollama providers, returns sum of all priority queues.

        This is a computed property for backward compatibility.
        """
        if self.queue_state is None:
            return 0  # Cloud providers: no queue control
        return self.queue_state.total

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'model_id': self.model_id,
            'is_loaded': self.is_loaded,
            'vram_mb': self.vram_mb,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'queue_depth': self.queue_depth,  # Computed property
            'queue_state': {
                'low': self.queue_state.low,
                'normal': self.queue_state.normal,
                'high': self.queue_state.high,
                'total': self.queue_state.total,
            } if self.queue_state else None,
            'active_requests': self.active_requests,
            'provider_type': self.provider_type
        }


@dataclass
class OllamaCapacity:
    """
    Capacity information for Ollama providers.

    Schedulers can determine if new models can be loaded based on available_vram_mb.
    """

    available_vram_mb: int
    total_vram_mb: int
    loaded_models: List[str]

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'available_vram_mb': self.available_vram_mb,
            'total_vram_mb': self.total_vram_mb,
            'loaded_models': self.loaded_models
        }


@dataclass
class AzureCapacity:
    """Capacity information for Azure providers with per-deployment rate limits."""

    deployment_name: str
    rate_limit_remaining_requests: Optional[int]
    rate_limit_remaining_tokens: Optional[int]
    rate_limit_total_requests: Optional[int]
    rate_limit_total_tokens: Optional[int]
    rate_limit_resets_at: Optional[datetime]
    last_header_age_seconds: Optional[float]
    has_capacity: bool

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'deployment_name': self.deployment_name,
            'rate_limit_remaining_requests': self.rate_limit_remaining_requests,
            'rate_limit_remaining_tokens': self.rate_limit_remaining_tokens,
            'rate_limit_total_requests': self.rate_limit_total_requests,
            'rate_limit_total_tokens': self.rate_limit_total_tokens,
            'rate_limit_resets_at': self.rate_limit_resets_at.isoformat() if self.rate_limit_resets_at else None,
            'last_header_age_seconds': self.last_header_age_seconds,
            'has_capacity': self.has_capacity
        }


@dataclass
class RequestMetrics:
    """Metrics collected for a completed request."""

    queue_wait_ms: float
    was_cold_start: bool
    duration_ms: float
    queue_depth_at_arrival: int
    priority: str

    def to_dict(self) -> dict:
        """Convert to dictionary for database logging."""
        return {
            'queue_wait_ms': self.queue_wait_ms,
            'was_cold_start': self.was_cold_start,
            'duration_ms': self.duration_ms,
            'queue_depth_at_arrival': self.queue_depth_at_arrival,
            'priority': self.priority
        }
