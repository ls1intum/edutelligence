"""
Scheduling Data Provider Interface.

Defines the contract that all scheduling data providers must implement.
Each provider fetches real-time scheduling data from different sources
(e.g., Ollama /api/ps, cloud provider rate limit headers).
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional


class SchedulingDataProvider(ABC):
    """
    Abstract base class defining the interface for scheduling data providers.

    Providers fetch real-time data from various sources to inform scheduling decisions:
    - OllamaDataProvider: Queries /api/ps for VRAM usage, loaded models, expiration
    - AzureDataProvider: Tracks rate limits from API response headers

    All providers must implement thread-safe data access.
    """

    def __init__(self, name: str):
        """
        Initialize provider with a unique name.

        Args:
            name: Provider identifier (e.g., 'openwebui', 'azure')
        """
        self.name = name

    @abstractmethod
    def register_model(self, model_id: int, model_name: str) -> None:
        """
        Register a model with this provider.

        Args:
            model_id: Internal database ID for the model
            model_name: Model name as known by the provider (e.g., 'llama3.1:8b')
        """
        pass

    @abstractmethod
    def get_model_status(self, model_id: int) -> Dict:
        """
        Get current scheduling status for a specific model.

        Args:
            model_id: Model to query

        Returns:
            Dictionary with scheduling data:
            {
                'model_id': int,
                'is_loaded': bool,              # In VRAM (Ollama) or always True (cloud)
                'cold_start_predicted': bool,   # Will request trigger cold start?
                'vram_mb': int,                 # VRAM usage in MB (0 for cloud)
                'expires_at': datetime | None,  # When model unloads (Ollama) or None (cloud)
                'queue_depth': int,             # Current requests queued for this model
                'active_requests': int,         # Requests currently executing
                'provider_type': str            # 'ollama' | 'azure'
            }
        """
        pass

    @abstractmethod
    def get_capacity_info(self) -> Dict:
        """
        Get provider-level capacity information.

        Returns for Ollama providers:
            {
                'available_vram_mb': int,       # Free VRAM for new models
                'total_vram_mb': int,           # Total VRAM capacity
                'loaded_models_count': int,     # Number of models currently loaded
                'loaded_models': List[str],     # Names of loaded models
                'can_load_new_model': bool      # Whether sufficient VRAM available
            }

        Returns for cloud providers:
            {
                'rate_limit_remaining_requests': int | None,
                'rate_limit_remaining_tokens': int | None,
                'rate_limit_resets_at': datetime | None,
                'has_capacity': bool             # True if not rate-limited
            }
        """
        pass

    @abstractmethod
    def refresh_data(self) -> None:
        """
        Update cached data from the provider's data source.

        For Ollama: Query /api/ps endpoint
        For cloud: No-op (updated via response headers)

        Should be called periodically or before queries if data is stale.
        Must be thread-safe.
        """
        pass

    @abstractmethod
    def increment_queue(self, model_id: int) -> None:
        """
        Increment queue depth counter when request arrives.

        Args:
            model_id: Model receiving the request
        """
        pass

    @abstractmethod
    def decrement_queue(self, model_id: int) -> None:
        """
        Decrement queue depth counter when request completes.

        Args:
            model_id: Model that finished the request
        """
        pass

    @abstractmethod
    def get_queue_depth(self, model_id: int) -> int:
        """
        Get current queue depth for a model.

        Args:
            model_id: Model to query

        Returns:
            Number of requests currently queued/executing for this model
        """
        pass
