"""
Ollama Scheduling Data Provider.

Queries Ollama /api/ps endpoint to get real-time information about:
- Which models are currently loaded in VRAM
- VRAM usage per model
- Model expiration times (from keep-alive settings)

Provides accurate cold-start prediction and VRAM availability calculation.
"""

import json
import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

import requests

from ..models import ModelStatus, OllamaCapacity, QueueStatePerPriority

# Import queue manager for type hints
try:
    from logos.queue import PriorityQueueManager
except ImportError:
    PriorityQueueManager = None  # Type hint only


logger = logging.getLogger(__name__)


class OllamaDataProvider:
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
    #TODO: develop better solution for tracking the current parallel capacity
    DEFAULT_PARALLEL_CAPACITY = 1  # OLLAMA_NUM_PARALLEL in default configuration has auto values between 1 and 4 
    DEFAULT_KEEP_ALIVE_SECONDS = 300  # 5 minutes (Ollama default)
    DEFAULT_MAX_LOADED_MODELS = 6  # 3 models × 2 GPUs
    DEFAULT_MAX_QUEUE = 512  # Total queue limit (matches OLLAMA_MAX_QUEUE)

    def __init__(
        self,
        provider_id: int,
        name: str,
        base_url: Optional[str],
        total_vram_mb: int,
        queue_manager: "PriorityQueueManager",  # REQUIRED
        refresh_interval: float = 5.0,
        db_manager = None
    ):
        """
        Initialize Ollama provider.

        Args:
            name: Provider identifier (e.g., 'openwebui')
            name: Provider identifier (e.g., 'openwebui')
            base_url: Ollama API base URL (optional)
            total_vram_mb: Total VRAM capacity in MB (e.g., 49152 for 48GB)
            queue_manager: PriorityQueueManager instance (REQUIRED for Ollama)
            refresh_interval: Seconds between /api/ps polls (default: 5.0)
            provider_id: Database provider ID (for config lookups)
            db_manager: Database manager instance (for config lookups)
        """
        self.provider_id = provider_id
        self.name = name
        self.base_url = base_url.rstrip('/') if base_url else None
        
        if not self.base_url:
            logger.warning(f"[{self.name}] No base_url provided. Scheduling data will be limited (no VRAM/loading stats).")

        self.total_vram_mb = total_vram_mb
        self.queue_manager = queue_manager  # Store queue manager reference
        self.refresh_interval = refresh_interval
        self._db = db_manager

        # Model registration
        self._model_id_to_name: Dict[int, str] = {}  # model_id → model_name

        # Cached data from /api/ps
        self._loaded_models: Dict[str, Dict] = {}  # model_name → {'size_vram': int, 'expires_at': datetime}
        self._last_refresh: float = 0.0

        # Track active requests (NOT queue - queue is in queue_manager)
        self._model_active: Dict[int, int] = {}  # model_id → requests currently processing

        # Thread safety
        self._lock = threading.RLock()

        # Load provider-level config from database
        self._provider_config = self._load_provider_config()

    def _load_provider_config(self) -> Dict[str, Any]:
        """
        Load provider-level configuration from providers table.

        Returns:
            Dictionary with provider config or empty dict if not found
        """
        try:
            if self._db:
                config = self._db.get_provider_config(self.provider_id)
                return config if config else {}
            
            # Fallback: Create temporary DB connection
            from logos.dbutils.dbmanager import DBManager
            with DBManager() as db:
                config = db.get_provider_config(self.provider_id)
                return config if config else {}
                
        except Exception as e:
            logger.warning(f"[{self.name}] Failed to load provider config: {e}")
            return {}

    def get_config_value(
        self,
        model_id: int,
        config_key: str,
        default_value: Any
    ) -> Any:
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

    def register_model(self, model_id: int, model_name: str) -> None:
        """
        Register a model with this provider.

        Args:
            model_id: Model ID
            model_name: Model name (e.g., 'llama3.1:8b')
        """
        # Lock protects concurrent access to model registry and tracking dicts
        with self._lock:
            self._model_id_to_name[model_id] = model_name
            if model_id not in self._model_active:
                self._model_active[model_id] = 0
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

        data = self._fetch_ps_data()
        if data is None:
            return

        models = data.get("models", [])
        logger.debug(
            "[%s] /api/ps payload models=%s",
            self.name,
            json.dumps(models, default=str)
        )

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

        loaded_debug = {
            name: {
                "size_vram": info.get("size_vram", 0),
                "expires_at": info.get("expires_at").isoformat() if info.get("expires_at") else None,
            }
            for name, info in self._loaded_models.items()
        }
        logger.debug(
            "[%s] Refreshed /api/ps: %d models loaded details=%s",
            self.name,
            len(self._loaded_models),
            json.dumps(loaded_debug, default=str)
        )

    def _fetch_ps_data(self) -> Optional[Dict[str, Any]]:
        """
        Fetch /api/ps either directly over HTTP .
        """
        data: Optional[Dict[str, Any]] = None

        if self.base_url:
            data = self._fetch_ps_via_http()
        
        if data is None:
            logger.warning(f"[{self.name}] Unable to fetch /api/ps via HTTP")
        return data

    def _fetch_ps_via_http(self) -> Optional[Dict[str, Any]]:
        """
        Fetch /api/ps using the configured HTTP base URL.
        """
        if not self.base_url:
            return None
        try:
            headers = self._get_auth_headers_for_ps()
            response = requests.get(
                f"{self.base_url}/api/ps",
                headers=headers if headers else None,
                timeout=5.0
            )

            if response.status_code == 200:
                return response.json()

            logger.warning(f"[{self.name}] /api/ps returned status {response.status_code}")
        except requests.exceptions.Timeout:
            logger.warning(f"[{self.name}] /api/ps query timed out")
        except requests.exceptions.RequestException as e:
            logger.warning(f"[{self.name}] Failed to query /api/ps: {e}")
        except Exception as e:
            logger.error(f"[{self.name}] Unexpected error querying /api/ps: {e}")

        return None

    def _get_auth_headers_for_ps(self, provider_id: int) -> Dict[str, str] | None:
        """
        Build auth headers for /api/ps based on provider config in DB.
        """
        try:
            if self._db:
                auth = self._db.get_provider_auth(self.provider_id)
            else:
                from logos.dbutils.dbmanager import DBManager
                with DBManager() as db:
                    auth = db.get_provider_auth(provider_id)

            if not auth:
                return {}

            auth_name = (auth.get("auth_name") or "").strip()
            auth_format = auth.get("auth_format") or ""
            api_key = auth.get("api_key")

            if not auth_name or not auth_format:
                return {}
            if not api_key:
                logger.warning(
                    "Missing API key for provider=%s - /api/ps auth skipped",
                    provider_id
                )
                return {}

            return {auth_name: auth_format.format(api_key)}
        except Exception as e:
            logger.warning(f"Failed to resolve /api/ps auth for {provider_id}: {e}")
            return {}



    def get_model_status(self, model_id: int) -> ModelStatus:
        """
        Get model status using /api/ps data.

        Returns accurate cold-start prediction based on whether model
        is currently loaded and has not expired.

        Args:
            model_id: Model to query

        Returns:
            ModelStatus dataclass

        Raises:
            ValueError: If model not registered
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

            # Query queue state from queue_manager (real 3-level breakdown)
            queue_state = self.queue_manager.get_state(model_id)

            # Track active requests separately
            active_requests = self._model_active.get(model_id, 0)

            if loaded_info:
                # Model is loaded - check if expired
                now = datetime.now(timezone.utc)
                is_expired = loaded_info['expires_at'] < now

                return ModelStatus(
                    model_id=model_id,
                    provider_id=self.provider_id,
                    is_loaded=not is_expired,
                    vram_mb=loaded_info['size_vram'] // (1024 * 1024),
                    expires_at=loaded_info['expires_at'],
                    queue_state=queue_state,  # Real 3-level breakdown from queue_manager
                    active_requests=active_requests,
                    provider_type='ollama'
                )
            else:
                # Model not loaded
                return ModelStatus(
                    model_id=model_id,
                    provider_id=self.provider_id,
                    is_loaded=False,
                    vram_mb=0,
                    expires_at=None,
                    queue_state=queue_state,  # Real 3-level breakdown from queue_manager
                    active_requests=active_requests,
                    provider_type='ollama'
                )

    def get_capacity_info(self) -> OllamaCapacity:
        """
        Calculate VRAM availability from /api/ps data.

        Returns total VRAM, used VRAM, available VRAM, and loaded models.

        Returns:
            OllamaCapacity dataclass
        """
        self.refresh_data()  # Update if stale

        with self._lock:
            # Calculate total VRAM usage
            total_used_bytes = sum(
                info['size_vram'] for info in self._loaded_models.values()
            )
            used_vram_mb = total_used_bytes // (1024 * 1024)
            available_vram_mb = max(0, self.total_vram_mb - used_vram_mb)

            return OllamaCapacity(
                available_vram_mb=available_vram_mb,
                total_vram_mb=self.total_vram_mb,
                loaded_models=list(self._loaded_models.keys())
            )

    def increment_active(self, model_id: int) -> None:
        """
        Track when a request starts processing.

        Called when a request begins execution (after being dequeued from queue_manager).

        Args:
            model_id: Model handling the request
        """
        with self._lock:
            self._model_active[model_id] = self._model_active.get(model_id, 0) + 1

    def decrement_active(self, model_id: int, reuse_slot: bool = False) -> None:
        """
        Track when a request completes processing.
        
        Args:
            model_id: Model that handled the request
            reuse_slot: If True, do NOT decrement count (hand off to queued request)
        """
        if reuse_slot:
            # Slot is being handed off to a queued request immediately.
            # Do not decrement the counter.
            logger.debug(f"Reuse slot for model {model_id}, active count remains {self._model_active.get(model_id, 0)}")
            return

        with self._lock:
            current_active = self._model_active.get(model_id, 0)
            self._model_active[model_id] = max(0, current_active - 1)
            logger.debug(f"Decremented active count for model {model_id}: {current_active} -> {self._model_active[model_id]}")

    def try_reserve_capacity(self, model_id: int) -> bool:
        """
        Atomically check availability and reserve capacity.
        
        Returns:
            True if capacity was available and reserved.
            False if busy (should queue).
        """
        with self._lock:
            current_active = self._model_active.get(model_id, 0)
            max_capacity = self.get_config_value(model_id, "parallel_capacity", self.DEFAULT_PARALLEL_CAPACITY)
            
            if current_active < max_capacity:
                self._model_active[model_id] = current_active + 1
                logger.debug(f"Reserved capacity for model {model_id}: {current_active} -> {self._model_active[model_id]} (max={max_capacity})")
                return True
            logger.debug(f"Capacity full for model {model_id}: {current_active}/{max_capacity}")
            return False

    def get_active_count(self, model_id: int) -> int:
        """
        Get number of currently active requests for a model.

        Returns:
            Number of requests currently being processed
        """
        with self._lock:
            return self._model_active.get(model_id, 0)

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
