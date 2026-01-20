"""
Azure Scheduling Data Provider.

Tracks Azure OpenAI rate limits from API response headers.
Implements per-deployment rate limit tracking since each Azure deployment
(e.g., gpt-4o, o3-mini) has independent rate limits.
"""

import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Optional

from ..models import ModelStatus, AzureCapacity, QueueStatePerPriority


logger = logging.getLogger(__name__)


def extract_azure_deployment_name(endpoint: str) -> Optional[str]:
    """
    Extract deployment name from Azure OpenAI endpoint URL.

    Args:
        endpoint: Azure endpoint URL like:
                  'https://xxx.openai.azure.com/openai/deployments/gpt-4o/chat/completions?api-version=...'

    Returns:
        Deployment name (e.g., 'gpt-4o') or None if not found
    """
    # Pattern: /deployments/{deployment_name}/
    match = re.search(r'/deployments/([^/\?]+)', endpoint)
    if match:
        return match.group(1)
    return None


class AzureDataProvider:
    """
    Azure provider implementation with per-deployment rate limit tracking.

    Azure providers have:
    - No VRAM constraints (unlimited capacity)
    - No cold starts (models always available)
    - Per-deployment rate limits (tracked via response headers)

    Each Azure deployment (gpt-4o, o3-mini, etc.) has separate rate limits
    stored in the _deployment_limits dictionary.

    Rate limits are updated by calling update_rate_limits(deployment_name, headers)
    after each API request.
    """

    def __init__(
        self,
        name: str = "azure",
        provider_id: Optional[int] = None,
        db_manager = None
    ):
        """
        Initialize Azure provider.

        Args:
            name: Provider identifier (default: 'azure')
            provider_id: Database provider ID (for config lookups)
            db_manager: Database manager instance (for config lookups)
        """
        self.name = name
        self.provider_id = provider_id
        self._db = db_manager

        # Per-deployment rate limit tracking
        # deployment_name → {rate limit data}
        self._deployment_limits: Dict[str, Dict] = {}

        # Model registration
        self._registered_models: Dict[int, str] = {}  # model_id → model_name
        self._model_to_deployment: Dict[int, str] = {}  # model_id → deployment_name

        # NO queue/active tracking - cloud providers manage this internally

        # Thread safety
        self._lock = threading.RLock()

    def _ensure_deployment(self, deployment_name: str) -> None:
        """
        Ensure deployment tracking exists.

        Args:
            deployment_name: Deployment identifier
        """
        if deployment_name not in self._deployment_limits:
            self._deployment_limits[deployment_name] = {
                'remaining_requests': None,
                'remaining_tokens': None,
                'total_requests': None,
                'total_tokens': None,
                'resets_at': None,
                'last_update_time': None
            }

    def register_model(
        self,
        model_id: int,
        model_name: str,
        deployment_name: str
    ) -> None:
        """
        Register a model with this provider.

        Args:
            model_id: Model ID
            model_name: Model name (e.g., 'gpt-4')
            deployment_name: Azure deployment identifier (extracted from endpoint URL)
        """
        with self._lock:
            self._registered_models[model_id] = model_name
            self._model_to_deployment[model_id] = deployment_name
            self._ensure_deployment(deployment_name)
        logger.info(f"[{self.name}] Registered model {model_id} as '{model_name}' (deployment: {deployment_name})")

    def get_model_status(self, model_id: int) -> ModelStatus:
        """
        Get model status for Azure provider.

        Azure models are always available (no VRAM constraints, always loaded).

        Args:
            model_id: Model to query

        Returns:
            ModelStatus dataclass

        Raises:
            ValueError: If model not registered
        """
        if model_id not in self._registered_models:
            raise ValueError(
                f"Model {model_id} not registered with provider '{self.name}'. "
                f"Call register_model() first."
            )

        return ModelStatus(
            model_id=model_id,
            is_loaded=True,  # Always available in cloud
            vram_mb=0,  # No VRAM constraints
            expires_at=None,  # No expiration
            queue_state=None,  # Cloud manages queues - no visibility
            active_requests=0,  # Cloud manages this - no visibility
            provider_type=self.name.lower()
        )

    def get_capacity_info(self, deployment_name: str) -> AzureCapacity:
        """
        Return rate limit status for a specific Azure deployment.

        Args:
            deployment_name: Deployment to query (e.g., 'gpt-4o', 'o3-mini')

        Returns:
            AzureCapacity dataclass with per-deployment rate limit information
        """
        with self._lock:
            self._ensure_deployment(deployment_name)
            limits = self._deployment_limits[deployment_name]

            # Calculate header staleness
            header_age_seconds = None
            if limits['last_update_time'] is not None:
                header_age_seconds = time.time() - limits['last_update_time']

            # Consider capacity available if no rate limit data or limits not exceeded
            has_capacity = (
                limits['remaining_requests'] is None or
                limits['remaining_requests'] > 10  # Conservative threshold
            )

            return AzureCapacity(
                deployment_name=deployment_name,
                rate_limit_remaining_requests=limits['remaining_requests'],
                rate_limit_remaining_tokens=limits['remaining_tokens'],
                rate_limit_total_requests=limits['total_requests'],
                rate_limit_total_tokens=limits['total_tokens'],
                rate_limit_resets_at=limits['resets_at'],
                last_header_age_seconds=header_age_seconds,
                has_capacity=has_capacity
            )

    def update_rate_limits(
        self,
        deployment_name: str,
        response_headers: Dict[str, str]
    ) -> None:
        """
        Parse and update rate limit information from API response headers for a specific deployment.

        Should be called after each request to the Azure API.

        Args:
            deployment_name: Deployment identifier (e.g., 'gpt-4o', 'o3-mini')
            response_headers: HTTP response headers from API call

        Common Azure headers:
            - x-ratelimit-remaining-requests
            - x-ratelimit-remaining-tokens
            - x-ratelimit-limit-requests
            - x-ratelimit-limit-tokens

        Note: Azure OpenAI does not provide reset time headers. Based on
        experimentation, Azure rate limits use a fixed clock-based window
        (resets at fixed intervals, likely every minute on the clock).
        The reset time will remain None for Azure, which is acceptable.
        """
        with self._lock:
            self._ensure_deployment(deployment_name)
            limits = self._deployment_limits[deployment_name]

            # Record when this update happened
            limits['last_update_time'] = time.time()

            # Parse total limits (constant per deployment)
            limit_requests_str = response_headers.get('x-ratelimit-limit-requests')
            if limit_requests_str:
                try:
                    limits['total_requests'] = int(limit_requests_str)
                except ValueError:
                    logger.warning(f"[{self.name}:{deployment_name}] Invalid limit header: {limit_requests_str}")

            limit_tokens_str = response_headers.get('x-ratelimit-limit-tokens')
            if limit_tokens_str:
                try:
                    limits['total_tokens'] = int(limit_tokens_str)
                except ValueError:
                    logger.warning(f"[{self.name}:{deployment_name}] Invalid limit header: {limit_tokens_str}")

            # Parse remaining (current snapshot)
            remaining_requests_str = response_headers.get('x-ratelimit-remaining-requests')
            if remaining_requests_str:
                try:
                    limits['remaining_requests'] = int(remaining_requests_str)
                except ValueError:
                    logger.warning(f"[{self.name}:{deployment_name}] Invalid remaining header: {remaining_requests_str}")

            # Parse remaining tokens
            remaining_tokens_str = response_headers.get('x-ratelimit-remaining-tokens')
            if remaining_tokens_str:
                try:
                    limits['remaining_tokens'] = int(remaining_tokens_str)
                except ValueError:
                    logger.warning(f"[{self.name}:{deployment_name}] Invalid token header: {remaining_tokens_str}")

        logger.debug(
            f"[{self.name}:{deployment_name}] Rate limits updated: "
            f"remaining={limits['remaining_requests']}/{limits['total_requests']}, "
            f"tokens={limits['remaining_tokens']}/{limits['total_tokens']}"
        )

    # NO queue/active tracking methods for cloud providers
    # Cloud providers (Azure, OpenAI, etc.) manage queues internally
    # We have no visibility into their queue state or active request count
