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
import subprocess
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
        name: str,
        base_url: Optional[str],
        total_vram_mb: int,
        queue_manager: "PriorityQueueManager",  # REQUIRED
        refresh_interval: float = 5.0,
        provider_id: Optional[int] = None,
        db_manager = None
    ):
        """
        Initialize Ollama provider.

        Args:
            name: Provider identifier (e.g., 'openwebui')
            base_url: Ollama API base URL (optional when using SSH config)
            total_vram_mb: Total VRAM capacity in MB (e.g., 49152 for 48GB)
            queue_manager: PriorityQueueManager instance (REQUIRED for Ollama)
            refresh_interval: Seconds between /api/ps polls (default: 5.0)
            provider_id: Database provider ID (for config lookups)
            db_manager: Database manager instance (for config lookups)
        """
        self.name = name
        self.base_url = base_url.rstrip('/') if base_url else ""
        self.total_vram_mb = total_vram_mb
        self.queue_manager = queue_manager  # Store queue manager reference
        self.refresh_interval = refresh_interval
        self.provider_id = provider_id
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
        self._ssh_config = self._build_ssh_config(self._provider_config)
        if not self.base_url and self._provider_config.get("ollama_admin_url"):
            self.base_url = (self._provider_config.get("ollama_admin_url") or "").rstrip('/')

    def _load_provider_config(self) -> Dict[str, Any]:
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

    def _build_ssh_config(self, provider_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract SSH connection details for private Ollama servers.
        """
        if not provider_config:
            return None

        ssh_host = provider_config.get("ssh_host")
        if not ssh_host:
            return None

        return {
            "host": ssh_host,
            "user": provider_config.get("ssh_user"),
            "port": provider_config.get("ssh_port") or 22,
            "key_path": provider_config.get("ssh_key_path"),
            "remote_port": provider_config.get("ssh_remote_ollama_port") or 11434,
        }

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

    def _fetch_ps_data(self) -> Optional[Dict[str, Any]]:
        """
        Fetch /api/ps either directly over HTTP or via SSH if the endpoint is private.
        """
        data: Optional[Dict[str, Any]] = None

        # Prefer HTTP when only base_url is configured, SSH when only SSH is configured.
        if self.base_url and not self._ssh_config:
            data = self._fetch_ps_via_http()
        elif self._ssh_config and not self.base_url:
            data = self._fetch_ps_via_ssh()
        else:
            # Try HTTP first, then fall back to SSH when both are present.
            if self.base_url:
                data = self._fetch_ps_via_http()
            if data is None and self._ssh_config:
                data = self._fetch_ps_via_ssh()

        if data is None:
            logger.warning(f"[{self.name}] Unable to fetch /api/ps via HTTP or SSH")
        return data

    def _fetch_ps_via_http(self) -> Optional[Dict[str, Any]]:
        """
        Fetch /api/ps using the configured HTTP base URL.
        """
        if not self.base_url:
            return None

        try:
            response = requests.get(
                f"{self.base_url}/api/ps",
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

    def _fetch_ps_via_ssh(self) -> Optional[Dict[str, Any]]:
        """
        Fetch /api/ps by executing curl over SSH on the remote host.
        """
        if not self._ssh_config:
            return None

        ssh_host = self._ssh_config.get("host")
        ssh_user = self._ssh_config.get("user")
        ssh_port = self._ssh_config.get("port") or 22
        ssh_key_path = self._ssh_config.get("key_path")
        remote_port = self._ssh_config.get("remote_port") or 11434

        if not ssh_host:
            return None

        ssh_target = f"{ssh_user + '@' if ssh_user else ''}{ssh_host}"
        remote_cmd = f"curl -s http://127.0.0.1:{remote_port}/api/ps"

        ssh_cmd = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            "-p",
            str(ssh_port)
        ]

        if ssh_key_path:
            ssh_cmd.extend(["-i", ssh_key_path])

        ssh_cmd.extend([ssh_target, remote_cmd])

        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                logger.warning(f"[{self.name}] SSH /api/ps failed: {result.stderr.strip()}")
                return None

            return json.loads(result.stdout or "{}")
        except subprocess.TimeoutExpired:
            logger.warning(f"[{self.name}] SSH /api/ps timed out")
        except json.JSONDecodeError as e:
            logger.warning(f"[{self.name}] Failed to parse SSH /api/ps response: {e}")
        except Exception as e:
            logger.error(f"[{self.name}] Unexpected SSH error: {e}")

        return None

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

    def decrement_active(self, model_id: int) -> None:
        """
        Track when a request completes processing.

        Called when a request finishes execution.

        Args:
            model_id: Model that handled the request
        """
        with self._lock:
            current_active = self._model_active.get(model_id, 0)
            self._model_active[model_id] = max(0, current_active - 1)

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
