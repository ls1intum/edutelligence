"""
Azure-specific Scheduling Data Facade.

Provides a type-safe API for accessing scheduling data from Azure providers.
Returns dataclasses instead of dictionaries for better type safety.
Handles per-deployment rate limit tracking.
"""

import logging
import threading
import time
from typing import Dict, List, Optional

from .models import ModelStatus, AzureCapacity, RequestMetrics
from .providers import AzureDataProvider, extract_azure_deployment_name


logger = logging.getLogger(__name__)


class AzureSchedulingDataFacade:
    """
    Facade for accessing Azure scheduling data with strong typing.

    Simplifies scheduler interaction by:
    - Managing Azure provider lifecycle
    - Tracking per-deployment rate limits
    - Tracking request metrics (queue wait times)
    - Providing type-safe responses via dataclasses

    Usage:
        facade = AzureSchedulingDataFacade(db_manager)

        # Register models with deployment names
        facade.register_model(
            model_id=5,
            provider_name='azure',
            model_name='gpt-4',
            model_endpoint='https://my-resource.openai.azure.com/openai/deployments/gpt-4o/chat/completions',
            provider_id=10
        )

        # Query for scheduling decisions (returns ModelStatus dataclass)
        status = facade.get_model_status(5)
        if status.queue_depth < 10:
            # Schedule to this model
            ...

        # Get rate limit info for a deployment (returns AzureCapacity dataclass)
        capacity = facade.get_capacity_info('azure', 'gpt-4o')
        if capacity.has_capacity:
            # Send request
            ...

        # Update rate limits after API response
        facade.update_rate_limits('azure', 'gpt-4o', response.headers)

        # Track request lifecycle
        facade.on_request_start('req-456', model_id=5, priority='high')
        # ... process request ...
        metrics = facade.on_request_complete('req-456', was_cold_start=False, duration_ms=180)
    """

    def __init__(self, db_manager=None):
        """
        Initialize Azure scheduling data facade.

        Args:
            db_manager: Optional database manager for configuration lookups
        """
        self._db = db_manager

        # Provider management (Azure providers only)
        self._providers: Dict[str, AzureDataProvider] = {}  # provider_name → provider
        self._model_to_provider: Dict[int, str] = {}  # model_id → provider_name

        # Request tracking
        self._request_tracking: Dict[str, Dict] = {}  # request_id → tracking_data

        # Thread safety
        self._lock = threading.RLock()

        logger.info("AzureSchedulingDataFacade initialized")

    def register_model(
        self,
        model_id: int,
        provider_name: str,
        model_name: str,
        model_endpoint: str,
        provider_id: Optional[int] = None
    ) -> None:
        """
        Register a model with the Azure facade.

        Creates Azure provider if it doesn't exist, then registers the model.
        Automatically extracts deployment name from the model_endpoint URL.

        Args:
            model_id: Internal database ID for the model
            provider_name: Provider identifier (e.g., 'azure')
            model_name: Model name (e.g., 'gpt-4')
            model_endpoint: Full Azure endpoint URL (for extracting deployment name)
            provider_id: Database provider ID (for config lookups)
        """
        with self._lock:
            # Create provider if it doesn't exist
            if provider_name not in self._providers:
                provider = AzureDataProvider(
                    name=provider_name,
                    db_manager=self._db,
                    provider_id=provider_id
                )
                self._providers[provider_name] = provider
                logger.info(f"Created Azure provider '{provider_name}'")

            # Extract deployment name from endpoint
            deployment_name = extract_azure_deployment_name(model_endpoint)

            # Register model with provider (includes deployment name)
            provider = self._providers[provider_name]
            provider.register_model(model_id, model_name, deployment_name=deployment_name)
            self._model_to_provider[model_id] = provider_name

            logger.info(
                f"Registered model {model_id} as '{model_name}' "
                f"with Azure provider '{provider_name}' (deployment: {deployment_name})"
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

    def get_capacity_info(self, provider_name: str, deployment_name: str) -> AzureCapacity:
        """
        Get rate limit capacity information for a specific Azure deployment.

        Args:
            provider_name: Provider to query
            deployment_name: Deployment identifier (e.g., 'gpt-4o', 'o3-mini')

        Returns:
            AzureCapacity dataclass with per-deployment rate limit info

        Raises:
            KeyError: If provider doesn't exist
        """
        if provider_name not in self._providers:
            raise KeyError(f"Provider '{provider_name}' not found")

        provider = self._providers[provider_name]
        capacity_dict = provider.get_capacity_info(deployment_name=deployment_name)

        # Convert dict to dataclass
        return AzureCapacity(
            deployment_name=capacity_dict['deployment_name'],
            rate_limit_remaining_requests=capacity_dict['rate_limit_remaining_requests'],
            rate_limit_remaining_tokens=capacity_dict['rate_limit_remaining_tokens'],
            rate_limit_total_requests=capacity_dict['rate_limit_total_requests'],
            rate_limit_total_tokens=capacity_dict['rate_limit_total_tokens'],
            rate_limit_resets_at=capacity_dict['rate_limit_resets_at'],
            last_header_age_seconds=capacity_dict['last_header_age_seconds'],
            has_capacity=capacity_dict['has_capacity']
        )

    def update_rate_limits(
        self,
        provider_name: str,
        deployment_name: str,
        response_headers: Dict[str, str]
    ) -> None:
        """
        Update rate limit information from API response headers.

        Should be called after each request to Azure to track rate limits per deployment.

        Args:
            provider_name: Provider identifier
            deployment_name: Deployment that was called (e.g., 'gpt-4o')
            response_headers: HTTP response headers from Azure API

        Raises:
            KeyError: If provider doesn't exist
        """
        if provider_name not in self._providers:
            raise KeyError(f"Provider '{provider_name}' not found")

        provider = self._providers[provider_name]
        provider.update_rate_limits(deployment_name, response_headers)

        logger.debug(f"Updated rate limits for {provider_name}/{deployment_name}")

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
        Track request arrival and increment queue depth.

        Args:
            request_id: Unique request identifier
            model_id: Model handling the request
            priority: Request priority level
        """
        with self._lock:
            provider = self._get_provider_for_model(model_id)
            provider.enqueue_request(model_id)

            # Get queue depth snapshot after increment
            queue_depth_snapshot = provider.get_queue_depth(model_id)

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
        1. on_request_start() - Request enters queue
        2. on_request_begin_processing() - Request starts processing (queue → active)
        3. on_request_complete() - Request finishes

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

            # Move from queue to active
            provider = self._get_provider_for_model(model_id)
            provider.begin_processing(model_id)

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

        Args:
            request_id: Request that finished
            was_cold_start: Always False for Azure (no cold starts)
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

            # Complete request (decrement active count)
            provider = self._get_provider_for_model(model_id)
            provider.complete_request(model_id)

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
                f"duration={duration_ms:.1f}ms, queue_wait={metrics.queue_wait_ms:.1f}ms"
            )

            return metrics

    def _get_provider_for_model(self, model_id: int) -> AzureDataProvider:
        """
        Get the provider instance for a given model.

        Args:
            model_id: Model to look up

        Returns:
            AzureDataProvider instance

        Raises:
            ValueError: If model not registered
        """
        if model_id not in self._model_to_provider:
            raise ValueError(f"Model {model_id} not registered with any provider")

        provider_name = self._model_to_provider[model_id]
        return self._providers[provider_name]
