"""logosnode Scheduling Data Facade."""

import logging
import threading
import time
from typing import Dict, Optional, Set

from logos.logosnode_registry import LogosNodeRuntimeRegistry

from .models import ModelStatus, OllamaCapacity, RequestMetrics
from .providers.logosnode_provider import LogosNodeDataProvider

logger = logging.getLogger(__name__)


class LogosNodeSchedulingDataFacade:
    """Facade for accessing logosnode scheduling data with strong typing."""

    def __init__(self, queue_manager, db_manager=None, runtime_registry: LogosNodeRuntimeRegistry | None = None):
        self.queue_manager = queue_manager
        self._db = db_manager
        self._runtime_registry = runtime_registry
        self._providers: Dict[int, LogosNodeDataProvider] = {}
        self._model_to_provider: Dict[int, Set[int]] = {}
        self._request_tracking: Dict[str, Dict] = {}
        self._lock = threading.RLock()
        logger.info("LogosNodeSchedulingDataFacade initialized")

    def register_model(
        self,
        model_id: int,
        provider_name: str,
        logosnode_admin_url: Optional[str] = None,
        model_name: Optional[str] = None,
        total_vram_mb: Optional[int] = None,
        refresh_interval: float = 5.0,
        provider_id: Optional[int] = None,
    ) -> None:
        if model_name is None and total_vram_mb is None:
            raise ValueError("model_name and total_vram_mb are required")
        if provider_id is None:
            raise ValueError(f"provider_id is required for model {model_id} / provider '{provider_name}'")

        with self._lock:
            provider_key = int(provider_id)
            if provider_key not in self._providers:
                provider = LogosNodeDataProvider(
                    name=provider_name,
                    base_url=logosnode_admin_url,
                    total_vram_mb=int(total_vram_mb) if total_vram_mb is not None else 0,
                    queue_manager=self.queue_manager,
                    refresh_interval=refresh_interval,
                    provider_id=provider_id,
                    db_manager=self._db,
                    runtime_registry=self._runtime_registry,
                )
                self._providers[provider_key] = provider
            provider = self._providers[provider_key]
            provider.register_model(model_id, model_name)
            current = self._model_to_provider.get(model_id, set())
            current.add(provider_key)
            self._model_to_provider[model_id] = current
            logger.info("Registered model %s as '%s' with logosnode provider '%s'", model_id, model_name, provider_name)

    def get_model_status(self, model_id: int, provider_id: Optional[int] = None) -> ModelStatus:
        provider = self._get_provider_for_model(model_id, provider_id)
        return provider.get_model_status(model_id)

    def get_capacity_info(self, provider_id: int) -> OllamaCapacity:
        if int(provider_id) not in self._providers:
            raise KeyError(f"Provider '{provider_id}' not found")
        return self._providers[int(provider_id)].get_capacity_info()

    def debug_state(self) -> Dict[str, Dict]:
        with self._lock:
            providers: Dict[str, Dict] = {}
            for provider_id, provider in self._providers.items():
                providers[str(provider_id)] = {
                    "name": provider.name,
                    "base_url": provider.base_url,
                    "models": provider.get_debug_state(),
                }
            now = time.time()
            tracked_requests: Dict[str, Dict] = {}
            for request_id, data in self._request_tracking.items():
                arrival_time = data.get("arrival_time")
                processing_start = data.get("processing_start_time")
                tracked_requests[request_id] = {
                    "model_id": data.get("model_id"),
                    "provider_id": data.get("provider_id"),
                    "priority": data.get("priority"),
                    "arrival_age_s": (now - arrival_time) if arrival_time else None,
                    "processing_age_s": (now - processing_start) if processing_start else None,
                }
            return {"providers": providers, "tracked_requests": tracked_requests}

    def on_request_start(self, request_id: str, model_id: int, provider_id: int, priority: str = "normal") -> None:
        with self._lock:
            provider = self._get_provider_for_model(model_id, provider_id)
            status = provider.get_model_status(model_id)
            self._request_tracking[request_id] = {
                "model_id": model_id,
                "provider_id": int(provider_id),
                "arrival_time": time.time(),
                "priority": priority,
                "queue_depth_at_arrival": status.queue_depth,
            }

    def on_request_begin_processing(self, request_id: str, increment_active: bool = True, provider_id: Optional[int] = None) -> None:
        with self._lock:
            if request_id not in self._request_tracking:
                raise KeyError(f"Request {request_id} not found in tracking")
            tracking_data = self._request_tracking[request_id]
            model_id = tracking_data["model_id"]
            provider_id = provider_id if provider_id is not None else tracking_data.get("provider_id")
            provider = self._get_provider_for_model(model_id, provider_id)
            provider.track_active_request(request_id=request_id, model_id=model_id, increment_active=increment_active)
            tracking_data["processing_start_time"] = time.time()

    def on_request_complete(self, request_id: str, was_cold_start: bool, duration_ms: float, reuse_slot: bool = False, provider_id: Optional[int] = None) -> RequestMetrics:
        with self._lock:
            if request_id not in self._request_tracking:
                raise KeyError(f"Request {request_id} not found in tracking")
            tracking_data = self._request_tracking.pop(request_id)
            model_id = tracking_data["model_id"]
            provider_id = provider_id if provider_id is not None else tracking_data.get("provider_id")
            queue_wait_ms = (time.time() - tracking_data["arrival_time"]) * 1000 - duration_ms
            provider = self._get_provider_for_model(model_id, provider_id)
            provider.decrement_active(model_id, reuse_slot=reuse_slot, request_id=request_id)
            return RequestMetrics(
                queue_wait_ms=max(0, queue_wait_ms),
                was_cold_start=was_cold_start,
                duration_ms=duration_ms,
                queue_depth_at_arrival=tracking_data["queue_depth_at_arrival"],
                priority=tracking_data["priority"],
            )

    def try_reserve_capacity(self, model_id: int, provider_id: int, request_id: str) -> bool:
        provider = self._get_provider_for_model(model_id, provider_id)
        return provider.try_reserve_capacity(model_id, request_id)

    def _get_provider_for_model(self, model_id: int, provider_id: Optional[int] = None) -> LogosNodeDataProvider:
        with self._lock:
            if provider_id is not None:
                provider = self._providers.get(int(provider_id))
                if provider is None:
                    raise KeyError(f"Provider '{provider_id}' not found")
                return provider
            provider_ids = self._model_to_provider.get(model_id)
            if not provider_ids:
                raise KeyError(f"Model '{model_id}' is not registered")
            return self._providers[next(iter(provider_ids))]
