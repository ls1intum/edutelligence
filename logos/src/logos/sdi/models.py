"""
Data models for Scheduling Data Interface.

Type-safe data classes for SDI responses. These provide an alternative
to raw dictionaries with better IDE support and type checking.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List


@dataclass
class ModelStatus:
    """
    Status data for a single model.

    Provides raw data only - schedulers should derive predictions from this data.
    For example, to predict cold starts:
    - Ollama: Check if is_loaded=False or expires_at < now
    - Cloud: Always False (no cold starts in cloud providers)
    """

    model_id: int
    is_loaded: bool
    vram_mb: int
    expires_at: Optional[datetime]
    queue_depth: int
    active_requests: int
    provider_type: str  # 'ollama' | 'azure'

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'model_id': self.model_id,
            'is_loaded': self.is_loaded,
            'vram_mb': self.vram_mb,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'queue_depth': self.queue_depth,
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
