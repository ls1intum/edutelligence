"""
Scheduling Data Provider Implementations.

Concrete implementations of the SchedulingDataProvider interface:
- OllamaDataProvider: Queries /api/ps for VRAM and model loading data
- CloudDataProvider: Base for cloud providers (Azure)
- AzureDataProvider: Azure-specific implementation
"""

import logging
import re
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import requests

from .provider_interface import SchedulingDataProvider


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


class OllamaDataProvider(SchedulingDataProvider):
    """
    Ollama provider implementation using /api/ps endpoint.

    Polls /api/ps periodically to get ground truth about:
    - Which models are currently loaded in VRAM
    - VRAM usage per model (size_vram field)
    - Model expiration times (expires_at field from keep-alive)

    Provides accurate cold-start prediction and VRAM availability calculation.

    Configuration Hierarchy:
    1. model_provider_config (per-model overrides)
    2. providers table (provider-level defaults)
    3. Hardcoded defaults (fallback)
    """

    # Hardcoded defaults (fallback when no database config exists)
    # Based on Ollama production deployment with 2 GPUs
    DEFAULT_PARALLEL_CAPACITY = 4  # Matches OLLAMA_NUM_PARALLEL high-memory auto-select
    DEFAULT_KEEP_ALIVE_SECONDS = 300  # 5 minutes (Ollama default)
    DEFAULT_MAX_LOADED_MODELS = 6  # 3 models × 2 GPUs
    DEFAULT_MAX_QUEUE = 512  # Total queue limit (matches OLLAMA_MAX_QUEUE)

    def __init__(
        self,
        name: str,
        base_url: str,
        total_vram_mb: int,
        refresh_interval: float = 5.0,
        provider_id: Optional[int] = None,
        db_manager = None
    ):
        """
        Initialize Ollama provider.

        Args:
            name: Provider identifier (e.g., 'openwebui')
            base_url: Ollama API base URL
            total_vram_mb: Total VRAM capacity in MB (e.g., 49152 for 48GB)
            refresh_interval: Seconds between /api/ps polls (default: 5.0)
            provider_id: Database provider ID (for config lookups)
            db_manager: Database manager instance (for config lookups)
        """
        super().__init__(name)
        self.base_url = base_url.rstrip('/')
        self.total_vram_mb = total_vram_mb
        self.refresh_interval = refresh_interval
        self.provider_id = provider_id
        self._db = db_manager

        # Model registration
        self._model_id_to_name: Dict[int, str] = {}  # model_id → model_name

        # Cached data from /api/ps
        self._loaded_models: Dict[str, Dict] = {}  # model_name → {'size_vram': int, 'expires_at': datetime}
        self._last_refresh: float = 0.0

        # Queue tracking
        self._model_queues: Dict[int, int] = {}  # model_id → queue_depth

        # Thread safety
        self._lock = threading.RLock()

        # Load provider-level config from database
        self._provider_config = self._load_provider_config()

    def _load_provider_config(self) -> Dict:
        """
        Load provider-level configuration from providers table.

        Returns:
            Dictionary with provider config or empty dict if not found
        """
        if not self._db or not self.provider_id:
            return {}

        try:
            config = self._db.get_provider_config(self.provider_id)
            return config if config else {}
        except Exception as e:
            logger.warning(f"[{self.name}] Failed to load provider config: {e}")
            return {}

    def get_config_value(
        self,
        model_id: int,
        config_key: str,
        default_value: any
    ) -> any:
        """
        Get configuration value using the hierarchy:
        1. model_provider_config (per-model override)
        2. providers table (provider default)
        3. Hardcoded default

        Args:
            model_id: Model ID to check for per-model override
            config_key: Configuration key (e.g., 'parallel_capacity')
            default_value: Hardcoded default value

        Returns:
            Configuration value from the highest priority source
        """
        # Level 1: Check model_provider_config
        if self._db and model_id:
            try:
                model_config = self._db.get_model_provider_config(model_id, self.name)
                if model_config and model_config.get(config_key) is not None:
                    return model_config[config_key]
            except Exception as e:
                logger.warning(f"[{self.name}] Failed to get model config: {e}")

        # Level 2: Check providers table (loaded from _provider_config)
        if self._provider_config.get(config_key) is not None:
            return self._provider_config[config_key]

        # Level 3: Use hardcoded default
        return default_value

    def register_model(self, model_id: int, model_name: str, deployment_name: Optional[str] = None) -> None:
        """
        Register a model with this provider.

        Args:
            model_id: Model ID
            model_name: Model name
            deployment_name: Ignored for Ollama (kept for interface compatibility)
        """
        # Lock protects concurrent access to model registry and queue dicts
        with self._lock:
            self._model_id_to_name[model_id] = model_name
            if model_id not in self._model_queues:
                self._model_queues[model_id] = 0
        logger.info(f"[{self.name}] Registered model {model_id} as '{model_name}'")

    def refresh_data(self) -> None:
        """
        Query /api/ps endpoint and update cache.

        Polls /api/ps if data is stale (older than refresh_interval).
        Thread-safe and handles failures gracefully.
        """
        now = time.time()
        with self._lock:
            if now - self._last_refresh < self.refresh_interval:
                return  # Data is fresh

        # Query /api/ps (without holding lock to avoid blocking)
        try:
            response = requests.get(
                f"{self.base_url}/api/ps",
                timeout=5.0
            )

            if response.status_code == 200:
                data = response.json()
                models = data.get("models", [])

                # Update cache with lock
                with self._lock:
                    self._loaded_models = {}
                    for model in models:
                        model_name = model.get("name") or model.get("model")
                        if model_name:
                            self._loaded_models[model_name] = {
                                'size_vram': model.get("size_vram", 0),
                                'expires_at': self._parse_timestamp(model.get("expires_at"))
                            }
                    self._last_refresh = now

                logger.debug(f"[{self.name}] Refreshed /api/ps: {len(self._loaded_models)} models loaded")
            else:
                logger.warning(
                    f"[{self.name}] /api/ps returned status {response.status_code}"
                )

        except requests.exceptions.Timeout:
            logger.warning(f"[{self.name}] /api/ps query timed out")
        except requests.exceptions.RequestException as e:
            logger.warning(f"[{self.name}] Failed to query /api/ps: {e}")
        except Exception as e:
            logger.error(f"[{self.name}] Unexpected error querying /api/ps: {e}")

    def get_model_status(self, model_id: int) -> Dict:
        """
        Get model status using /api/ps data.

        Returns accurate cold-start prediction based on whether model
        is currently loaded and has not expired.
        """
        self.refresh_data()  # Update if stale

        model_name = self._model_id_to_name.get(model_id)
        if not model_name:
            raise ValueError(
                f"Model {model_id} not registered with provider '{self.name}'. "
                f"Call register_model() first."
            )

        with self._lock:
            loaded_info = self._loaded_models.get(model_name)
            queue_depth = self._model_queues.get(model_id, 0)

            if loaded_info:
                # Model is loaded - check if expired
                now = datetime.now(timezone.utc)
                is_expired = loaded_info['expires_at'] < now

                return {
                    'model_id': model_id,
                    'is_loaded': not is_expired,
                    'cold_start_predicted': is_expired,
                    'vram_mb': loaded_info['size_vram'] // (1024 * 1024),
                    'expires_at': loaded_info['expires_at'],
                    'queue_depth': queue_depth,
                    'active_requests': queue_depth,  # Approximation: queue_depth = active + queued
                    'provider_type': 'ollama'
                }
            else:
                # Model not loaded - cold start guaranteed
                return {
                    'model_id': model_id,
                    'is_loaded': False,
                    'cold_start_predicted': True,
                    'vram_mb': 0,
                    'expires_at': None,
                    'queue_depth': queue_depth,
                    'active_requests': queue_depth,
                    'provider_type': 'ollama'
                }

    def get_capacity_info(self) -> Dict:
        """
        Calculate VRAM availability from /api/ps data.

        Returns total VRAM, used VRAM, available VRAM, and loaded models.
        """
        self.refresh_data()  # Update if stale

        with self._lock:
            # Calculate total VRAM usage
            total_used_bytes = sum(
                info['size_vram'] for info in self._loaded_models.values()
            )
            used_vram_mb = total_used_bytes // (1024 * 1024)
            available_vram_mb = max(0, self.total_vram_mb - used_vram_mb)

            # Heuristic: Can load new model if >4GB free (typical small model size)
            can_load = available_vram_mb > 4096

            return {
                'available_vram_mb': available_vram_mb,
                'total_vram_mb': self.total_vram_mb,
                'loaded_models_count': len(self._loaded_models),
                'loaded_models': list(self._loaded_models.keys()),
                'can_load_new_model': can_load
            }

    def increment_queue(self, model_id: int) -> None:
        """Increment queue depth when request arrives."""
        with self._lock:
            self._model_queues[model_id] = self._model_queues.get(model_id, 0) + 1

    def decrement_queue(self, model_id: int) -> None:
        """Decrement queue depth when request completes."""
        with self._lock:
            current = self._model_queues.get(model_id, 0)
            self._model_queues[model_id] = max(0, current - 1)

    def get_queue_depth(self, model_id: int) -> int:
        """Get current queue depth for a model."""
        with self._lock:
            return self._model_queues.get(model_id, 0)

    def _parse_timestamp(self, ts_str: Optional[str]) -> datetime:
        """
        Parse Ollama timestamp format.

        Args:
            ts_str: ISO8601 timestamp string (e.g., '2025-01-06T15:30:00Z')

        Returns:
            Parsed datetime in UTC. If parsing fails, returns 1 hour from now as fallback.
        """
        if not ts_str:
            # No expiration time provided - assume 1 hour keep-alive
            return datetime.now(timezone.utc) + timedelta(hours=1)

        try:
            # Remove 'Z' suffix and parse as UTC
            ts_clean = ts_str.rstrip('Z')
            dt = datetime.fromisoformat(ts_clean)

            # Ensure timezone-aware
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            return dt

        except (ValueError, AttributeError) as e:
            logger.warning(f"[{self.name}] Failed to parse timestamp '{ts_str}': {e}")
            # Fallback: 1 hour from now
            return datetime.now(timezone.utc) + timedelta(hours=1)


class CloudDataProvider(SchedulingDataProvider):
    """
    Base provider for cloud services (Azure).

    Cloud providers have:
    - No VRAM constraints (unlimited capacity)
    - No cold starts (models always available)
    - Rate limits (tracked via response headers)

    Rate limits are tracked PER DEPLOYMENT internally.
    Each Azure deployment (gpt-4o, o3-mini, etc.) has separate rate limits
    stored in the _deployment_limits dictionary.

    Rate limits are updated by calling update_rate_limits(deployment_name, headers).
    """

    def __init__(self, name: str):
        """
        Initialize cloud provider.

        Args:
            name: Provider identifier (e.g., 'azure')
        """
        super().__init__(name)

        # Per-deployment rate limit tracking
        # deployment_name → {rate limit data}
        self._deployment_limits: Dict[str, Dict] = {}

        # Model registration
        self._registered_models: Dict[int, str] = {}  # model_id → model_name
        self._model_to_deployment: Dict[int, str] = {}  # model_id → deployment_name

        # Queue tracking
        self._model_queues: Dict[int, int] = {}  # model_id → queue_depth

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

    def register_model(self, model_id: int, model_name: str, deployment_name: Optional[str] = None) -> None:
        """
        Register a model with this provider.

        Args:
            model_id: Model ID
            model_name: Model name
            deployment_name: Deployment identifier (for Azure: extracted from endpoint)
                            If not provided, uses "default"
        """
        with self._lock:
            deployment = deployment_name or "default"
            self._registered_models[model_id] = model_name
            self._model_to_deployment[model_id] = deployment
            if model_id not in self._model_queues:
                self._model_queues[model_id] = 0
            self._ensure_deployment(deployment)
        logger.info(f"[{self.name}] Registered model {model_id} as '{model_name}' (deployment: {deployment})")

    def get_model_status(self, model_id: int) -> Dict:
        """
        Get model status for cloud provider.

        Cloud models are always available (no cold starts, no VRAM constraints).
        """
        if model_id not in self._registered_models:
            raise ValueError(
                f"Model {model_id} not registered with provider '{self.name}'. "
                f"Call register_model() first."
            )

        with self._lock:
            queue_depth = self._model_queues.get(model_id, 0)

            return {
                'model_id': model_id,
                'is_loaded': True,  # Always available in cloud
                'cold_start_predicted': False,  # No cold starts
                'vram_mb': 0,  # No VRAM constraints
                'expires_at': None,  # No expiration
                'queue_depth': queue_depth,
                'active_requests': queue_depth,
                'provider_type': self.name.lower()
            }

    def get_capacity_info(self, deployment_name: Optional[str] = None) -> Dict:
        """
        Return rate limit status for a specific deployment.

        Args:
            deployment_name: Deployment to query. If None, uses "default"

        Returns:
            Dict with rate limit information including:
            - deployment_name: Deployment identifier
            - rate_limit_remaining_requests: Current remaining requests
            - rate_limit_remaining_tokens: Current remaining tokens
            - rate_limit_total_requests: Total request limit
            - rate_limit_total_tokens: Total token limit
            - last_header_age_seconds: Seconds since last update (None if never updated)
            - has_capacity: Whether deployment has capacity (>10 requests remaining)
        """
        with self._lock:
            deployment = deployment_name or "default"
            self._ensure_deployment(deployment)
            limits = self._deployment_limits[deployment]

            # Calculate header staleness
            header_age_seconds = None
            if limits['last_update_time'] is not None:
                header_age_seconds = time.time() - limits['last_update_time']

            # Consider capacity available if no rate limit data or limits not exceeded
            has_capacity = (
                limits['remaining_requests'] is None or
                limits['remaining_requests'] > 10  # Conservative threshold
            )

            return {
                'deployment_name': deployment,
                'rate_limit_remaining_requests': limits['remaining_requests'],
                'rate_limit_remaining_tokens': limits['remaining_tokens'],
                'rate_limit_total_requests': limits['total_requests'],
                'rate_limit_total_tokens': limits['total_tokens'],
                'rate_limit_resets_at': limits['resets_at'],
                'last_header_age_seconds': header_age_seconds,
                'has_capacity': has_capacity
            }

    def update_rate_limits(self, deployment_name: str, response_headers: Dict[str, str]) -> None:
        """
        Parse and update rate limit information from API response headers for a specific deployment.

        Should be called after each request to the cloud provider API.

        Args:
            deployment_name: Deployment identifier (e.g., 'gpt-4o', 'o3-mini')
            response_headers: HTTP response headers from API call

        Common headers (availability varies by provider):
            - x-ratelimit-remaining-requests (Azure, OpenAI)
            - x-ratelimit-remaining-tokens (Azure, OpenAI)
            - x-ratelimit-limit-requests (Azure, OpenAI)
            - x-ratelimit-limit-tokens (Azure, OpenAI)
            - x-ratelimit-reset-requests (OpenAI only - Azure does NOT provide)

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

            # Parse reset time (if provided - not available for Azure)
            reset_str = response_headers.get('x-ratelimit-reset-requests')
            if reset_str:
                try:
                    # Try parsing as ISO8601 timestamp
                    limits['resets_at'] = datetime.fromisoformat(reset_str.rstrip('Z'))
                except ValueError:
                    try:
                        # Try parsing as Unix timestamp
                        reset_timestamp = float(reset_str)
                        limits['resets_at'] = datetime.fromtimestamp(reset_timestamp, tz=timezone.utc)
                    except ValueError:
                        logger.warning(f"[{self.name}:{deployment_name}] Invalid reset time header: {reset_str}")

        logger.debug(
            f"[{self.name}:{deployment_name}] Rate limits updated: "
            f"remaining={limits['remaining_requests']}/{limits['total_requests']}, "
            f"tokens={limits['remaining_tokens']}/{limits['total_tokens']}"
        )

    def refresh_data(self) -> None:
        """
        Cloud providers don't poll - data updated via update_rate_limits().

        This method is a no-op for cloud providers.
        """
        pass

    def increment_queue(self, model_id: int) -> None:
        """Increment queue depth when request arrives."""
        with self._lock:
            self._model_queues[model_id] = self._model_queues.get(model_id, 0) + 1

    def decrement_queue(self, model_id: int) -> None:
        """Decrement queue depth when request completes."""
        with self._lock:
            current = self._model_queues.get(model_id, 0)
            self._model_queues[model_id] = max(0, current - 1)

    def get_queue_depth(self, model_id: int) -> int:
        """Get current queue depth for a model."""
        with self._lock:
            return self._model_queues.get(model_id, 0)


class AzureDataProvider(CloudDataProvider):
    """
    Azure provider implementation.

    Inherits all cloud provider behavior. Can be extended with
    Azure-specific features (e.g., deployment-specific rate limits).
    """

    def __init__(self):
        super().__init__("azure")
