"""Scheduling data provider for logosnode deployments."""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import requests

from logos.logosnode_registry import LogosNodeRuntimeRegistry, _lane_ttft_p95_seconds, _lane_metric_float

from ..models import (
    ModelStatus,
    OllamaCapacity,
    QueueStatePerPriority,
    LaneSchedulerSignals,
    ModelSchedulerView,
    ModelProfile,
)

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
        self._db_parallel_ceiling: Dict[int, int] = {}
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

    def update_registration(self, *, name: str, base_url: Optional[str], total_vram_mb: int) -> None:
        with self._lock:
            self.name = name
            self.base_url = base_url.rstrip("/") if base_url else None
            self.total_vram_mb = int(total_vram_mb)
            self._provider_config = self._load_provider_config()

    def set_registered_models(self, models: Dict[int, str]) -> None:
        with self._lock:
            desired = {int(model_id): model_name for model_id, model_name in models.items()}
            removed_ids = set(self._model_id_to_name) - set(desired)
            self._model_id_to_name = desired
            for model_id in removed_ids:
                self._model_active.pop(model_id, None)
            for model_id in desired:
                self._model_active.setdefault(model_id, 0)
            stale_request_ids = [
                request_id
                for request_id, model_id in self._active_request_ids.items()
                if model_id not in desired
            ]
            for request_id in stale_request_ids:
                self._active_request_ids.pop(request_id, None)

    def set_db_parallel_ceilings(self, ceilings: Dict[int, int]) -> None:
        """Set DB-configured parallel ceilings per model_id."""
        with self._lock:
            self._db_parallel_ceiling = dict(ceilings)

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

    @staticmethod
    def _sample_epoch(timestamp: Any) -> float | None:
        if not isinstance(timestamp, str) or not timestamp.strip():
            return None
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()

    @staticmethod
    def _counter_rate(points: list[tuple[float, dict[str, Any]]], key: str) -> float | None:
        if len(points) < 2:
            return None

        start_value: float | None = None
        start_ts: float | None = None
        end_value: float | None = None
        end_ts: float | None = None

        for ts, signal in points:
            raw = signal.get(key)
            if raw is None:
                continue
            try:
                numeric = float(raw)
            except (TypeError, ValueError):
                continue
            if start_value is None:
                start_value = numeric
                start_ts = ts
            end_value = numeric
            end_ts = ts

        if start_value is None or end_value is None or start_ts is None or end_ts is None:
            return None
        elapsed = end_ts - start_ts
        if elapsed <= 0 or end_value < start_value:
            return None
        return (end_value - start_value) / elapsed

    def _get_recent_model_scheduler_signals(self, model_id: int) -> Dict[str, Any] | None:
        if self._runtime_registry is None or not hasattr(self._runtime_registry, "peek_recent_samples"):
            return None

        model_name = self._model_id_to_name.get(model_id)
        if not model_name:
            return None

        points: list[tuple[float, dict[str, Any]]] = []
        for sample in self._runtime_registry.peek_recent_samples(self.provider_id):
            if not isinstance(sample, dict):
                continue
            scheduler_signals = sample.get("scheduler_signals")
            if not isinstance(scheduler_signals, dict):
                continue
            models = scheduler_signals.get("models")
            if not isinstance(models, dict):
                continue
            signal = models.get(model_name)
            if not isinstance(signal, dict):
                continue
            sample_ts = self._sample_epoch(sample.get("timestamp"))
            if sample_ts is None:
                continue
            points.append((sample_ts, signal))

        if not points:
            return None

        latest_ts, latest_signal = points[-1]
        first_ts = points[0][0]
        recent_window_seconds = max(0.0, latest_ts - first_ts)

        result = dict(latest_signal)
        result["sample_count"] = len(points)
        result["recent_window_seconds"] = recent_window_seconds
        result["queue_waiting_peak"] = max(float(signal.get("queue_waiting_current") or 0.0) for _, signal in points)
        result["requests_running_peak"] = max(float(signal.get("requests_running_current") or 0.0) for _, signal in points)
        result["active_requests_peak"] = max(int(signal.get("active_requests") or 0) for _, signal in points)

        prompt_rate = self._counter_rate(points, "prompt_tokens_total")
        if prompt_rate is not None:
            result["prompt_tokens_per_second"] = prompt_rate

        generation_rate = self._counter_rate(points, "generation_tokens_total")
        if generation_rate is not None:
            result["generation_tokens_per_second"] = generation_rate

        return result

    def get_runtime_debug_state(self) -> Dict[str, Any]:
        if self._runtime_registry is None:
            return {}

        snapshot = self._runtime_registry.peek_runtime_snapshot(self.provider_id)
        if not snapshot:
            return {}

        provider_signals: Dict[str, Any] = {}
        sample_count = 0
        samples = (
            self._runtime_registry.peek_recent_samples(self.provider_id)
            if hasattr(self._runtime_registry, "peek_recent_samples")
            else []
        )
        if samples:
            sample_count = len(samples)
            latest = samples[-1]
            scheduler_signals = latest.get("scheduler_signals")
            if isinstance(scheduler_signals, dict):
                provider_signals = scheduler_signals.get("provider") or {}

        return {
            "last_heartbeat": snapshot.get("last_heartbeat"),
            "capabilities_models": snapshot.get("capabilities_models") or [],
            "recent_sample_count": sample_count,
            "provider_signals": provider_signals,
        }

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
            is_vllm = bool(lane.get("vllm"))
            capacity_hint = lane.get("num_parallel")
            if is_vllm and not capacity_hint:
                # vLLM uses continuous batching — num_parallel=0 means unlimited.
                # Default to 256 so the scheduler doesn't artificially
                # serialize requests.  The DB parallel column is the real
                # ceiling if one is needed.
                capacity_hint = 256

            try:
                capacity = int(capacity_hint) if capacity_hint is not None else 0
            except (TypeError, ValueError):
                capacity = 0

            # Apply oversubscription for vLLM lanes: the reported
            # num_parallel is based on worst-case full-context requests,
            # but real requests typically use a fraction of context.
            if is_vllm and capacity > 0 and capacity < 256:
                capacity = capacity * self.VLLM_CONCURRENCY_OVERSUBSCRIPTION

            if capacity > 0:
                total_capacity += capacity

        if matched_lanes == 0 or total_capacity <= 0:
            return None, "config"
        return max(1, total_capacity), "runtime"

    def get_parallel_capacity(self, model_id: int) -> tuple[int, str]:
        configured = self.get_config_value(model_id, "parallel_capacity", None)
        if configured is not None and int(configured) != self.DEFAULT_PARALLEL_CAPACITY:
            capacity, source = int(configured), "config"
        else:
            runtime_capacity, source = self._get_runtime_parallel_capacity(model_id)
            if runtime_capacity is not None:
                capacity, source = runtime_capacity, source
            elif configured is not None:
                capacity, source = int(configured), "config"
            else:
                capacity, source = self.DEFAULT_PARALLEL_CAPACITY, "default"

        # DB parallel ceiling: hard ceiling from the models table
        db_ceiling = self._db_parallel_ceiling.get(model_id)
        if db_ceiling is not None and db_ceiling > 0:
            if capacity > db_ceiling:
                logger.debug(
                    "Capping parallel capacity for model %d from %d (%s) to %d (db_ceiling)",
                    model_id, capacity, source, db_ceiling,
                )
                return db_ceiling, "db_ceiling"
        return capacity, source

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
        runtime_total_mb = None
        if self._runtime_registry is not None:
            snap = self._runtime_registry.peek_runtime_snapshot(self.provider_id)
            runtime = (snap or {}).get("runtime") or {}
            devices = runtime.get("devices") or {}
            if isinstance(devices, dict) and bool(devices.get("nvidia_smi_available")):
                runtime_free_mb = int(devices.get("free_memory_mb", 0) or 0)
                runtime_total_mb = int(devices.get("total_memory_mb", 0) or 0)
        with self._lock:
            total_used_bytes = sum(info["size_vram"] for info in self._loaded_models.values())
            used_vram_mb = total_used_bytes // (1024 * 1024)
            total_vram_mb = runtime_total_mb if runtime_total_mb is not None and runtime_total_mb > 0 else self.total_vram_mb
            available_vram_mb = runtime_free_mb if runtime_free_mb is not None else max(0, total_vram_mb - used_vram_mb)
            return OllamaCapacity(
                available_vram_mb=available_vram_mb,
                total_vram_mb=total_vram_mb,
                loaded_models=list(self._loaded_models.keys()),
            )

    # ------------------------------------------------------------------
    # Scheduler-view and lane-signal methods (Phase 1.2)
    # ------------------------------------------------------------------

    def _build_lane_signal(self, lane: Dict[str, Any]) -> LaneSchedulerSignals:
        """Construct a LaneSchedulerSignals from a raw lane dict in the runtime snapshot."""
        backend_metrics = lane.get("backend_metrics") if isinstance(lane.get("backend_metrics"), dict) else {}
        lane_config = lane.get("lane_config") if isinstance(lane.get("lane_config"), dict) else {}
        vllm_config = lane_config.get("vllm_config") if isinstance(lane_config.get("vllm_config"), dict) else {}
        is_vllm = bool(lane.get("vllm"))
        gpu_cache_usage_percent = backend_metrics.get("gpu_cache_usage_percent")
        if gpu_cache_usage_percent is None:
            gpu_cache_usage_percent = backend_metrics.get("gpu_cache_usage_perc")

        return LaneSchedulerSignals(
            lane_id=str(lane.get("lane_id", "")),
            model_name=str(lane.get("model", "")),
            runtime_state=str(lane.get("runtime_state", "error")),
            sleep_state=str(lane.get("sleep_state", "unsupported")),
            is_vllm=is_vllm,
            active_requests=int(lane.get("active_requests", 0) or 0),
            queue_waiting=_lane_metric_float(backend_metrics.get("queue_waiting")),
            requests_running=_lane_metric_float(backend_metrics.get("requests_running"))
            if is_vllm
            else float(int(lane.get("active_requests", 0) or 0)),
            gpu_cache_usage_percent=(
                _lane_metric_float(gpu_cache_usage_percent)
                if is_vllm and gpu_cache_usage_percent is not None
                else None
            ),
            ttft_p95_seconds=_lane_ttft_p95_seconds(backend_metrics),
            effective_vram_mb=float(lane.get("effective_vram_mb", 0.0) or 0.0),
            num_parallel=int(lane.get("num_parallel", 0) or 0),
            gpu_memory_utilization=(
                _lane_metric_float(vllm_config.get("gpu_memory_utilization"))
                if is_vllm and vllm_config.get("gpu_memory_utilization") is not None
                else None
            ),
            tensor_parallel_size=(
                int(vllm_config.get("tensor_parallel_size", 0) or 0)
                if is_vllm and vllm_config.get("tensor_parallel_size") is not None
                else None
            ),
            gpu_devices=str(
                lane_config.get("gpu_devices")
                or lane.get("gpu_devices")
                or lane.get("effective_gpu_devices")
                or ""
            ) or None,
        )

    def get_model_scheduler_view(self, model_id: int) -> Optional[ModelSchedulerView]:
        """Build aggregated scheduler view for one model from runtime snapshot.

        Reads lanes from latest_runtime, filters by model name matching model_id,
        constructs LaneSchedulerSignals per lane, aggregates into ModelSchedulerView.
        Returns None if the model is not registered or no runtime data available.
        """
        self.refresh_data()

        model_name = self._model_id_to_name.get(model_id)
        if not model_name:
            return None

        if self._runtime_registry is None:
            return None

        snap = self._runtime_registry.peek_runtime_snapshot(self.provider_id)
        if not snap:
            return None

        runtime = snap.get("runtime") or {}
        lanes = runtime.get("lanes") or []
        if not isinstance(lanes, list):
            return None

        matching_signals: List[LaneSchedulerSignals] = []
        for lane in lanes:
            if not isinstance(lane, dict):
                continue
            if lane.get("model") != model_name:
                continue
            if lane.get("runtime_state") in {"stopped", "error"}:
                # Include stopped/error lanes in signals but they'll rank lowest
                # in warmth ordering — allows planner to see them
                pass
            matching_signals.append(self._build_lane_signal(lane))

        if not matching_signals:
            return None

        runtime_states = [s.runtime_state for s in matching_signals]
        sleep_states = [s.sleep_state for s in matching_signals]
        best_lane_state = ModelSchedulerView.warmest_state(runtime_states)
        best_sleep_state = ModelSchedulerView.warmest_sleep(sleep_states)

        is_loaded = best_lane_state in ("loaded", "running")

        aggregate_active = sum(s.active_requests for s in matching_signals)
        aggregate_queue = sum(s.queue_waiting for s in matching_signals)

        # Best-case TTFT: minimum ttft_p95 among loaded/running lanes (non-zero)
        loaded_ttfts = [
            s.ttft_p95_seconds
            for s in matching_signals
            if s.runtime_state in ("loaded", "running") and s.ttft_p95_seconds > 0
        ]
        warmest_ttft = min(loaded_ttfts) if loaded_ttfts else 0.0

        # Max GPU cache pressure across lanes (vLLM only)
        cache_values = [
            s.gpu_cache_usage_percent
            for s in matching_signals
            if s.gpu_cache_usage_percent is not None
        ]
        gpu_cache_max = max(cache_values) if cache_values else None

        return ModelSchedulerView(
            model_id=model_id,
            model_name=model_name,
            provider_id=self.provider_id,
            is_loaded=is_loaded,
            best_lane_state=best_lane_state,
            best_sleep_state=best_sleep_state,
            aggregate_active_requests=aggregate_active,
            aggregate_queue_waiting=aggregate_queue,
            warmest_ttft_p95_seconds=warmest_ttft,
            gpu_cache_pressure_max=gpu_cache_max,
            lanes=matching_signals,
        )

    def get_all_lane_signals(self) -> List[LaneSchedulerSignals]:
        """Return signals for every lane regardless of model. Used by capacity planner."""
        self.refresh_data()

        if self._runtime_registry is None:
            return []

        snap = self._runtime_registry.peek_runtime_snapshot(self.provider_id)
        if not snap:
            return []

        runtime = snap.get("runtime") or {}
        lanes = runtime.get("lanes") or []
        if not isinstance(lanes, list):
            return []

        return [self._build_lane_signal(lane) for lane in lanes if isinstance(lane, dict)]

    def get_model_profiles(self) -> Dict[str, ModelProfile]:
        """Read model profiles from runtime snapshot's model_profiles section."""
        if self._runtime_registry is None:
            return {}

        snap = self._runtime_registry.peek_runtime_snapshot(self.provider_id)
        if not snap:
            return {}

        runtime = snap.get("runtime") or {}
        raw_profiles = runtime.get("model_profiles") or {}
        raw_lanes = runtime.get("lanes") or []
        if not isinstance(raw_profiles, dict):
            return {}

        profiles: Dict[str, ModelProfile] = {}
        for model_name, data in raw_profiles.items():
            if not isinstance(data, dict):
                continue
            profiles[str(model_name)] = ModelProfile(
                model_name=str(model_name),
                loaded_vram_mb=data.get("loaded_vram_mb"),
                sleeping_residual_mb=data.get("sleeping_residual_mb"),
                disk_size_bytes=data.get("disk_size_bytes"),
                base_residency_mb=data.get("base_residency_mb"),
                kv_budget_mb=data.get("kv_budget_mb"),
                engine=data.get("engine"),
                observed_gpu_memory_utilization=data.get("observed_gpu_memory_utilization"),
                min_gpu_memory_utilization_to_load=data.get("min_gpu_memory_utilization_to_load"),
                tensor_parallel_size=data.get("tensor_parallel_size"),
                kv_per_token_bytes=data.get("kv_per_token_bytes"),
                max_context_length=data.get("max_context_length"),
                measurement_count=int(data.get("measurement_count", 0) or 0),
                last_measured_epoch=float(data.get("last_measured_epoch", 0.0) or 0.0),
                residency_source=data.get("residency_source"),
            )

        if isinstance(raw_lanes, list):
            for lane in raw_lanes:
                if not isinstance(lane, dict):
                    continue
                model_name = str(lane.get("model", "")).strip()
                if not model_name:
                    continue
                profile = profiles.get(model_name)
                if profile is None:
                    continue
                lane_config = lane.get("lane_config") if isinstance(lane.get("lane_config"), dict) else {}
                vllm_config = lane_config.get("vllm_config") if isinstance(lane_config.get("vllm_config"), dict) else {}
                if profile.engine is None:
                    profile.engine = "vllm" if bool(lane.get("vllm")) else "ollama"
                if profile.observed_gpu_memory_utilization is None and vllm_config.get("gpu_memory_utilization") is not None:
                    profile.observed_gpu_memory_utilization = float(vllm_config.get("gpu_memory_utilization"))
                if profile.tensor_parallel_size is None and vllm_config.get("tensor_parallel_size") is not None:
                    profile.tensor_parallel_size = int(vllm_config.get("tensor_parallel_size") or 0)

        if self._runtime_registry is not None and hasattr(self._runtime_registry, "peek_recent_samples"):
            for sample in reversed(self._runtime_registry.peek_recent_samples(self.provider_id)):
                if not isinstance(sample, dict):
                    continue
                runtime_payload = sample.get("runtime_payload")
                if not isinstance(runtime_payload, dict):
                    continue
                lanes = runtime_payload.get("lanes")
                if not isinstance(lanes, list):
                    continue
                for lane in lanes:
                    if not isinstance(lane, dict):
                        continue
                    model_name = str(lane.get("model", "")).strip()
                    if not model_name:
                        continue
                    profile = profiles.get(model_name)
                    if profile is None:
                        continue
                    lane_config = lane.get("lane_config") if isinstance(lane.get("lane_config"), dict) else {}
                    vllm_config = lane_config.get("vllm_config") if isinstance(lane_config.get("vllm_config"), dict) else {}
                    if profile.engine is None:
                        profile.engine = "vllm" if bool(lane.get("vllm")) else "ollama"
                    if profile.observed_gpu_memory_utilization is None and vllm_config.get("gpu_memory_utilization") is not None:
                        profile.observed_gpu_memory_utilization = float(vllm_config.get("gpu_memory_utilization"))
                    if profile.tensor_parallel_size is None and vllm_config.get("tensor_parallel_size") is not None:
                        profile.tensor_parallel_size = int(vllm_config.get("tensor_parallel_size") or 0)
        return profiles

    def get_worker_capabilities(self) -> List[str]:
        """Return the list of models this worker declares it can serve."""
        if self._runtime_registry is None:
            return []
        snap = self._runtime_registry.peek_runtime_snapshot(self.provider_id)
        if not snap:
            return []
        caps = snap.get("capabilities_models")
        return list(caps) if caps else []

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

    # Maximum backend queue_waiting before we refuse new reservations.
    # Prevents piling requests on an already-backlogged vLLM process.
    # Raised from 2→8: with oversubscription enabled, vLLM's internal
    # scheduler (PagedAttention) handles queuing efficiently; we only
    # need to back off when the engine is genuinely saturated.
    BACKEND_QUEUE_PRESSURE_THRESHOLD = 8

    # vLLM reports "Maximum concurrency for N tokens per request" assuming
    # every request fills the entire context window.  In practice, requests
    # use a fraction of context (e.g. 200/4096 = 5%), so the KV cache can
    # safely hold many more concurrent sequences.  This multiplier is
    # applied to the vLLM-reported num_parallel to allow higher throughput
    # while still letting vLLM's own scheduler handle fine-grained KV
    # admission via PagedAttention preemption.
    VLLM_CONCURRENCY_OVERSUBSCRIPTION = 3

    def try_reserve_capacity(self, model_id: int, request_id: str) -> bool:
        with self._lock:
            # Reject if no lane is ready (loaded/running) — requests for sleeping
            # or unloaded models should go to the scheduler queue instead.
            if not self._is_model_lane_ready(model_id):
                logger.debug(
                    "Refusing reservation for model %d: no ready lane (sleeping/not loaded)",
                    model_id,
                )
                return False
            current_active = self._model_active.get(model_id, 0)
            max_capacity, _source = self.get_parallel_capacity(model_id)
            if current_active < max_capacity:
                # Check backend queue pressure before accepting
                if self._backend_queue_exceeds_threshold(model_id):
                    logger.debug(
                        "Refusing reservation for model %d: backend queue pressure exceeds threshold",
                        model_id,
                    )
                    return False
                if request_id in self._active_request_ids:
                    return True
                self._active_request_ids[request_id] = model_id
                self._model_active[model_id] = current_active + 1
                return True
            return False

    def _is_model_lane_ready(self, model_id: int) -> bool:
        """Check if at least one lane for this model is in a ready state (loaded/running)."""
        if self._runtime_registry is None:
            return True  # No runtime info, assume ready (backwards compat)
        model_name = self._model_id_to_name.get(model_id)
        if not model_name:
            return False
        snap = self._runtime_registry.peek_runtime_snapshot(self.provider_id)
        if not snap:
            return True  # No snapshot yet, assume ready
        lanes = ((snap.get("runtime") or {}).get("lanes") or [])
        for lane in lanes:
            if not isinstance(lane, dict):
                continue
            if lane.get("model") != model_name:
                continue
            if lane.get("runtime_state") in ("loaded", "running"):
                return True
        return False

    def _backend_queue_exceeds_threshold(self, model_id: int) -> bool:
        """Check if the backend (vLLM) queue_waiting exceeds the threshold."""
        if self._runtime_registry is None:
            return False
        model_name = self._model_id_to_name.get(model_id)
        if not model_name:
            return False
        snap = self._runtime_registry.peek_runtime_snapshot(self.provider_id)
        if not snap:
            return False
        lanes = ((snap.get("runtime") or {}).get("lanes") or [])
        for lane in lanes:
            if not isinstance(lane, dict):
                continue
            if lane.get("model") != model_name:
                continue
            if lane.get("runtime_state") in {"stopped", "error"}:
                continue
            backend = lane.get("backend_metrics")
            if isinstance(backend, dict):
                queue_waiting = float(backend.get("queue_waiting") or 0)
                if queue_waiting > self.BACKEND_QUEUE_PRESSURE_THRESHOLD:
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
                recent_signals = self._get_recent_model_scheduler_signals(model_id)
                models[model_id] = {
                    "model_name": model_name,
                    "active": self._model_active.get(model_id, 0),
                    "max_capacity": max_capacity,
                    "capacity_source": capacity_source,
                    "queue_depth": queue_state.total,
                    "loaded": model_name in self._loaded_models,
                    "scheduler_signals": recent_signals,
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
