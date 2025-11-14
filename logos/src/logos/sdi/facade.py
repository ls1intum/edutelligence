"""
Scheduling Data Facade.

Provides a unified API for accessing scheduling data from heterogeneous providers.
Routes queries to appropriate providers (Ollama, Azure) and tracks
request lifecycle for metrics collection.
"""

import logging
import threading
import time
import uuid
from typing import Dict, List, Optional

from .provider_interface import SchedulingDataProvider
from .providers import OllamaDataProvider, AzureDataProvider, extract_azure_deployment_name


logger = logging.getLogger(__name__)


class SchedulingDataFacade:
    """
    Facade providing unified access to scheduling data from multiple providers.

    Simplifies scheduler interaction by:
    - Routing queries to appropriate providers
    - Managing provider lifecycle (creation, registration)
    - Tracking request metrics (queue wait times, cold starts)
    - Providing batch query optimization

    Usage:
        facade = SchedulingDataFacade(db_manager)

        # Register models
        facade.register_model(1, 'openwebui', 'http://gpu:11434', 'llama3.1:8b')
        facade.register_model(5, 'azure', 'https://api.azure.com', 'gpt-4')

        # Query for scheduling decisions
        status = facade.get_model_status(1)
        if not status['cold_start_predicted']:
            # Schedule to this model
            ...

        # Track request lifecycle
        facade.on_request_start('req-123', model_id=1, priority='high')
        # ... process request ...
        metrics = facade.on_request_complete('req-123', was_cold_start=False, duration_ms=250)
    """

    def __init__(self, db_manager=None):
        """
        Initialize scheduling data facade.

        Args:
            db_manager: Optional database manager for configuration lookups
        """
        self._db = db_manager

        # Provider management
        self._providers: Dict[str, SchedulingDataProvider] = {}  # provider_name → provider
        self._model_to_provider: Dict[int, str] = {}  # model_id → provider_name

        # Request tracking
        self._request_tracking: Dict[str, Dict] = {}  # request_id → tracking_data

        # Thread safety
        self._lock = threading.RLock()

        logger.info("SchedulingDataFacade initialized")

    def register_model(
        self,
        model_id: int,
        provider_name: str,
        provider_type: str,
        model_name: str,
        model_endpoint: Optional[str] = None,
        ollama_admin_url: Optional[str] = None,
        total_vram_mb: Optional[int] = None,
        refresh_interval: float = 5.0,
        provider_id: Optional[int] = None
    ) -> None:
        """
        Register a model with the facade.

        Creates provider if it doesn't exist, then registers the model with that provider.

        Args:
            model_id: Internal database ID for the model
            provider_name: Provider identifier (e.g., 'openwebui', 'azure')
            provider_type: 'ollama' or 'cloud'
            model_name: Model name as known by the provider (e.g., 'llama3.1:8b')
            model_endpoint: Full model endpoint URL (for extracting deployment name from Azure URLs)
            ollama_admin_url: Ollama /api/ps endpoint (required if provider_type='ollama')
            total_vram_mb: Total VRAM capacity in MB (required if provider_type='ollama')
            refresh_interval: Polling interval in seconds (default: 5.0)
            provider_id: Database provider ID (for config lookups)
        """
        # Validate inputs
        if provider_type == 'ollama':
            if not ollama_admin_url:
                raise ValueError(f"ollama_admin_url required for Ollama provider '{provider_name}'")
            if not total_vram_mb:
                raise ValueError(f"total_vram_mb required for Ollama provider '{provider_name}'")

        with self._lock:
            # Create unique provider key
            # For Ollama: Use admin URL (different VMs have different URLs)
            # For Cloud: Use provider name (different deployments have different names)
            if provider_type == 'ollama':
                provider_key = f"ollama:{ollama_admin_url}"
            else:
                provider_key = f"cloud:{provider_name}"

            # Create provider if doesn't exist
            if provider_key not in self._providers:
                if provider_type == 'ollama':
                    provider = OllamaDataProvider(
                        name=provider_name,
                        base_url=ollama_admin_url,
                        total_vram_mb=total_vram_mb,
                        refresh_interval=refresh_interval,
                        provider_id=provider_id,
                        db_manager=self._db
                    )
                elif provider_type == 'cloud':
                    provider = AzureDataProvider()
                else:
                    raise ValueError(
                        f"Unknown provider_type: '{provider_type}'. "
                        f"Must be 'ollama' or 'cloud' or extend the providers.py with new providers' logic"
                    )

                self._providers[provider_key] = provider
                logger.info(f"Created {provider_type} provider '{provider_name}' (key: {provider_key})")

            # Register model with provider
            provider = self._providers[provider_key]

            # For cloud providers, extract deployment name from endpoint
            deployment_name = None
            if provider_type == 'cloud' and model_endpoint:
                deployment_name = extract_azure_deployment_name(model_endpoint)
                if deployment_name:
                    logger.debug(f"Extracted deployment name '{deployment_name}' from endpoint")
                else:
                    logger.warning(f"Could not extract deployment name from endpoint: {model_endpoint}")

            provider.register_model(model_id, model_name, deployment_name=deployment_name)

            # Map model to provider key
            self._model_to_provider[model_id] = provider_key

            logger.info(
                f"Registered model {model_id} ('{model_name}') with "
                f"{provider_type} provider '{provider_name}'"
                + (f" (deployment: {deployment_name})" if deployment_name else "")
            )

    def get_model_status(self, model_id: int) -> Dict:
        """
        Get current status for a specific model.

        Routes query to the appropriate provider based on model registration.

        Args:
            model_id: Model to query

        Returns:
            Dictionary with scheduling data:
            {
                'model_id': int,
                'is_loaded': bool,
                'cold_start_predicted': bool,
                'vram_mb': int,
                'expires_at': datetime | None,
                'queue_depth': int,
                'active_requests': int,
                'provider_type': str
            }

        Raises:
            ValueError: If model not registered
        """
        provider = self._get_provider_for_model(model_id)
        return provider.get_model_status(model_id)

    def get_provider_capacity(self, provider_name: str) -> Dict:
        """
        Get provider-level capacity information.

        Args:
            provider_name: Provider to query

        Returns:
            For Ollama:
                {
                    'available_vram_mb': int,
                    'total_vram_mb': int,
                    'loaded_models_count': int,
                    'loaded_models': List[str],
                    'can_load_new_model': bool
                }

            For cloud providers:
                {
                    'rate_limit_remaining_requests': int | None,
                    'rate_limit_remaining_tokens': int | None,
                    'rate_limit_resets_at': datetime | None,
                    'has_capacity': bool
                }

        Raises:
            ValueError: If provider not found
        """
        if provider_name not in self._providers:
            raise ValueError(f"Provider '{provider_name}' not found. Register a model first.")

        return self._providers[provider_name].get_capacity_info()

    def get_scheduling_data(self, model_ids: List[int]) -> List[Dict]:
        """
        Batch query for multiple models.

        Optimization for schedulers that need to compare multiple candidates.

        Args:
            model_ids: List of model IDs to query

        Returns:
            List of model status dictionaries (same format as get_model_status)
        """
        return [self.get_model_status(model_id) for model_id in model_ids]

    def on_request_start(
        self,
        request_id: str,
        model_id: int,
        priority: str = 'medium'
    ) -> None:
        """
        Track request arrival for metrics collection.

        Should be called when request enters the system, before scheduling.

        Args:
            request_id: Unique identifier for this request
            model_id: Model that will handle the request
            priority: Request priority ('high', 'medium', 'low')
        """
        with self._lock:
            # Capture current queue depth
            try:
                status = self.get_model_status(model_id)
                queue_depth_snapshot = status['queue_depth']
            except Exception as e:
                logger.warning(f"Failed to get model status for {model_id}: {e}")
                queue_depth_snapshot = 0

            # Track request
            self._request_tracking[request_id] = {
                'model_id': model_id,
                'priority': priority,
                'arrived_at': time.time(),
                'queue_depth_snapshot': queue_depth_snapshot
            }

            # Increment queue depth
            provider = self._get_provider_for_model(model_id)
            provider.increment_queue(model_id)

        logger.debug(
            f"Request {request_id} started for model {model_id} "
            f"(priority={priority}, queue_depth={queue_depth_snapshot})"
        )

    def on_request_complete(
        self,
        request_id: str,
        was_cold_start: bool,
        duration_ms: float
    ) -> Dict:
        """
        Track request completion and return metrics.

        Should be called after request finishes processing.

        Args:
            request_id: Request identifier (same as on_request_start)
            was_cold_start: Whether this request triggered a cold start
            duration_ms: Total request duration in milliseconds

        Returns:
            Dictionary with metrics for database logging:
            {
                'queue_wait_ms': float,
                'was_cold_start': bool,
                'duration_ms': float,
                'queue_depth_at_arrival': int,
                'priority': str
            }

        Raises:
            ValueError: If request_id not found (on_request_start not called)
        """
        with self._lock:
            if request_id not in self._request_tracking:
                raise ValueError(
                    f"Request {request_id} not found in tracking. "
                    f"Call on_request_start() first."
                )

            tracking = self._request_tracking.pop(request_id)
            model_id = tracking['model_id']

            # Calculate queue wait time
            queue_wait_ms = (time.time() - tracking['arrived_at']) * 1000

            # Decrement queue depth
            provider = self._get_provider_for_model(model_id)
            provider.decrement_queue(model_id)

            metrics = {
                'queue_wait_ms': queue_wait_ms,
                'was_cold_start': was_cold_start,
                'duration_ms': duration_ms,
                'queue_depth_at_arrival': tracking['queue_depth_snapshot'],
                'priority': tracking['priority']
            }

        logger.debug(
            f"Request {request_id} completed: "
            f"wait={queue_wait_ms:.1f}ms, cold={was_cold_start}, duration={duration_ms:.1f}ms"
        )

        return metrics

    def update_cloud_rate_limits(
        self,
        provider_name: str,
        deployment_name: str,
        response_headers: Dict[str, str]
    ) -> None:
        """
        Update rate limit information for a specific cloud deployment.

        Should be called after each API request to Azure with response headers.

        Args:
            provider_name: Cloud provider name ('azure')
            deployment_name: Deployment identifier (e.g., 'gpt-4o', 'o3-mini')
            response_headers: HTTP response headers from API call

        Raises:
            ValueError: If provider not found or not a cloud provider
        """
        if provider_name not in self._providers:
            raise ValueError(f"Provider '{provider_name}' not found")

        provider = self._providers[provider_name]

        # Check if provider supports rate limit updates
        if not hasattr(provider, 'update_rate_limits'):
            raise ValueError(
                f"Provider '{provider_name}' does not support rate limit updates. "
                f"Only cloud providers (Azure) support this."
            )

        provider.update_rate_limits(deployment_name, response_headers)

    def get_all_providers(self) -> List[str]:
        """
        Get list of all registered provider names.

        Returns:
            List of provider identifiers
        """
        with self._lock:
            return list(self._providers.keys())

    def get_all_registered_models(self) -> List[int]:
        """
        Get list of all registered model IDs.

        Returns:
            List of model IDs
        """
        with self._lock:
            return list(self._model_to_provider.keys())

    def _get_provider_for_model(self, model_id: int) -> SchedulingDataProvider:
        """
        Get provider instance for a model.

        Args:
            model_id: Model to look up

        Returns:
            Provider instance

        Raises:
            ValueError: If model not registered
        """
        with self._lock:
            provider_name = self._model_to_provider.get(model_id)

            if not provider_name:
                raise ValueError(
                    f"Model {model_id} not registered. "
                    f"Call register_model() first."
                )

            return self._providers[provider_name]
