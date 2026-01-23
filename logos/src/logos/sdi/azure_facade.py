"""
Azure-specific Scheduling Data Facade.

Provides a type-safe API for accessing scheduling data from Azure providers.
Returns dataclasses instead of dictionaries for better type safety.
Handles per-deployment rate limit tracking.
"""

import logging
import threading
from typing import Dict, List, Optional

from .models import ModelStatus, AzureCapacity
from .providers import AzureDataProvider, extract_azure_deployment_name


logger = logging.getLogger(__name__)


class AzureSchedulingDataFacade:
    """
    Facade for accessing Azure scheduling data with strong typing.

    Simplifies scheduler interaction by:
    - Managing Azure provider lifecycle
    - Tracking per-deployment rate limits
    - Providing type-safe responses via dataclasses

    Note: Azure is a cloud provider with no visibility into queue state or active requests.
    For local queue tracking, see OllamaSchedulingDataFacade.

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
        status = facade.get_model_status(5, provider_id=10)
        # Note: Azure models are always loaded (status.is_loaded == True)

        # Get rate limit info for a deployment (returns AzureCapacity dataclass)
        capacity = facade.get_capacity_info(10, 'gpt-4o')
        if capacity.has_capacity:
            # Send request
            ...

        # Update rate limits after API response
        facade.update_rate_limits(10, 'gpt-4o', response.headers)
    """

    def __init__(self, db_manager=None):
        """
        Initialize Azure scheduling data facade.

        Args:
            db_manager: Optional database manager for configuration lookups
        """
        self._db = db_manager

        # Provider management (Azure providers only)
        self._providers: Dict[int, AzureDataProvider] = {}  # provider_id → provider
        self._deployments: set[tuple[int, int]] = set()  # (model_id, provider_id)

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
            provider_name: Provider identifier (display name)
            model_name: Model name (e.g., 'gpt-4')
            model_endpoint: Full Azure endpoint URL (for extracting deployment name)
            provider_id: Database provider ID (for config lookups)
        """
        with self._lock:
            # Create provider if it doesn't exist
            if provider_id is None:
                raise ValueError(f"provider_id is required for Azure model {model_id} ({provider_name})")

            provider_key = int(provider_id)

            if provider_key not in self._providers:
                provider = AzureDataProvider(
                    name=provider_name,
                    db_manager=self._db,
                    provider_id=provider_id
                )
                self._providers[provider_key] = provider
                logger.info("Created Azure provider '%s' (id=%s)", provider_name, provider_key)

            # Extract deployment name from endpoint
            deployment_name = extract_azure_deployment_name(model_endpoint)
            if not deployment_name:
                logger.error(
                    "Failed to extract Azure deployment name",
                    extra={
                        "model_id": model_id,
                        "provider_name": provider_name,
                        "model_endpoint": model_endpoint,
                    },
                )
                raise ValueError(
                    f"Invalid Azure model_endpoint for model {model_id} / provider '{provider_name}': {model_endpoint}"
                )

            # Register model with provider (includes deployment name)
            provider = self._providers[provider_key]
            provider.register_model(model_id, model_name, deployment_name=deployment_name)
            self._deployments.add((int(model_id), provider_key))

            logger.info(
                f"Registered model {model_id} as '{model_name}' "
                f"with Azure provider '{provider_name}' (id={provider_key}, deployment: {deployment_name})"
            )

    def get_model_status(self, model_id: int, provider_id: int) -> ModelStatus:
        """
        Get current status for a specific model.

        Args:
            model_id: Model to query
            provider_id: Provider ID hosting this deployment

        Returns:
            ModelStatus dataclass with scheduling data

        Raises:
            ValueError: If model not registered
        """
        provider = self._get_provider_for_model(model_id, provider_id)
        return provider.get_model_status(model_id)

    def get_model_capacity(self, model_id: int, provider_id: int) -> Optional[AzureCapacity]:
        """
        Get capacity info for a specific model (resolving deployment automatically).

        Args:
            model_id: Model to query
            provider_id: Provider ID hosting this deployment

        Returns:
            AzureCapacity dataclass or None if not found
        """
        try:
            provider = self._get_provider_for_model(model_id, provider_id)
            # Retrieve deployment name associated with the model
            deployment_name = provider._model_to_deployment.get(model_id)
            if not deployment_name:
                return None
                
            return provider.get_capacity_info(deployment_name)
            
        except (ValueError, KeyError):
            return None

    def get_capacity_info(self, provider_id: int, deployment_name: str) -> AzureCapacity:
        """
        Get rate limit capacity information for a specific Azure deployment.

        Args:
            provider_id: Provider to query
            deployment_name: Deployment identifier (e.g., 'gpt-4o', 'o3-mini')

        Returns:
            AzureCapacity dataclass with per-deployment rate limit info

        Raises:
            KeyError: If provider doesn't exist
        """
        provider_key = int(provider_id)
        if provider_key not in self._providers:
            raise KeyError(f"Provider '{provider_id}' not found")

        provider = self._providers[provider_key]
        # Provider already returns AzureCapacity dataclass
        return provider.get_capacity_info(deployment_name=deployment_name)

    def update_rate_limits(
        self,
        provider_id: int,
        deployment_name: str,
        response_headers: Dict[str, str]
    ) -> None:
        """
        Update rate limit information from API response headers.

        Should be called after each request to Azure to track rate limits per deployment.

        Args:
            provider_id: Provider identifier
            deployment_name: Deployment that was called (e.g., 'gpt-4o')
            response_headers: HTTP response headers from Azure API

        Raises:
            KeyError: If provider doesn't exist
        """
        provider_key = int(provider_id)
        if provider_key not in self._providers:
            raise KeyError(f"Provider '{provider_id}' not found")

        provider = self._providers[provider_key]
        provider.update_rate_limits(deployment_name, response_headers)

        logger.debug("Updated rate limits for provider=%s deployment=%s", provider_id, deployment_name)

    def update_model_rate_limits(self, model_id: int, provider_id: int, response_headers: Dict[str, str]) -> None:
        """
        Update rate limits for the deployment associated with a specific model ID.
        
        This is a convenience wrapper that looks up the deployment name for the given model
        and then calls update_rate_limits().
        """
        try:
            provider = self._get_provider_for_model(model_id, provider_id)
            # Find deployment (internal lookup)
            deployment_name = provider._model_to_deployment.get(model_id)
            if deployment_name:
                provider.update_rate_limits(deployment_name, response_headers)
        except (ValueError, KeyError, AttributeError):
            pass

    def get_scheduling_data(self, deployments: List[tuple[int, int]]) -> List[ModelStatus]:
        """
        Batch query for multiple models (optimized).

        Args:
            deployments: List of (model_id, provider_id) tuples

        Returns:
            List of ModelStatus dataclasses, one per model
        """
        return [self.get_model_status(model_id, provider_id) for model_id, provider_id in deployments]

    # NOTE: Cloud providers (Azure) manage queues internally.
    # We have no visibility into their queue state, active requests, or queue depth.
    # Therefore, request lifecycle tracking methods are not applicable for Azure.
    # For Ollama providers with local queue visibility, see OllamaSchedulingDataFacade.

    def _get_provider_for_model(self, model_id: int, provider_id: int) -> AzureDataProvider:
        """
        Get the provider instance for a given model.

        Args:
            model_id: Model to look up
            provider_id: Provider ID hosting the deployment

        Returns:
            AzureDataProvider instance

        Raises:
            ValueError: If model not registered
        """
        provider_key = int(provider_id)
        if (int(model_id), provider_key) not in self._deployments:
            raise ValueError(
                f"Model {model_id} not registered with provider {provider_id}"
            )

        try:
            return self._providers[provider_key]
        except KeyError as exc:
            raise ValueError(f"Provider {provider_id} not registered") from exc
