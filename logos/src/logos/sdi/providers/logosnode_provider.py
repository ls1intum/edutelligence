"""Scheduling data provider for logosnode deployments."""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

import requests

from logos.logosnode_registry import LogosNodeRuntimeRegistry

from ..models import ModelStatus, OllamaCapacity, QueueStatePerPriority

try:
    from logos.queue import PriorityQueueManager
except ImportError:  # pragma: no cover
    PriorityQueueManager = None

logger = logging.getLogger(__name__)


class LogosNodeDataProvider:
    """Unified local-provider SDI source for direct Ollama and worker-backed lanes."""

    DEFAULT_PARALLEL_CAPACITY = 1

    def __init__(
        self,
        provider_id: int,
        name: str,
        base_url: Optional[str],
        total_vram_mb: int,
        queue_manager: "PriorityQueueManager",
        refresh_interval: float = 5.0,
        db_manager=None,
        runtime_registry: LogosNodeRuntimeRegistry | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.name = name
        self.base_url = base_url.rstrip("/") if base_url else None
        self.total_vram_mb = total_vram_mb
        self.queue_manager = queue_manager
        self.refresh_interval = refresh_interval
        self._db = db_manager
        self._runtime_registry = runtime_registry

        self._model_id_to_name: Dict[int, str] = {}
        self._loaded_models: Dict[str, Dict[str, Any]] = {}
        self._last_refresh = 0.0
        self._model_active: Dict[int, int] = {}
        self._active_request_ids: Dict[str, int] = {}
        self._lock = threading.RLock()
        self._provider_config = self._load_provider_config()

    def _load_provider_config(self) -> Dict[str, Any]:
        try:
            if self._db:
                config = self._db.get_provider_config(self.provider_id)
                return config if config else {}
            from logos.dbutils.dbmanager import DBManager
            with DBManager() as db:
                config = db.get_provider_config(self.provider_id)
                return config if config else {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] Failed to load provider config: %s", self.name, exc)
            return {}

    def get_config_value(self, model_id: int, config_key: str, default_value: Any) -> Any:
        if self._provider_config.get(config_key) is not None:
            return self._provider_config[config_key]
        return default_value

    def register_model(self, model_id: int, model_name: str) -> None:
        with self._lock:
            self._model_id_to_name[model_id] = model_name
            self._model_active.setdefault(model_id, 0)

    def refresh_data(self) -> None:
        now = time.time()
        with self._lock:
            if now - self._last_refresh < self.refresh_interval:
                return

        runtime_models = self._fetch_runtime_models()
        if runtime_models is not None:
            with self._lock:
                self._loaded_models = runtime_models
                self._last_refresh = now
            return

        data = self._fetch_ps_data()
        if data is None:
            return

        models = data.get("models", [])
        with self._lock:
            self._loaded_models = {}
            for model in models:
                model_name = model.get("name") or model.get("model")
                if model_name:
                    self._loaded_models[model_name] = {
                        "size_vram": model.get("size_vram", 0),
                        "expires_at": self._parse_timestamp(model.get("expires_at")),
                    }
            self._last_refresh = now

    def _fetch_runtime_models(self) -> Dict[str, Dict[str, Any]] | None:
        if self._runtime_registry is None:
            return None
        snap = self._runtime_registry.peek_runtime_snapshot(self.provider_id)
        if not snap:
            return None
        runtime = snap.get("runtime") or {}
        lanes = runtime.get("lanes") or []
        if not isinstance(lanes, list):
            return None
        loaded_models: Dict[str, Dict[str, Any]] = {}
        for lane in lanes:
            if not isinstance(lane, dict):
                continue
            for model in lane.get("loaded_models") or []:
                name = model.get("name") or lane.get("model")
                if not name:
                    continue
                expires_at = self._parse_timestamp(model.get("expires_at"))
                loaded_models[name] = {
                    "size_vram": int((lane.get("effective_vram_mb") or 0) * 1024 * 1024),
                    "expires_at": expires_at,
                }
        return loaded_models

    def _fetch_ps_data(self) -> Optional[Dict[str, Any]]:
        if not self.base_url:
            return None
        try:
            headers = self._get_auth_headers_for_ps(self.provider_id)
            response = requests.get(f"{self.base_url}/api/ps", headers=headers if headers else None, timeout=5.0)
            if response.status_code == 200:
                return response.json()
        except requests.exceptions.RequestException as exc:
            logger.warning("[%s] Failed to query /api/ps: %s", self.name, exc)
        return None

    def _get_auth_headers_for_ps(self, provider_id: int) -> Dict[str, str] | None:
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
            if not auth_name or not auth_format or not api_key:
                return {}
            return {auth_name: auth_format.format(api_key)}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to resolve /api/ps auth for %s: %s", provider_id, exc)
            return {}

    def _get_runtime_parallel_capacity(self, model_id: int) -> tuple[int | None, str]:
        if self._runtime_registry is None:
            return None, "config"

        snap = self._runtime_registry.peek_runtime_snapshot(self.provider_id)
        if not snap:
            return None, "config"

        runtime = snap.get("runtime") or {}
        lanes = runtime.get("lanes") or []
        if not isinstance(lanes, list):
            return None, "config"

        model_name = self._model_id_to_name.get(model_id)
        if not model_name:
            return None, "config"

        total_capacity = 0
        matched_lanes = 0
        for lane in lanes:
            if not isinstance(lane, dict):
                continue
            if lane.get("model") != model_name:
                continue
            if lane.get("runtime_state") in {"stopped", "error"}:
                continue

            matched_lanes += 1
            capacity_hint = lane.get("num_parallel")
            if bool(lane.get("vllm")) and not capacity_hint:
                lane_config = lane.get("lane_config")
                if isinstance(lane_config, dict):
                    # vLLM runtime status reports num_parallel=0 because concurrency is continuous,
                    # but the saved lane config still provides the scheduling capacity hint.
                    capacity_hint = lane_config.get("num_parallel")

            try:
                capacity = int(capacity_hint) if capacity_hint is not None else 0
            except (TypeError, ValueError):
                capacity = 0

            if capacity > 0:
                total_capacity += capacity

        if matched_lanes == 0 or total_capacity <= 0:
            return None, "config"
        return max(1, total_capacity), "runtime"

    def get_parallel_capacity(self, model_id: int) -> tuple[int, str]:
        runtime_capacity, source = self._get_runtime_parallel_capacity(model_id)
        if runtime_capacity is not None:
            return runtime_capacity, source
        configured = self.get_config_value(model_id, "parallel_capacity", self.DEFAULT_PARALLEL_CAPACITY)
        return int(configured), "config"

    def get_model_status(self, model_id: int) -> ModelStatus:
        self.refresh_data()
        model_name = self._model_id_to_name.get(model_id)
        if not model_name:
            raise ValueError(f"Model {model_id} not registered with provider '{self.name}'")

        with self._lock:
            loaded_info = self._loaded_models.get(model_name)
            queue_state = self.queue_manager.get_state(model_id, self.provider_id)
            active_requests = self._model_active.get(model_id, 0)
            is_loaded = bool(loaded_info)
            vram_mb = int((loaded_info or {}).get("size_vram", 0) // (1024 * 1024))
            expires_at = (loaded_info or {}).get("expires_at")
            return ModelStatus(
                model_id=model_id,
                provider_id=self.provider_id,
                is_loaded=is_loaded,
                vram_mb=vram_mb,
                expires_at=expires_at,
                queue_state=queue_state,
                active_requests=active_requests,
                provider_type="logosnode",
            )

    def get_capacity_info(self) -> OllamaCapacity:
        self.refresh_data()
        runtime_free_mb = None
        if self._runtime_registry is not None:
            snap = self._runtime_registry.peek_runtime_snapshot(self.provider_id)
            runtime = (snap or {}).get("runtime") or {}
            devices = runtime.get("devices") or {}
            if isinstance(devices, dict) and bool(devices.get("nvidia_smi_available")):
                runtime_free_mb = int(devices.get("free_memory_mb", 0) or 0)
        with self._lock:
            total_used_bytes = sum(info["size_vram"] for info in self._loaded_models.values())
            used_vram_mb = total_used_bytes // (1024 * 1024)
            available_vram_mb = runtime_free_mb if runtime_free_mb is not None else max(0, self.total_vram_mb - used_vram_mb)
            return OllamaCapacity(
                available_vram_mb=available_vram_mb,
                total_vram_mb=self.total_vram_mb,
                loaded_models=list(self._loaded_models.keys()),
            )

    def increment_active(self, model_id: int, request_id: Optional[str] = None) -> None:
        with self._lock:
            if request_id:
                if request_id in self._active_request_ids:
                    return
                self._active_request_ids[request_id] = model_id
            self._model_active[model_id] = self._model_active.get(model_id, 0) + 1

    def decrement_active(self, model_id: int, reuse_slot: bool = False, request_id: Optional[str] = None) -> None:
        if request_id:
            with self._lock:
                mapped_model = self._active_request_ids.pop(request_id, None)
                if mapped_model is not None:
                    model_id = mapped_model
        if reuse_slot:
            return
        with self._lock:
            current_active = self._model_active.get(model_id, 0)
            self._model_active[model_id] = max(0, current_active - 1)

    def try_reserve_capacity(self, model_id: int, request_id: str) -> bool:
        with self._lock:
            current_active = self._model_active.get(model_id, 0)
            max_capacity, _source = self.get_parallel_capacity(model_id)
            if current_active < max_capacity:
                if request_id in self._active_request_ids:
                    return True
                self._active_request_ids[request_id] = model_id
                self._model_active[model_id] = current_active + 1
                return True
            return False

    def track_active_request(self, request_id: str, model_id: int, increment_active: bool) -> None:
        with self._lock:
            if request_id in self._active_request_ids:
                return
            self._active_request_ids[request_id] = model_id
            if increment_active:
                self._model_active[model_id] = self._model_active.get(model_id, 0) + 1

    def get_active_count(self, model_id: int) -> int:
        with self._lock:
            return self._model_active.get(model_id, 0)

    def get_debug_state(self) -> Dict[int, Dict[str, Any]]:
        with self._lock:
            models = {}
            for model_id, model_name in self._model_id_to_name.items():
                max_capacity, capacity_source = self.get_parallel_capacity(model_id)
                queue_state = self.queue_manager.get_state(model_id, self.provider_id)
                models[model_id] = {
                    "model_name": model_name,
                    "active": self._model_active.get(model_id, 0),
                    "max_capacity": max_capacity,
                    "capacity_source": capacity_source,
                    "queue_depth": queue_state.total,
                    "loaded": model_name in self._loaded_models,
                }
            return models

    def _parse_timestamp(self, ts_str: Optional[str]) -> datetime:
        if not ts_str:
            return datetime.now(timezone.utc) + timedelta(hours=1)
        try:
            ts_clean = ts_str.rstrip("Z")
            dt = datetime.fromisoformat(ts_clean)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, AttributeError) as exc:
            logger.warning("[%s] Failed to parse timestamp '%s': %s", self.name, ts_str, exc)
            return datetime.now(timezone.utc) + timedelta(hours=1)
