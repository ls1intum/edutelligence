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
    """Status data for a single model."""

    model_id: int
    is_loaded: bool
    cold_start_predicted: bool
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
            'cold_start_predicted': self.cold_start_predicted,
            'vram_mb': self.vram_mb,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'queue_depth': self.queue_depth,
            'active_requests': self.active_requests,
            'provider_type': self.provider_type
        }


@dataclass
class OllamaCapacity:
    """Capacity information for Ollama providers."""

    available_vram_mb: int
    total_vram_mb: int
    loaded_models_count: int
    loaded_models: List[str]
    can_load_new_model: bool

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'available_vram_mb': self.available_vram_mb,
            'total_vram_mb': self.total_vram_mb,
            'loaded_models_count': self.loaded_models_count,
            'loaded_models': self.loaded_models,
            'can_load_new_model': self.can_load_new_model
        }


@dataclass
class CloudCapacity:
    """Capacity information for cloud providers (Azure)."""

    rate_limit_remaining_requests: Optional[int]
    rate_limit_remaining_tokens: Optional[int]
    rate_limit_resets_at: Optional[datetime]
    has_capacity: bool

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'rate_limit_remaining_requests': self.rate_limit_remaining_requests,
            'rate_limit_remaining_tokens': self.rate_limit_remaining_tokens,
            'rate_limit_resets_at': self.rate_limit_resets_at.isoformat() if self.rate_limit_resets_at else None,
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
