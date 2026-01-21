"""
Ollama-specific Scheduling Data Facade.

Provides a type-safe API for accessing scheduling data from Ollama providers.
Returns dataclasses instead of dictionaries for better type safety.
"""

import logging
import threading
import time
from typing import Dict, List, Optional

from .models import ModelStatus, OllamaCapacity, RequestMetrics
from .providers import OllamaDataProvider


logger = logging.getLogger(__name__)


class OllamaSchedulingDataFacade:
    """
    Facade for accessing Ollama scheduling data with strong typing.
    """

    def __init__(self, queue_manager, db_manager=None):
        self.queue_manager = queue_manager
        self._db = db_manager

        # Provider management (Ollama providers only)
        self._providers: Dict[int, OllamaDataProvider] = {}  # provider__id → OllamaDataProvider
        self._model_to_provider: Dict[int, str] = {}  # model_id → provider_name

        # Request tracking
        self._request_tracking: Dict[str, Dict] = {}  # request_id → tracking_data

        # Thread safety
        self._lock = threading.RLock()

        logger.info("OllamaSchedulingDataFacade initialized")

    def register_model(
        self,
        model_id: int,
        provider_name: str,
        ollama_admin_url: Optional[str] = None,
        model_name: Optional[str] = None,
        total_vram_mb: Optional[int] = None,
        refresh_interval: float = 5.0,
        provider_id: Optional[int] = None
    ) -> None:
        """
        Register a model with the Ollama facade.
        """

        if model_name is None and total_vram_mb is None:
            raise ValueError("model_name and total_vram_mb are required")

        with self._lock:
            # Create provider if it doesn't exist
            if provider_name not in self._providers:
                provider = OllamaDataProvider(
                    name=provider_name,
                    base_url=ollama_admin_url,
                    total_vram_mb=int(total_vram_mb) if total_vram_mb is not None else 0,
                    queue_manager=self.queue_manager,
                    refresh_interval=refresh_interval,
                    provider_id=provider_id,
                    db_manager=self._db
                )
                self._providers[provider_name] = provider
                
                if ollama_admin_url:
                    logger.info(f"Created Ollama provider '{provider_name}' using {ollama_admin_url}")
                else:
                    logger.info(f"Created Ollama provider '{provider_name}' without explicit URL (scheduling metrics limited)")

            # Register model with provider
            provider = self._providers[provider_name]
            provider.register_model(model_id, model_name)
            self._model_to_provider[model_id] = provider_name

            logger.info(
                f"Registered model {model_id} as '{model_name}' "
                f"with Ollama provider '{provider_name}'"
            )

    def get_model_status(self, model_id: int) -> ModelStatus:
        """
        Get current status for a specific model.
        """
        provider = self._get_provider_for_model(model_id)
        return provider.get_model_status(model_id)

    def get_capacity_info(self, provider_id: int) -> OllamaCapacity:
        """
        Get VRAM capacity information for an Ollama provider.
        """
        if provider_id not in self._providers.keys():
            raise KeyError(f"Provider '{provider_id}' not found")

        provider = self._providers[provider_id]
        return provider.get_capacity_info()

    def on_request_start(self, request_id: str, model_id: int, priority: str = 'normal') -> None:
        """
        Track request arrival (for metrics only).
        """
        with self._lock:
            # Query current queue depth from provider
            provider = self._get_provider_for_model(model_id)
            status = provider.get_model_status(model_id)
            queue_depth_snapshot = status.queue_depth

            # Track request metadata
            self._request_tracking[request_id] = {
                'model_id': model_id,
                'arrival_time': time.time(),
                'priority': priority,
                'queue_depth_at_arrival': queue_depth_snapshot
            }

        logger.debug(
            f"Request {request_id} started for model {model_id} "
            f"(priority={priority}, queue_depth={queue_depth_snapshot})"
        )

    def on_request_begin_processing(self, request_id: str, increment_active: bool = True) -> None:
        """
        Track when a request begins processing (moves from queue to active).
        """
        with self._lock:
            if request_id not in self._request_tracking:
                raise KeyError(f"Request {request_id} not found in tracking")

            tracking_data = self._request_tracking[request_id]
            model_id = tracking_data['model_id']

            # Increment active request count for this model (if requested)
            if increment_active:
                provider = self._get_provider_for_model(model_id)
                provider.increment_active(model_id)

            # Record processing start time
            tracking_data['processing_start_time'] = time.time()

        logger.debug(f"Request {request_id} began processing on model {model_id}")

    def on_request_complete(
        self,
        request_id: str,
        was_cold_start: bool,
        duration_ms: float,
        reuse_slot: bool = False
    ) -> RequestMetrics:
        """
        Track request completion and return metrics.
        """
        with self._lock:
            if request_id not in self._request_tracking:
                raise KeyError(f"Request {request_id} not found in tracking")

            tracking_data = self._request_tracking.pop(request_id)
            model_id = tracking_data['model_id']

            # Calculate metrics
            queue_wait_ms = (time.time() - tracking_data['arrival_time']) * 1000 - duration_ms

            # Decrement active request count (or reuse slot)
            provider = self._get_provider_for_model(model_id)
            provider.decrement_active(model_id, reuse_slot=reuse_slot)

            # Create metrics dataclass
            metrics = RequestMetrics(
                queue_wait_ms=max(0, queue_wait_ms),  # Clamp to 0 if negative
                was_cold_start=was_cold_start,
                duration_ms=duration_ms,
                queue_depth_at_arrival=tracking_data['queue_depth_at_arrival'],
                priority=tracking_data['priority']
            )

            logger.debug(
                f"Request {request_id} completed: "
                f"cold_start={was_cold_start}, duration={duration_ms:.1f}ms, "
                f"queue_wait={metrics.queue_wait_ms:.1f}ms"
            )

            return metrics

    def try_reserve_capacity(self, model_id: int, provider_id: int) -> bool:
        """
        Attempt to reserve execution capacity for a model.
        Atomic check-and-increment.
        
        Returns:
            True if reserved, False if full (queue needed).
        """
        try:
            ollama_data_provider = self._providers[provider_id]

            return ollama_data_provider.try_reserve_capacity(model_id)
        except ValueError:
            return False
