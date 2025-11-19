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

    Simplifies scheduler interaction by:
    - Managing Ollama provider lifecycle
    - Tracking request metrics (queue wait times, cold starts)
    - Providing type-safe responses via dataclasses

    Usage:
        queue_manager = PriorityQueueManager()
        facade = OllamaSchedulingDataFacade(queue_manager, db_manager)

        # Register models
        facade.register_model(1, 'openwebui', 'http://gpu:11434', 'llama3.1:8b',
                             total_vram_mb=49152)

        # Query for scheduling decisions (returns ModelStatus dataclass)
        status = facade.get_model_status(1)
        if status.is_loaded and status.queue_depth < 3:
            # Good candidate: warm and not overloaded
            ...

        # Get capacity info (returns OllamaCapacity dataclass)
        capacity = facade.get_capacity_info('openwebui')
        if capacity.available_vram_mb > 8000:
            # Can load new model
            ...

        # Track request lifecycle (for metrics only)
        facade.on_request_start('req-123', model_id=1, priority='high')
        # ... scheduler dequeues and processes request ...
        facade.on_request_begin_processing('req-123')
        # ... request completes ...
        metrics = facade.on_request_complete('req-123', was_cold_start=False, duration_ms=250)
    """

    def __init__(self, queue_manager, db_manager=None):
        """
        Initialize Ollama scheduling data facade.

        Args:
            queue_manager: PriorityQueueManager instance (REQUIRED for Ollama)
            db_manager: Optional database manager for configuration lookups
        """
        self.queue_manager = queue_manager
        self._db = db_manager

        # Provider management (Ollama providers only)
        self._providers: Dict[str, OllamaDataProvider] = {}  # provider_name → provider
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
        ollama_admin_url: str,
        model_name: str,
        total_vram_mb: int,
        refresh_interval: float = 5.0,
        provider_id: Optional[int] = None
    ) -> None:
        """
        Register a model with the Ollama facade.

        Creates Ollama provider if it doesn't exist, then registers the model.

        Args:
            model_id: Internal database ID for the model
            provider_name: Provider identifier (e.g., 'openwebui')
            ollama_admin_url: Ollama /api/ps endpoint
            model_name: Model name as known by Ollama (e.g., 'llama3.1:8b')
            total_vram_mb: Total VRAM capacity in MB
            refresh_interval: Polling interval in seconds (default: 5.0)
            provider_id: Database provider ID (for config lookups)
        """
        with self._lock:
            # Create provider if it doesn't exist
            if provider_name not in self._providers:
                provider = OllamaDataProvider(
                    name=provider_name,
                    base_url=ollama_admin_url,
                    total_vram_mb=total_vram_mb,
                    queue_manager=self.queue_manager,
                    refresh_interval=refresh_interval,
                    provider_id=provider_id,
                    db_manager=self._db
                )
                self._providers[provider_name] = provider
                logger.info(f"Created Ollama provider '{provider_name}' at {ollama_admin_url}")

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

        Args:
            model_id: Model to query

        Returns:
            ModelStatus dataclass with scheduling data

        Raises:
            ValueError: If model not registered
        """
        provider = self._get_provider_for_model(model_id)
        return provider.get_model_status(model_id)

    def get_capacity_info(self, provider_name: str) -> OllamaCapacity:
        """
        Get VRAM capacity information for an Ollama provider.

        Args:
            provider_name: Provider to query

        Returns:
            OllamaCapacity dataclass with VRAM info

        Raises:
            KeyError: If provider doesn't exist
        """
        if provider_name not in self._providers:
            raise KeyError(f"Provider '{provider_name}' not found")

        provider = self._providers[provider_name]
        # Provider already returns OllamaCapacity dataclass
        return provider.get_capacity_info()

    def get_scheduling_data(self, model_ids: List[int]) -> List[ModelStatus]:
        """
        Batch query for multiple models (optimized).

        Args:
            model_ids: Models to query

        Returns:
            List of ModelStatus dataclasses, one per model
        """
        return [self.get_model_status(mid) for mid in model_ids]

    def on_request_start(self, request_id: str, model_id: int, priority: str = 'normal') -> None:
        """
        Track request arrival (for metrics only).

        Note: Queue operations are handled by the scheduler, not the facade.
        This method only tracks arrival time and snapshots queue depth for metrics.

        Args:
            request_id: Unique request identifier
            model_id: Model handling the request
            priority: Request priority level
        """
        with self._lock:
            # Query current queue depth from provider (provider queries queue_manager)
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

    def on_request_begin_processing(self, request_id: str) -> None:
        """
        Track when a request begins processing (moves from queue to active).

        Optional method for 3-stage lifecycle tracking:
        1. on_request_start() - Request arrival (metrics only)
        2. on_request_begin_processing() - Request starts processing (increment active count)
        3. on_request_complete() - Request finishes (decrement active count)

        Args:
            request_id: Request identifier (same as on_request_start)

        Raises:
            KeyError: If request_id not found
        """
        with self._lock:
            if request_id not in self._request_tracking:
                raise KeyError(f"Request {request_id} not found in tracking")

            tracking_data = self._request_tracking[request_id]
            model_id = tracking_data['model_id']

            # Increment active request count for this model
            provider = self._get_provider_for_model(model_id)
            provider.increment_active(model_id)

            # Record processing start time
            tracking_data['processing_start_time'] = time.time()

        logger.debug(f"Request {request_id} began processing on model {model_id}")

    def on_request_complete(
        self,
        request_id: str,
        was_cold_start: bool,
        duration_ms: float
    ) -> RequestMetrics:
        """
        Track request completion and return metrics.

        Decrements the active request count for the model.

        Args:
            request_id: Request that finished
            was_cold_start: Whether request triggered cold start
            duration_ms: End-to-end request duration

        Returns:
            RequestMetrics dataclass with collected metrics

        Raises:
            KeyError: If request_id not found
        """
        with self._lock:
            if request_id not in self._request_tracking:
                raise KeyError(f"Request {request_id} not found in tracking")

            tracking_data = self._request_tracking.pop(request_id)
            model_id = tracking_data['model_id']

            # Calculate metrics
            queue_wait_ms = (time.time() - tracking_data['arrival_time']) * 1000 - duration_ms

            # Decrement active request count
            provider = self._get_provider_for_model(model_id)
            provider.decrement_active(model_id)

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

    def _get_provider_for_model(self, model_id: int) -> OllamaDataProvider:
        """
        Get the provider instance for a given model.

        Args:
            model_id: Model to look up

        Returns:
            OllamaDataProvider instance

        Raises:
            ValueError: If model not registered
        """
        if model_id not in self._model_to_provider:
            raise ValueError(f"Model {model_id} not registered with any provider")

        provider_name = self._model_to_provider[model_id]
        return self._providers[provider_name]
