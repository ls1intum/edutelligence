import asyncio
import hmac
import datetime
import json
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Dict, Set, Optional, Tuple
import grpc
from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from logos.auth import authenticate_logos_key
from logos.role_auth import require_logos_admin_key
from grpclocal import model_pb2_grpc
from grpclocal.grpc_server import LogosServicer
from logos.classification.classification_balancer import Balancer
from logos.classification.classification_manager import ClassificationManager
from logos.dbutils.dbmanager import DBManager
from logos.dbutils.types import Deployment, get_unique_models_from_deployments, normalize_provider_type
from logos.dbutils.dbmodules import JobStatus
from logos.dbutils.dbrequest import *
from logos.jobs.job_service import JobService, JobSubmission
from logos.responses import (
    get_client_ip,
    extract_model,
    request_setup,
    extract_token_usage
)
from logos.pipeline.pipeline import RequestPipeline, PipelineRequest
from logos.pipeline.fcfs_scheduler import FcfScheduler
from logos.pipeline.correcting_scheduler import ClassificationCorrectingScheduler
from logos.pipeline.executor import Executor, ExecutionResult
from logos.pipeline.context_resolver import ContextResolver
from logos.capacity.demand_tracker import DemandTracker
from logos.capacity.capacity_planner import CapacityPlanner
from logos.queue.priority_queue import PriorityQueueManager
from logos.sdi.logosnode_facade import LogosNodeSchedulingDataFacade
from logos.sdi.azure_facade import AzureSchedulingDataFacade
from logos.sdi.providers.azure_provider import extract_azure_deployment_name
from logos.logosnode_registry import (
    LogosNodeCommandError,
    LogosNodeOfflineError,
    LogosNodeSessionConflictError,
    LogosNodeRuntimeRegistry,
)
from logos.terminal_logging import MultiLineFormatter, UvicornAccessFilter, UvicornErrorFilter
from logos.monitoring.prometheus_metrics import metrics_response as _prometheus_metrics_response
from scripts import setup_proxy

_SERVER_START_TIME = int(time.time())

logger = logging.getLogger("LogosLogger")
_grpc_server = None
_background_tasks: Set[asyncio.Task] = set()
def _resolve_provider_name(provider_id: int) -> str:
    """Best-effort resolve a provider ID to its worker name."""
    snap = _logosnode_registry.peek_runtime_snapshot(provider_id)
    if snap:
        return snap.get("worker_id") or str(provider_id)
    return str(provider_id)


def _sync_logosnode_capabilities_to_db(provider_id: int, model_names: list[str]) -> None:
    """Callback: sync announced capabilities into DB tables."""
    pname = _resolve_provider_name(provider_id)
    try:
        with DBManager() as db:
            db.sync_logosnode_capabilities(provider_id, model_names)
        logger.info(
            "Synced %d capability model(s) to DB for provider %s",
            len(model_names), pname,
        )
    except Exception:
        logger.exception("Failed to sync capabilities to DB for provider %s", pname)


_logosnode_registry = LogosNodeRuntimeRegistry(
    on_capabilities_changed=_sync_logosnode_capabilities_to_db,
)
_demand_tracker: Optional[DemandTracker] = None
_capacity_planner: Optional[CapacityPlanner] = None


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return default


_LOGOSNODE_INFER_TIMEOUT_SECONDS = _env_int("LOGOSNODE_INFER_TIMEOUT_SECONDS", 120)
_LOGOSNODE_STREAM_TIMEOUT_SECONDS = _env_int(
    "LOGOSNODE_STREAM_TIMEOUT_SECONDS",
    _LOGOSNODE_INFER_TIMEOUT_SECONDS,
)
_LOGOSNODE_STATS_STALE_AFTER_SECONDS = _env_int("LOGOSNODE_STATS_STALE_AFTER_SECONDS", 30)


def _record_azure_rate_limits(
    scheduling_stats: Optional[Dict[str, Any]],
    headers: Dict[str, str],
) -> None:
    if not scheduling_stats or not headers:
        return
    request_id = scheduling_stats.get("request_id")
    if not request_id:
        return

    headers_lower = {k.lower(): v for k, v in headers.items()}
    remaining_requests = headers_lower.get("x-ratelimit-remaining-requests")
    remaining_tokens = headers_lower.get("x-ratelimit-remaining-tokens")

    provider_metrics = {}
    if remaining_requests is not None:
        try:
            provider_metrics["azure_rate_remaining_requests"] = int(remaining_requests)
        except (TypeError, ValueError):
            pass
    if remaining_tokens is not None:
        try:
            provider_metrics["azure_rate_remaining_tokens"] = int(remaining_tokens)
        except (TypeError, ValueError):
            pass

    if provider_metrics:
        _pipeline.record_provider_metrics(request_id, provider_metrics)


def _parse_iso_datetime(raw: Any) -> Optional[datetime.datetime]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_today_or_all_utc(day: str) -> bool:
    normalized = str(day or "").strip().lower()
    if normalized == "all":
        return True
    return normalized == datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def _logosnode_snapshot_is_connected(snapshot: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(snapshot, dict):
        return False
    last_heartbeat = _parse_iso_datetime(snapshot.get("last_heartbeat"))
    if last_heartbeat is None:
        return False
    now = datetime.datetime.now(datetime.timezone.utc)
    return (now - last_heartbeat) <= datetime.timedelta(seconds=_LOGOSNODE_STATS_STALE_AFTER_SECONDS)


def _normalize_loaded_models(lanes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for lane in lanes:
        if not isinstance(lane, dict):
            continue
        lane_model = str(lane.get("model") or "").strip()
        loaded_models = lane.get("loaded_models") or []
        if not isinstance(loaded_models, list):
            loaded_models = []
        for item in loaded_models:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or lane_model).strip()
            if not name:
                continue
            size_vram = int(item.get("size_vram") or 0)
            size_bytes = int(item.get("size") or 0)
            current = deduped.get(name)
            candidate = {
                "name": name,
                "size": size_bytes,
                "size_vram": size_vram,
            }
            if current is None or candidate["size_vram"] > current["size_vram"]:
                deduped[name] = candidate
    return sorted(deduped.values(), key=lambda item: item["name"].lower())


def _planner_model_alias(model_name: str) -> str:
    """Return the planner/worker-safe alias used in lane ids and logs."""
    return str(model_name or "").strip().replace("/", "_").replace(":", "_").replace(" ", "_")


def _resolve_requested_model_name(
    requested_name: str,
    available_model_names: list[str],
) -> Optional[str]:
    """Resolve user-supplied model ids to canonical DB model names.

    Accepts exact OpenAI-style model names as stored in the DB and also the
    planner-safe alias form where ``/``, ``:``, and spaces are rewritten as
    underscores. This lets users copy model ids from lane names or worker logs
    without breaking access-controlled model lookup.
    """
    requested = str(requested_name or "").strip()
    if not requested:
        return None

    alias_matches: set[str] = set()
    for raw_name in available_model_names:
        canonical = str(raw_name or "").strip()
        if not canonical:
            continue
        if canonical == requested:
            return canonical

        sanitized = _planner_model_alias(canonical)
        if requested in {sanitized, f"planner-{sanitized}"}:
            alias_matches.add(canonical)

    if len(alias_matches) == 1:
        return next(iter(alias_matches))
    return None


def _runtime_modes_for_lanes(lanes: list[dict[str, Any]]) -> list[str]:
    modes: set[str] = set()
    for lane in lanes:
        if not isinstance(lane, dict):
            continue
        modes.add("vllm" if bool(lane.get("vllm")) else "ollama")
    return sorted(modes)


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _merge_histogram_buckets(target: dict[str, float], source: Any) -> None:
    if not isinstance(source, dict):
        return
    for raw_bucket, raw_value in source.items():
        bucket = str(raw_bucket).strip()
        if not bucket:
            continue
        count = _safe_float(raw_value)
        if count is None or count < 0:
            continue
        target[bucket] = target.get(bucket, 0.0) + count


def _histogram_quantile_seconds(histogram: Any, quantile: float = 0.95) -> Optional[float]:
    if not isinstance(histogram, dict) or not histogram:
        return None

    buckets: list[tuple[float, float]] = []
    for raw_bucket, raw_count in histogram.items():
        count = _safe_float(raw_count)
        if count is None or count < 0:
            continue
        bucket_label = str(raw_bucket).strip()
        if not bucket_label:
            continue
        if bucket_label == "+Inf":
            upper_bound = float("inf")
        else:
            upper_bound = _safe_float(bucket_label)
            if upper_bound is None:
                continue
        buckets.append((upper_bound, count))

    if not buckets:
        return None

    buckets.sort(key=lambda item: item[0])
    total_count = max(count for _upper, count in buckets)
    if total_count <= 0:
        return None

    target = total_count * max(0.0, min(1.0, quantile))
    previous_upper = 0.0
    previous_count = 0.0

    for upper_bound, cumulative_count in buckets:
        if cumulative_count < target:
            previous_upper = 0.0 if upper_bound == float("inf") else upper_bound
            previous_count = cumulative_count
            continue

        if upper_bound == float("inf"):
            return previous_upper if previous_upper > 0 else None

        bucket_count = cumulative_count - previous_count
        if bucket_count <= 0:
            return upper_bound

        bucket_width = upper_bound - previous_upper
        if bucket_width <= 0:
            return upper_bound

        fraction = (target - previous_count) / bucket_count
        return previous_upper + (fraction * bucket_width)

    last_upper = buckets[-1][0]
    if last_upper == float("inf"):
        return previous_upper if previous_upper > 0 else None
    return last_upper


def _build_logosnode_scheduler_signals(runtime: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(runtime, dict):
        return {}

    devices = runtime.get("devices") if isinstance(runtime.get("devices"), dict) else {}
    capacity = runtime.get("capacity") if isinstance(runtime.get("capacity"), dict) else {}
    transport = runtime.get("transport") if isinstance(runtime.get("transport"), dict) else {}
    lanes = runtime.get("lanes") if isinstance(runtime.get("lanes"), list) else []

    provider_signals: Dict[str, Any] = {
        "timestamp": runtime.get("timestamp"),
        "transport_connected": bool(transport.get("connected", True)),
        "device_mode": devices.get("mode"),
        "nvidia_smi_available": bool(devices.get("nvidia_smi_available", False)),
        "device_count": len(devices.get("devices") or []) if isinstance(devices.get("devices"), list) else 0,
        "total_memory_mb": _safe_float(devices.get("total_memory_mb")),
        "used_memory_mb": _safe_float(devices.get("used_memory_mb")),
        "free_memory_mb": _safe_float(devices.get("free_memory_mb")),
        "lane_count": _safe_int(capacity.get("lane_count")) or len(lanes),
        "active_requests": _safe_int(capacity.get("active_requests")) or 0,
        "loaded_lane_count": _safe_int(capacity.get("loaded_lane_count")) or 0,
        "sleeping_lane_count": _safe_int(capacity.get("sleeping_lane_count")) or 0,
        "cold_lane_count": _safe_int(capacity.get("cold_lane_count")) or 0,
        "total_effective_vram_mb": _safe_float(capacity.get("total_effective_vram_mb")) or 0.0,
        "runtime_modes": _runtime_modes_for_lanes(lanes),
    }

    model_signals: dict[str, Dict[str, Any]] = {}
    lane_signals: dict[str, Dict[str, Any]] = {}

    def _ensure_model_entry(model_name: str) -> Dict[str, Any]:
        return model_signals.setdefault(
            model_name,
            {
                "lane_count": 0,
                "vllm_lane_count": 0,
                "ollama_lane_count": 0,
                "loaded_lane_count": 0,
                "running_lane_count": 0,
                "sleeping_lane_count": 0,
                "cold_lane_count": 0,
                "starting_lane_count": 0,
                "error_lane_count": 0,
                "active_requests": 0,
                "effective_vram_mb": 0.0,
                "reported_vram_mb": 0.0,
                "pid_vram_mb": 0.0,
                "device_vram_mb": 0.0,
                "queue_waiting_current": 0.0,
                "requests_running_current": 0.0,
                "prompt_tokens_total": None,
                "generation_tokens_total": None,
                "ttft_histogram": {},
                "ttft_p95_seconds": None,
                "gpu_cache_usage_percent_avg": None,
                "gpu_cache_usage_percent_max": None,
                "prefix_cache_hit_rate_avg": None,
                "_gpu_cache_usage_percent_sum": 0.0,
                "_gpu_cache_usage_percent_count": 0,
                "_prefix_cache_hit_rate_sum": 0.0,
                "_prefix_cache_hit_rate_count": 0,
            },
        )

    for lane in lanes:
        if not isinstance(lane, dict):
            continue

        model_name = str(lane.get("model") or "").strip()
        lane_id = str(lane.get("lane_id") or "").strip()
        runtime_state = str(lane.get("runtime_state") or "").strip()
        is_vllm = bool(lane.get("vllm"))
        active_requests = _safe_int(lane.get("active_requests")) or 0
        backend_metrics = lane.get("backend_metrics") if isinstance(lane.get("backend_metrics"), dict) else {}
        ttft_histogram = (
            backend_metrics.get("ttft_histogram")
            if isinstance(backend_metrics.get("ttft_histogram"), dict)
            else {}
        )
        lane_ttft_p95 = _histogram_quantile_seconds(ttft_histogram)

        lane_signal = {
            "model": model_name,
            "vllm": is_vllm,
            "runtime_state": runtime_state,
            "sleep_state": lane.get("sleep_state"),
            "active_requests": active_requests,
            "effective_vram_mb": _safe_float(lane.get("effective_vram_mb")) or 0.0,
            "reported_vram_mb": _safe_float(lane.get("reported_vram_mb")) or 0.0,
            "pid_vram_mb": _safe_float(lane.get("pid_vram_mb")) or 0.0,
            "device_vram_mb": _safe_float(lane.get("device_vram_mb")) or 0.0,
            "vram_source": lane.get("vram_source"),
            "queue_waiting": _safe_float(backend_metrics.get("queue_waiting")),
            "requests_running": _safe_float(backend_metrics.get("requests_running")),
            "gpu_cache_usage_percent": _safe_float(backend_metrics.get("gpu_cache_usage_percent")),
            "prefix_cache_hit_rate": _safe_float(backend_metrics.get("prefix_cache_hit_rate")),
            "prompt_tokens_total": _safe_float(backend_metrics.get("prompt_tokens_total")),
            "generation_tokens_total": _safe_float(backend_metrics.get("generation_tokens_total")),
            "ttft_histogram": ttft_histogram,
            "ttft_p95_seconds": lane_ttft_p95,
        }
        if lane_id:
            lane_signals[lane_id] = lane_signal

        if not model_name:
            continue

        entry = _ensure_model_entry(model_name)
        entry["lane_count"] += 1
        if is_vllm:
            entry["vllm_lane_count"] += 1
        else:
            entry["ollama_lane_count"] += 1

        if runtime_state == "loaded":
            entry["loaded_lane_count"] += 1
        elif runtime_state == "running":
            entry["running_lane_count"] += 1
        elif runtime_state == "sleeping":
            entry["sleeping_lane_count"] += 1
        elif runtime_state == "cold":
            entry["cold_lane_count"] += 1
        elif runtime_state == "starting":
            entry["starting_lane_count"] += 1
        elif runtime_state == "error":
            entry["error_lane_count"] += 1

        entry["active_requests"] += active_requests
        entry["effective_vram_mb"] += _safe_float(lane.get("effective_vram_mb")) or 0.0
        entry["reported_vram_mb"] += _safe_float(lane.get("reported_vram_mb")) or 0.0
        entry["pid_vram_mb"] += _safe_float(lane.get("pid_vram_mb")) or 0.0
        entry["device_vram_mb"] += _safe_float(lane.get("device_vram_mb")) or 0.0

        queue_waiting = _safe_float(backend_metrics.get("queue_waiting"))
        if queue_waiting is not None:
            entry["queue_waiting_current"] += queue_waiting

        requests_running = _safe_float(backend_metrics.get("requests_running"))
        if requests_running is not None:
            entry["requests_running_current"] += requests_running

        prompt_tokens_total = _safe_float(backend_metrics.get("prompt_tokens_total"))
        if prompt_tokens_total is not None:
            current_prompt = _safe_float(entry.get("prompt_tokens_total")) or 0.0
            entry["prompt_tokens_total"] = current_prompt + prompt_tokens_total

        generation_tokens_total = _safe_float(backend_metrics.get("generation_tokens_total"))
        if generation_tokens_total is not None:
            current_generation = _safe_float(entry.get("generation_tokens_total")) or 0.0
            entry["generation_tokens_total"] = current_generation + generation_tokens_total

        gpu_cache_usage_percent = _safe_float(backend_metrics.get("gpu_cache_usage_percent"))
        if gpu_cache_usage_percent is not None:
            entry["_gpu_cache_usage_percent_sum"] += gpu_cache_usage_percent
            entry["_gpu_cache_usage_percent_count"] += 1
            current_max = _safe_float(entry.get("gpu_cache_usage_percent_max"))
            entry["gpu_cache_usage_percent_max"] = (
                gpu_cache_usage_percent
                if current_max is None
                else max(current_max, gpu_cache_usage_percent)
            )

        prefix_cache_hit_rate = _safe_float(backend_metrics.get("prefix_cache_hit_rate"))
        if prefix_cache_hit_rate is not None:
            entry["_prefix_cache_hit_rate_sum"] += prefix_cache_hit_rate
            entry["_prefix_cache_hit_rate_count"] += 1

        _merge_histogram_buckets(entry["ttft_histogram"], ttft_histogram)

    for entry in model_signals.values():
        gpu_count = int(entry.pop("_gpu_cache_usage_percent_count", 0) or 0)
        gpu_sum = float(entry.pop("_gpu_cache_usage_percent_sum", 0.0) or 0.0)
        if gpu_count > 0:
            entry["gpu_cache_usage_percent_avg"] = gpu_sum / gpu_count

        prefix_count = int(entry.pop("_prefix_cache_hit_rate_count", 0) or 0)
        prefix_sum = float(entry.pop("_prefix_cache_hit_rate_sum", 0.0) or 0.0)
        if prefix_count > 0:
            entry["prefix_cache_hit_rate_avg"] = prefix_sum / prefix_count

        entry["ttft_p95_seconds"] = _histogram_quantile_seconds(entry.get("ttft_histogram"))

    return {
        "provider": provider_signals,
        "models": model_signals,
        "lanes": lane_signals,
    }


def _build_live_local_provider_sample(
    provider: Optional[Dict[str, Any]],
    snapshot: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not _logosnode_snapshot_is_connected(snapshot):
        return None

    runtime = snapshot.get("runtime") if isinstance(snapshot, dict) else {}
    if not isinstance(runtime, dict):
        return None

    lanes = runtime.get("lanes") if isinstance(runtime.get("lanes"), list) else []
    devices = runtime.get("devices") if isinstance(runtime.get("devices"), dict) else {}
    capacity = runtime.get("capacity") if isinstance(runtime.get("capacity"), dict) else {}
    transport = runtime.get("transport") if isinstance(runtime.get("transport"), dict) else {}

    used_vram_mb = float(devices.get("used_memory_mb") or 0.0)
    if used_vram_mb <= 0:
        used_vram_mb = float(capacity.get("total_effective_vram_mb") or 0.0)

    total_vram_mb = float(devices.get("total_memory_mb") or 0.0)
    if total_vram_mb <= 0 and isinstance(provider, dict) and provider.get("total_vram_mb") is not None:
        total_vram_mb = float(provider.get("total_vram_mb") or 0.0)

    remaining_vram_mb: Optional[float] = None
    if devices.get("nvidia_smi_available"):
        remaining_vram_mb = float(devices.get("free_memory_mb") or 0.0)
    elif total_vram_mb > 0:
        remaining_vram_mb = max(total_vram_mb - used_vram_mb, 0.0)

    loaded_models = _normalize_loaded_models(lanes)
    runtime_modes = _runtime_modes_for_lanes(lanes)
    scheduler_signals = _build_logosnode_scheduler_signals(runtime)

    if remaining_vram_mb is None and not loaded_models and used_vram_mb <= 0:
        return None

    timestamp = runtime.get("timestamp") or snapshot.get("last_heartbeat")
    if not isinstance(timestamp, str) or not timestamp.strip():
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    return {
        "timestamp": timestamp,
        "snapshot_source": "logosnode-runtime",
        "provider_type": provider.get("provider_type") if isinstance(provider, dict) else "logosnode",
        "connection_state": "online",
        "connected": True,
        "transport_connected": bool(transport.get("connected", True)),
        "runtime_modes": runtime_modes,
        "vram_mb": used_vram_mb,
        "used_vram_mb": used_vram_mb,
        "remaining_vram_mb": remaining_vram_mb,
        "total_vram_mb": total_vram_mb if total_vram_mb > 0 else None,
        "models_loaded": len(loaded_models),
        "loaded_models": loaded_models,
        "runtime_payload": runtime,
        "scheduler_signals": scheduler_signals,
    }


def _sample_snapshot_id(sample: Dict[str, Any]) -> int:
    try:
        return int(sample.get("snapshot_id") or 0)
    except (TypeError, ValueError):
        return 0


def _sample_sort_key(sample: Dict[str, Any]) -> tuple[int, str]:
    return (_sample_snapshot_id(sample), str(sample.get("timestamp") or ""))


def _merge_provider_samples(
    existing_samples: list[Dict[str, Any]],
    extra_samples: list[Dict[str, Any]],
) -> list[Dict[str, Any]]:
    by_key: dict[str, Dict[str, Any]] = {}
    for sample in list(existing_samples) + list(extra_samples):
        if not isinstance(sample, dict):
            continue
        key = str(sample.get("snapshot_id") or sample.get("timestamp") or "")
        if not key:
            continue
        by_key[key] = {**by_key.get(key, {}), **sample}
    return sorted(by_key.values(), key=_sample_sort_key)


def _load_persisted_local_provider_vram_payload(
    logos_key: str,
    *,
    day: str,
    after_snapshot_id: int = 0,
) -> Dict[str, Any]:
    with DBManager() as db:
        if int(after_snapshot_id or 0) > 0:
            payload, status = db.get_ollama_vram_deltas(
                logos_key,
                day=day,
                after_snapshot_id=int(after_snapshot_id or 0),
            )
        elif str(day).strip().lower() == "all":
            payload, status = db.get_ollama_vram_deltas(logos_key, day="all", after_snapshot_id=0)
        else:
            payload, status = db.get_ollama_vram_stats(logos_key, day=day, bucket_seconds=5)
    if status != 200 or not isinstance(payload, dict):
        return {
            "providers": [],
            "last_snapshot_id": int(after_snapshot_id or 0),
        }
    payload.setdefault("providers", [])
    payload.setdefault("last_snapshot_id", int(after_snapshot_id or 0))
    return payload


def _capture_logosnode_provider_snapshot(
    provider_id: int,
    runtime: Dict[str, Any],
) -> None:
    sample = _build_live_local_provider_sample(None, {
        "last_heartbeat": runtime.get("timestamp"),
        "runtime": runtime,
    })
    if sample is None:
        return

    timestamp = _parse_iso_datetime(sample.get("timestamp"))
    used_bytes = int(float(sample.get("used_vram_mb") or 0.0) * 1024 * 1024)
    total_vram_mb = sample.get("total_vram_mb")
    total_bytes = None
    if total_vram_mb is not None:
        total_bytes = int(float(total_vram_mb or 0.0) * 1024 * 1024)
    free_vram_mb = sample.get("remaining_vram_mb")
    free_bytes = None
    if free_vram_mb is not None:
        free_bytes = int(float(free_vram_mb or 0.0) * 1024 * 1024)

    with DBManager() as db:
        snapshot_id = db.insert_provider_snapshot(
            provider_id=provider_id,
            snapshot_ts=timestamp,
            total_models_loaded=int(sample.get("models_loaded") or 0),
            total_vram_used_bytes=used_bytes,
            total_memory_bytes=total_bytes,
            free_memory_bytes=free_bytes,
            loaded_models=list(sample.get("loaded_models") or []),
            snapshot_source=str(sample.get("snapshot_source") or "logosnode-runtime"),
            runtime_payload=sample.get("runtime_payload") if isinstance(sample.get("runtime_payload"), dict) else {},
            scheduler_signals=sample.get("scheduler_signals") if isinstance(sample.get("scheduler_signals"), dict) else {},
            poll_success=True,
        )
        # Persist calibrated model profiles into the dedicated table
        runtime_payload = sample.get("runtime_payload")
        if isinstance(runtime_payload, dict):
            model_profiles = runtime_payload.get("model_profiles")
            if isinstance(model_profiles, dict) and model_profiles:
                try:
                    db.upsert_model_profiles(provider_id, model_profiles)
                except Exception:
                    logger.debug("Failed to upsert model profiles for provider %s", _resolve_provider_name(provider_id), exc_info=True)

    sample["snapshot_id"] = snapshot_id
    asyncio.create_task(_logosnode_registry.record_runtime_sample(provider_id, sample))


def _merge_local_provider_vram_payload(
    logos_key: str,
    payload: Dict[str, Any],
    *,
    day: str,
    after_snapshot_id: int = 0,
    include_live_runtime: bool,
) -> Dict[str, Any]:
    providers = payload.get("providers") if isinstance(payload.get("providers"), list) else []
    providers_by_id: Dict[int, Dict[str, Any]] = {}
    unnamed_providers: list[Dict[str, Any]] = []

    for provider in providers:
        if not isinstance(provider, dict):
            continue
        entry = dict(provider)
        entry["data"] = list(entry.get("data") or [])
        provider_id = entry.get("provider_id")
        if isinstance(provider_id, int):
            providers_by_id[provider_id] = entry
        else:
            unnamed_providers.append(entry)

    with DBManager() as db:
        inventory, status = db.get_local_provider_inventory(logos_key)
    if status != 200 or not isinstance(inventory, list):
        merged = list(providers_by_id.values()) + unnamed_providers
        merged.sort(key=lambda item: str(item.get("name") or "").lower())
        next_payload = dict(payload)
        next_payload["providers"] = merged
        return next_payload

    for provider in inventory:
        if not isinstance(provider, dict):
            continue
        provider_id = int(provider.get("provider_id") or 0)
        if provider_id <= 0:
            continue
        entry = providers_by_id.get(provider_id)
        if entry is None:
            entry = {
                "provider_id": provider_id,
                "name": provider.get("name") or f"Provider {provider_id}",
                "data": [],
            }
            providers_by_id[provider_id] = entry

        entry["provider_type"] = provider.get("provider_type")
        entry["base_url"] = provider.get("base_url")
        entry["parallel_capacity"] = provider.get("parallel_capacity")
        if provider.get("total_vram_mb") is not None:
            entry["configured_total_vram_mb"] = provider.get("total_vram_mb")

        runtime_snapshot = _logosnode_registry.peek_runtime_snapshot(provider_id)
        connected = _logosnode_snapshot_is_connected(runtime_snapshot)
        entry["connected"] = connected
        entry["connection_state"] = "online" if connected else "offline"
        entry["last_heartbeat"] = runtime_snapshot.get("last_heartbeat") if runtime_snapshot else None

        runtime = runtime_snapshot.get("runtime") if isinstance(runtime_snapshot, dict) else {}
        lanes = runtime.get("lanes") if isinstance(runtime, dict) and isinstance(runtime.get("lanes"), list) else []
        runtime_modes = _runtime_modes_for_lanes(lanes)
        if runtime_modes:
            entry["runtime_modes"] = runtime_modes
        transport = runtime.get("transport") if isinstance(runtime, dict) and isinstance(runtime.get("transport"), dict) else {}
        if transport:
            entry["transport_connected"] = bool(transport.get("connected", connected))

        data = list(entry.get("data") or [])

        if include_live_runtime and _is_today_or_all_utc(day):
            recent_samples = _logosnode_registry.peek_recent_samples(
                provider_id,
                after_snapshot_id=int(after_snapshot_id or 0),
            )
            if recent_samples:
                data = _merge_provider_samples(data, recent_samples)
            elif connected:
                live_sample = _build_live_local_provider_sample(provider, runtime_snapshot)
                if live_sample is not None:
                    data = _merge_provider_samples(data, [live_sample])

        entry["data"] = data

    merged = list(providers_by_id.values()) + unnamed_providers
    merged.sort(key=lambda item: str(item.get("name") or "").lower())
    next_payload = dict(payload)
    next_payload["providers"] = merged
    return next_payload


def _build_live_local_provider_vram_payload(
    logos_key: str,
    *,
    day: str,
    after_snapshot_id: int = 0,
) -> Dict[str, Any]:
    payload = _load_persisted_local_provider_vram_payload(
        logos_key,
        day=day,
        after_snapshot_id=after_snapshot_id,
    )
    payload = _merge_local_provider_vram_payload(
        logos_key,
        payload,
        day=day,
        after_snapshot_id=after_snapshot_id,
        include_live_runtime=True,
    )
    last_snapshot_id = int(payload.get("last_snapshot_id") or after_snapshot_id or 0)
    for provider in payload.get("providers") or []:
        for sample in provider.get("data") or []:
            sample_id = _sample_snapshot_id(sample)
            if sample_id > last_snapshot_id:
                last_snapshot_id = sample_id
    payload["last_snapshot_id"] = last_snapshot_id
    return payload


def _record_log_failure(
    log_id: Optional[int],
    request_id: Optional[str],
    error_message: str,
    *,
    result_status: str = "error",
    provider_id: Optional[int] = None,
    model_id: Optional[int] = None,
    classification_stats: Optional[Dict[str, Any]] = None,
    scheduling_stats: Optional[Dict[str, Any]] = None,
) -> None:
    if not log_id:
        return

    payload = {"error": error_message} if error_message else None
    scheduling_stats = scheduling_stats or {}
    classification_stats = classification_stats or {}

    try:
        with DBManager() as db:
            db.set_response_payload(
                log_id,
                payload,
                provider_id,
                model_id,
                {},
                -1,
                classification_stats,
                request_id=request_id,
                queue_depth_at_arrival=scheduling_stats.get("queue_depth_at_arrival"),
                utilization_at_arrival=scheduling_stats.get("utilization_at_arrival"),
            )
            db.update_log_entry_metrics(
                log_id=log_id,
                request_id=request_id,
                model_id=model_id,
                provider_id=provider_id,
                result_status=result_status,
                error_message=error_message,
                cold_start=scheduling_stats.get("is_cold_start"),
            )
    except Exception:
        logger.exception("Failed to record terminal log failure (log_id=%s, request_id=%s)", log_id, request_id)


@dataclass
class _StreamingLogAccumulator:
    """
    Line-buffered SSE parser for request logging.

    Network chunk boundaries are not aligned with SSE event boundaries, especially on the
    logosnode websocket path. Buffer until complete lines are available so streamed usage
    metadata is not lost when it arrives split across chunks.
    """

    buffer: str = ""
    full_text: str = ""
    first_chunk: Optional[Dict[str, Any]] = None
    last_chunk: Optional[Dict[str, Any]] = None

    def feed(self, chunk: bytes | str) -> None:
        if isinstance(chunk, bytes):
            text = chunk.decode("utf-8", errors="replace")
        else:
            text = str(chunk)
        self.buffer += text
        self._consume_complete_lines()

    def finish(self) -> None:
        if not self.buffer:
            return
        remainder = self.buffer
        self.buffer = ""
        for line in remainder.splitlines():
            self._consume_line(line.rstrip("\r"))

    def usage(self) -> Dict[str, Any]:
        if isinstance(self.last_chunk, dict):
            usage = self.last_chunk.get("usage")
            if isinstance(usage, dict):
                return usage
        return {}

    def response_payload(self) -> Dict[str, Any]:
        usage = self.usage()
        response_payload: Dict[str, Any] = {"content": self.full_text}
        base_payload = None

        if self.first_chunk:
            base_payload = self.first_chunk.copy()
        if self.last_chunk:
            if base_payload is None:
                base_payload = self.last_chunk.copy()
            else:
                for key, value in self.last_chunk.items():
                    if key not in base_payload:
                        base_payload[key] = value

        if base_payload:
            response_payload = base_payload
            if "choices" in response_payload and response_payload["choices"]:
                response_payload["choices"][0]["delta"] = {"content": self.full_text}
        if usage:
            response_payload["usage"] = usage
        return response_payload

    def _consume_complete_lines(self) -> None:
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            self._consume_line(line.rstrip("\r"))

    def _consume_line(self, line: str) -> None:
        stripped = line.strip()
        if not stripped or stripped == "data: [DONE]" or not stripped.startswith("data: "):
            return
        try:
            blob = json.loads(stripped[6:])
        except json.JSONDecodeError:
            return
        if not isinstance(blob, dict):
            return

        self.last_chunk = blob
        if self.first_chunk is None:
            self.first_chunk = blob

        choices = blob.get("choices")
        if isinstance(choices, list) and choices:
            delta = choices[0].get("delta", {})
            if isinstance(delta, dict):
                content = delta.get("content", "")
                if content:
                    self.full_text += content


def _usage_tokens_from_payload(response_payload: Any) -> Dict[str, int]:
    if not isinstance(response_payload, dict):
        return {}
    usage = response_payload.get("usage")
    if not isinstance(usage, dict):
        return {}
    return extract_token_usage(usage)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup/shutdown lifecycle.
    Initializes the request pipeline components and gRPC server.
    """

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        force=True
    )
    formatter = MultiLineFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.setFormatter(formatter)
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        named_logger = logging.getLogger(logger_name)
        named_logger.handlers.clear()
        named_logger.propagate = True
    uvicorn_access_logger = logging.getLogger("uvicorn.access")
    uvicorn_access_logger.filters.clear()
    uvicorn_access_logger.addFilter(UvicornAccessFilter())
    uvicorn_error_logger = logging.getLogger("uvicorn.error")
    uvicorn_error_logger.filters.clear()
    uvicorn_error_logger.addFilter(UvicornErrorFilter())
    logging.getLogger("logos").setLevel(logging.INFO)
    logging.getLogger("logos.sdi.providers.logosnode_provider").setLevel(logging.DEBUG)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
    logging.getLogger("transformers").setLevel(logging.WARNING)
    logging.getLogger("huggingface_hub").setLevel(logging.WARNING)

    # Start Pipeline
    await start_pipeline()

    # Start gRPC server
    global _grpc_server
    _grpc_server = grpc.aio.server()
    model_pb2_grpc.add_LogosServicer_to_server(LogosServicer(_pipeline), _grpc_server)
    _grpc_server.add_insecure_port("[::]:50051")
    await _grpc_server.start()

    # Auto-setup: create root user + API key on first startup
    with DBManager() as db:
        db.is_root_initialized()
    if not DBManager.is_initialized():
        logging.info("First startup detected — creating root user...")
        with DBManager() as db:
            result = db.setup()
        if "error" in result:
            logging.error("Error during initial setup: %s", result)
        else:
            logging.info("Initial setup complete. Root API key: %s", result["api_key"])
        # Apply migrations on fresh install (init.sql already has current schema)
        with DBManager() as db:
            logging.info("Applying pending migrations on fresh install...")
            db.run_migrations(is_fresh_install=True)
    else:
        logging.info("Database already initialized, skipping setup.")
        # Apply any pending migrations on existing install
        with DBManager() as db:
            logging.info("Checking for pending migrations...")
            db.run_migrations(is_fresh_install=False)

    yield

    # Shutdown logic
    if _capacity_planner:
        await _capacity_planner.stop()
    if _grpc_server:
        await _grpc_server.stop(0)


# Prometheus metrics auth: set PROMETHEUS_API_KEY env var to require auth; if unset, deny all.
_PROMETHEUS_API_KEY = os.getenv("PROMETHEUS_API_KEY")

# Initialize FastAPI app with lifespan
app = FastAPI(
    docs_url="/docs",
    openapi_url="/openapi.json",
    lifespan=lifespan,
    swagger_ui_init_oauth={},
    openapi_tags=[
        {"name": "user-facing", "description": "OpenAI-compatible API endpoints for model inference, model listing, and async jobs"},
        {"name": "admin", "description": "Database management, statistics, dashboards, and system configuration"},
        {"name": "logosnode", "description": "LogosWorkerNode provider registration, sessions, and lane management"},
        {"name": "monitoring", "description": "Prometheus metrics and health checks"},
    ],
)

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    from fastapi.openapi.utils import get_openapi
    schema = get_openapi(
        title=app.title or "Logos",
        version=app.version or "0.1.0",
        routes=app.routes,
    )
    schema["components"] = schema.get("components", {})
    schema["components"]["securitySchemes"] = {
        "LogosApiKey": {
            "type": "apiKey",
            "in": "header",
            "name": "logos_key",
            "description": "Logos API key for all endpoints",
        },
        "PrometheusApiKey": {
            "type": "http",
            "scheme": "bearer",
            "description": "Prometheus metrics API key (set via PROMETHEUS_API_KEY env var)",
        },
    }
    # Default: all endpoints require LogosApiKey
    schema["security"] = [{"LogosApiKey": []}]
    # Fix duplicate operationIds: api_route() with multiple methods shares one
    # function name, so FastAPI generates the same operationId for each method.
    # Append the HTTP method to make them unique.
    seen_ids: dict[str, int] = {}
    for path, methods in schema.get("paths", {}).items():
        for method, detail in methods.items():
            if not isinstance(detail, dict):
                continue
            # Override /metrics to use PrometheusApiKey instead of the global default
            if path == "/metrics":
                detail["security"] = [{"PrometheusApiKey": []}]
            op_id = detail.get("operationId")
            if op_id:
                if op_id in seen_ids:
                    detail["operationId"] = f"{op_id}_{method}"
                else:
                    seen_ids[op_id] = 1
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi

_logos_domain = os.getenv("LOGOS_DOMAIN", "localhost")
_allowed_origins = [
    f"https://{_logos_domain}",
    f"https://{_logos_domain}:8080",
    f"https://{_logos_domain}:443",
]
# Also allow plain HTTP on localhost for local development
if _logos_domain == "localhost":
    _allowed_origins += [
        "http://localhost",
        "http://localhost:8080",
        "http://localhost:18080",
        "http://localhost:18081",
        "http://localhost:18443",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],  # logos_key, Authorization, etc.
)


@app.get("/metrics", tags=["monitoring"])
async def prometheus_metrics(request: Request):
    """Prometheus metrics endpoint. Requires PROMETHEUS_API_KEY env var to be set.
    Pass the key via `Authorization: Bearer <key>` header."""
    if not _PROMETHEUS_API_KEY:
        raise HTTPException(status_code=403, detail="Metrics endpoint disabled (PROMETHEUS_API_KEY not configured)")
    auth = request.headers.get("authorization", "")
    token = auth.removeprefix("Bearer ").strip() if auth.lower().startswith("bearer ") else auth.strip()
    if not hmac.compare_digest(token, _PROMETHEUS_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing metrics API key")
    body, content_type = _prometheus_metrics_response()
    from starlette.responses import Response
    return Response(content=body, media_type=content_type)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _extract_policy(headers: dict, logos_key: str, body: dict):
    """
    Extract policy from request headers or model string.

    :param headers: Request headers dict
    :param logos_key: User's logos_key
    :param body: Request body (for model string parsing)
    :return: Policy dict or None (will default to ProxyPolicy)
    """
    from logos.model_string_parser import parse_model_string

    policy = None

    if "policy" in headers:
        try:
            policy_id = int(headers["policy"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="policy header must be an integer")
        try:
            with DBManager() as db:
                policy = db.get_policy(logos_key, policy_id)
                if isinstance(policy, dict) and "error" in policy:
                    raise HTTPException(
                        status_code=404,
                        detail="Policy not found for this process",
                    )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Failed to load policy from header: {e}")
            raise HTTPException(status_code=500, detail="Failed to load policy")

    if policy is None:
        policy = {}

    try:
        mdl = extract_model(body)
        if mdl and mdl.startswith("logos-v"):
            model_string_dto = parse_model_string(mdl)
            p = model_string_dto.policy
            if not p.get("default"):
                for key in p:
                    if key == "default":
                        continue
                    if key == "privacy":
                        policy["threshold_privacy"] = p[key]
                    # Add other policy settings as needed
    except Exception as e:
        logger.debug(f"Could not parse model string for policy: {e}")

    return policy if policy else None


def _require_root_access(logos_key: str) -> None:
    with DBManager() as db:
        require_logos_admin_key(logos_key, db)

def _normalize_provider_type(provider_type: str | None) -> str:
    return normalize_provider_type(provider_type)


def _logosnode_insecure_dev_mode_enabled() -> bool:
    raw = os.getenv("LOGOS_NODE_DEV_ALLOW_INSECURE_HTTP", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _is_tls_request(request: Request) -> bool:
    if _logosnode_insecure_dev_mode_enabled():
        return True
    if request.url.scheme == "https":
        return True
    forwarded = request.headers.get("x-forwarded-proto", "")
    forwarded_values = [item.strip().lower() for item in forwarded.split(",") if item.strip()]
    return "https" in forwarded_values


def _require_tls_request(request: Request) -> None:
    if not _is_tls_request(request):
        raise HTTPException(status_code=400, detail="TLS is required for logosnode auth/session endpoints")


def _build_logosnode_ws_url(request: Request, token: str) -> str:
    _require_tls_request(request)
    ws_scheme = "ws" if _logosnode_insecure_dev_mode_enabled() else "wss"
    host = request.headers.get("host", "")
    if not host:
        raise HTTPException(status_code=400, detail="Missing Host header for websocket URL generation")
    return f"{ws_scheme}://{host}/logosdb/providers/logosnode/session?token={token}"


async def _filter_logosnode_deployments(deployments: list[Deployment]) -> list[Deployment]:
    """
    Enforce provider model scope intersection:
    DB deployment assignment AND node capabilities.
    """
    if not deployments:
        return []

    filtered: list[Deployment] = []
    model_name_cache: dict[int, str] = {}

    with DBManager() as db:
        for deployment in deployments:
            provider_type = _normalize_provider_type(deployment.get("type"))
            if provider_type != "logosnode":
                filtered.append({**deployment, "type": provider_type or deployment.get("type", "")})
                continue

            model_id = int(deployment["model_id"])
            if model_id not in model_name_cache:
                model_info = db.get_model(model_id)
                model_name_cache[model_id] = (model_info or {}).get("name", "")

            model_name = model_name_cache[model_id]
            if not model_name:
                continue

            allowed = await _logosnode_registry.is_model_allowed(
                int(deployment["provider_id"]),
                model_name,
            )
            if allowed:
                filtered.append({**deployment, "type": "logosnode"})

    return filtered


async def start_pipeline():
    """Initialize the new request pipeline components."""
    global _pipeline, _queue_mgr, _logosnode_facade, _azure_facade, _context_resolver
    global _demand_tracker, _capacity_planner

    logger.info("Initializing Request Pipeline...")

    _queue_mgr = PriorityQueueManager()

    _logosnode_facade = LogosNodeSchedulingDataFacade(_queue_mgr, None, runtime_registry=_logosnode_registry)
    _azure_facade = AzureSchedulingDataFacade(None)

    await _register_models_with_facades(_logosnode_facade, _azure_facade)

    model_registry = _build_model_registry()

    # Scheduler: use ETTFT-correcting scheduler (ablatable via env var)
    ettft_enabled = os.getenv("LOGOS_SCHEDULER_ETTFT_ENABLED", "true").lower() == "true"
    scheduler = ClassificationCorrectingScheduler(
        queue_manager=_queue_mgr,
        logosnode_facade=_logosnode_facade,
        azure_facade=_azure_facade,
        model_registry=model_registry,
        ettft_enabled=ettft_enabled,
    )
    logger.info("Scheduler: ClassificationCorrectingScheduler (ettft_enabled=%s)", ettft_enabled)

    # 5. Executor
    executor = Executor()

    # 6. Context Resolver
    _context_resolver = ContextResolver(logosnode_registry=_logosnode_registry)

    # 7. Classifier
    clf = classifier()

    # 8. Demand Tracker (for capacity planner)
    _demand_tracker = DemandTracker()

    # 9. Pipeline
    _pipeline = RequestPipeline(
        classifier=clf,
        scheduler=scheduler,
        executor=executor,
        context_resolver=_context_resolver,
        demand_tracker=_demand_tracker,
    )

    # 10. Capacity Planner (ablatable via env var)
    planner_enabled = os.getenv("LOGOS_CAPACITY_PLANNER_ENABLED", "true").lower() == "true"
    _capacity_planner = CapacityPlanner(
        logosnode_facade=_logosnode_facade,
        logosnode_registry=_logosnode_registry,
        demand_tracker=_demand_tracker,
        enabled=planner_enabled,
        on_state_change=scheduler.reevaluate_model_queues,
    )
    _context_resolver = ContextResolver(
        logosnode_registry=_logosnode_registry,
        lane_preparer=_capacity_planner,
    )
    _pipeline._context_resolver = _context_resolver
    await _capacity_planner.start()

    logger.info(
        "Request Pipeline Initialized with ETTFT-correcting scheduler "
        "(ettft=%s, planner=%s)", ettft_enabled, planner_enabled,
    )


async def _register_models_with_facades(logosnode_facade: LogosNodeSchedulingDataFacade, azure_facade: AzureSchedulingDataFacade):
    """Register all models with their respective SDI facades."""
    logosnode_registrations: list[dict[str, Any]] = []
    azure_registrations: list[dict[str, Any]] = []

    with DBManager() as db:
        deployments = db.get_all_deployments()
        if not deployments:
            logger.warning("No deployments found to register with SDI facades")
            logosnode_facade.replace_registrations([])
            azure_facade.replace_registrations([])
            return

        model_cache: Dict[int, Dict[str, Any]] = {}
        provider_cache: Dict[int, Dict[str, Any]] = {}

        for deployment in deployments:
            model_id = deployment["model_id"]
            provider_id = deployment["provider_id"]
            if model_id not in model_cache:
                model_info = db.get_model(model_id)
                if not model_info:
                    logger.warning("Model %s not found when registering providers", model_id)
                    continue
                model_cache[model_id] = model_info
            model_info = model_cache[model_id]
            model_name = model_info["name"]

            if provider_id not in provider_cache:
                provider_cache[provider_id] = db.get_provider(provider_id) or {}
            provider_info = provider_cache[provider_id]
            provider_name = provider_info.get("name", f"provider-{provider_id}")
            provider_type = normalize_provider_type(
                deployment.get("type"),
                provider_name=provider_name,
                base_url=provider_info.get("base_url"),
            )

            # Provider-level SDI config (VRAM, admin URL, etc.)
            provider_config = db.get_provider_config(provider_id) or {}

            if not provider_type:
                logger.warning(
                    "Skipping provider %s (%s) for model %s: missing provider_type",
                    provider_id,
                    provider_name,
                    model_id,
                )
                continue

            if provider_type == "logosnode":
                logosnode_registrations.append(
                    {
                        "model_id": model_id,
                        "provider_name": provider_name,
                        "logosnode_admin_url": (provider_config.get("ollama_admin_url") or provider_info.get("base_url")),
                        "model_name": model_name,
                        "total_vram_mb": provider_config.get("total_vram_mb", 65536),
                        "provider_id": provider_id,
                        "db_parallel": model_info.get("parallel"),
                    }
                )
            elif provider_type == "azure":
                endpoint = db.get_endpoint_for_deployment(model_id, provider_id)
                deployment_name = endpoint or ""
                azure_registrations.append(
                    {
                        "model_id": model_id,
                        "provider_name": provider_name,
                        "model_name": model_name,
                        "deployment_name": extract_azure_deployment_name(deployment_name),
                        "provider_id": provider_id,
                    }
                )
            else:
                logger.debug(
                    "Skipping provider %s (%s) for model %s: unsupported type '%s'",
                    provider_id,
                    provider_name,
                    model_id,
                    provider_type,
                )

    azure_registrations = [item for item in azure_registrations if item.get("deployment_name")]
    logosnode_facade.replace_registrations(logosnode_registrations)
    azure_facade.replace_registrations(azure_registrations)


def _build_model_registry() -> Dict[tuple[int, int], str]:
    """Build mapping of (model_id, provider_id) -> provider_type."""
    registry: Dict[tuple[int, int], str] = {}
    with DBManager() as db:
        for deployment in db.get_all_deployments():
            model_id = deployment["model_id"]
            provider_id = deployment["provider_id"]
            provider_info = db.get_provider(provider_id) or {}
            provider_type = normalize_provider_type(
                deployment.get("type"),
                provider_name=provider_info.get("name"),
                base_url=provider_info.get("base_url"),
            )
            if provider_type:
                registry[(model_id, provider_id)] = provider_type
    return registry


def classifier() -> ClassificationManager:
    """Build classifier with all models from database."""
    mdls = []
    with DBManager() as db:
        for model_id in db.get_all_models():
            tpl = db.get_model(model_id)
            if tpl:
                mdls.append({
                    "id": tpl["id"],
                    "name": tpl["name"],
                    "weight_privacy": tpl["weight_privacy"],
                    "weight_latency": tpl["weight_latency"],
                    "weight_accuracy": tpl["weight_accuracy"],
                    "weight_cost": tpl["weight_cost"],
                    "weight_quality": tpl["weight_quality"],
                    "tags": tpl["tags"],
                    "parallel": tpl["parallel"],
                    "description": tpl["description"],
                    "classification_weight": Balancer(),
                })

    manager = ClassificationManager(mdls)
    manager.update_manager(mdls)
    return manager


def rebuild_classifier():
    """
    Rebuild classifier with current models from database.
    Updates the global pipeline's classifier instance.
    Called when models are added, updated, or deleted.
    """
    global _pipeline
    if _pipeline:
        new_classifier = classifier()
        _pipeline.update_classifier(new_classifier)
        logger.info("Classifier rebuilt with updated models")


async def refresh_pipeline_runtime_state(*, rebuild_model_classifier: bool = False) -> None:
    """
    Refresh in-memory DB-derived runtime state without rebuilding the whole pipeline.

    This keeps queue state and active request tracking intact while making newly
    added providers/deployments/models available immediately.
    """
    global _pipeline, _logosnode_facade, _azure_facade
    if not _pipeline or not _logosnode_facade or not _azure_facade:
        return

    await _register_models_with_facades(_logosnode_facade, _azure_facade)
    _pipeline.scheduler.update_model_registry(_build_model_registry())

    if rebuild_model_classifier:
        rebuild_classifier()

    logger.info(
        "Refreshed in-memory pipeline state%s",
        " with classifier rebuild" if rebuild_model_classifier else "",
    )


def _streaming_response(context, payload, log_id, provider_id, model_id, policy_id, classification_stats, scheduling_stats=None, request_path=None):
    """Build streaming response using executor."""
    from fastapi.responses import StreamingResponse
    request_id = scheduling_stats.get("request_id") if scheduling_stats else None

    async def streamer():
        stream_log = _StreamingLogAccumulator()
        error_message = None
        timed_out = False
        ttft_recorded = False

        try:
            def process_headers(headers: dict):
                try:
                    _pipeline.update_provider_stats(model_id, provider_id, headers)
                except Exception:
                    pass
                try:
                    _record_azure_rate_limits(scheduling_stats, headers)
                except Exception:
                    pass

            # Prepare headers and payload using context resolver
            headers, prepared_payload = _context_resolver.prepare_headers_and_payload(context, payload)

            if context.provider_type == "logosnode" and context.lane_id:
                stream_payload = {
                    **prepared_payload,
                    "stream": True,
                    "stream_options": {"include_usage": True},
                }
                chunk_iter = _logosnode_registry.send_stream_command(
                    provider_id=provider_id,
                    action="infer_stream",
                    params={"lane_id": context.lane_id, "payload": stream_payload, "request_path": request_path},
                    timeout_seconds=_LOGOSNODE_STREAM_TIMEOUT_SECONDS,
                )
            else:
                chunk_iter = _pipeline.executor.execute_streaming(
                    context.forward_url,
                    headers,
                    prepared_payload,
                    on_headers=process_headers,
                )

            async for chunk in chunk_iter:
                yield chunk
                if chunk and not ttft_recorded:
                    if log_id:
                        with DBManager() as db:
                            db.set_time_at_first_token(log_id)
                    ttft_recorded = True

                stream_log.feed(chunk)
        except Exception as e:
            error_message = str(e)
            raise e
        finally:
            # Log completion with detailed token usage
            if log_id:
                stream_log.finish()
                response_payload = stream_log.response_payload()
                usage_tokens = _usage_tokens_from_payload(response_payload)

                with DBManager() as db:
                    db.set_response_payload(
                        log_id,
                        response_payload,
                        provider_id,
                        model_id,
                        usage_tokens,
                        policy_id,
                        classification_stats,
                        request_id=scheduling_stats.get("request_id") if scheduling_stats else None,
                        queue_depth_at_arrival=scheduling_stats.get("queue_depth_at_arrival") if scheduling_stats else None,
                        utilization_at_arrival=scheduling_stats.get("utilization_at_arrival") if scheduling_stats else None
                    )

            if scheduling_stats:
                status = "timeout" if timed_out else ("error" if error_message else "success")
                
                _pipeline.record_completion(
                    request_id=scheduling_stats.get("request_id"),
                    result_status=status,
                    error_message=error_message,
                    cold_start=scheduling_stats.get("is_cold_start")
                )
            
            # Release scheduler resources
            if scheduling_stats and scheduling_stats.get("request_id"):
                try:
                    _pipeline.scheduler.release(
                        model_id,
                        provider_id,
                        scheduling_stats.get("provider_type"),
                        scheduling_stats.get("request_id")
                    )
                except Exception as e:
                    logger.error(f"Failed to release scheduler resources: {e}")
    
    response_headers = {"X-Request-ID": request_id} if request_id else None
    return StreamingResponse(streamer(), media_type="text/event-stream", headers=response_headers)


async def _sync_response(context, payload, log_id, provider_id, model_id, policy_id, classification_stats, scheduling_stats=None, is_async_job=False, request_path=None):
    """Execute sync request and return response."""
    from fastapi.responses import JSONResponse
    request_id = scheduling_stats.get("request_id") if scheduling_stats else None

    try:
        # Prepare headers and payload using context resolver
        headers, prepared_payload = _context_resolver.prepare_headers_and_payload(context, payload)

        timed_out = False
        error_message = None
        status_override = None

        if context.provider_type == "logosnode" and context.lane_id:
            sync_payload = {**prepared_payload, "stream": False}
            try:
                rpc_result = await _logosnode_registry.send_command(
                    provider_id=provider_id,
                    action="infer",
                    params={"lane_id": context.lane_id, "payload": sync_payload, "request_path": request_path},
                    timeout_seconds=_LOGOSNODE_INFER_TIMEOUT_SECONDS,
                )
                status_override = int(rpc_result.get("status_code", 200))
                response_payload = rpc_result.get("body")
                if response_payload is None:
                    response_payload = {}
                if not isinstance(response_payload, dict):
                    response_payload = {"response": response_payload}
                rpc_error = str(rpc_result.get("error") or "").strip() or None
                if status_override >= 400 and rpc_error is None:
                    rpc_error = f"logosnode infer returned HTTP {status_override}"
                exec_result = ExecutionResult(
                    success=status_override < 400,
                    response=response_payload,
                    error=rpc_error,
                    usage={},
                    is_streaming=False,
                    headers=rpc_result.get("headers")
                    if isinstance(rpc_result.get("headers"), dict)
                    else None,
                )
            except LogosNodeOfflineError as exc:
                status_override = 503
                exec_result = ExecutionResult(
                    success=False,
                    response={"error": str(exc)},
                    error=str(exc),
                    usage={},
                    is_streaming=False,
                    headers=None,
                )
            except LogosNodeCommandError as exc:
                status_override = 502
                exec_result = ExecutionResult(
                    success=False,
                    response={"error": str(exc)},
                    error=str(exc),
                    usage={},
                    is_streaming=False,
                    headers=None,
                )
        else:
            exec_result = await _pipeline.executor.execute_sync(context.forward_url, headers, prepared_payload)

        # Update rate limits from response headers
        if exec_result.headers:
            try:
                _pipeline.update_provider_stats(model_id, provider_id, exec_result.headers)
            except Exception:
                pass
            try:
                _record_azure_rate_limits(scheduling_stats, exec_result.headers)
            except Exception:
                pass

        response_payload = exec_result.response
        if not exec_result.success:
            if not response_payload and exec_result.error:
                response_payload = {"error": exec_result.error}
            logger.error(
                f"Request failed (model_id={model_id}, provider_id={provider_id}): "
                f"{exec_result.error}, response={response_payload}"
            )

        if log_id:
            usage_tokens = _usage_tokens_from_payload(response_payload)

            with DBManager() as db:
                if exec_result.success:
                    db.set_time_at_first_token(log_id)
                db.set_response_payload(
                    log_id,
                    response_payload,
                    provider_id,
                    model_id,
                    usage_tokens,
                    policy_id,
                    classification_stats,
                    request_id=scheduling_stats.get("request_id") if scheduling_stats else None,
                    queue_depth_at_arrival=scheduling_stats.get("queue_depth_at_arrival") if scheduling_stats else None,
                    utilization_at_arrival=scheduling_stats.get("utilization_at_arrival") if scheduling_stats else None
                )

        if scheduling_stats:
            status = "timeout" if timed_out else ("success" if exec_result.success else "error")
            _pipeline.record_completion(
                request_id=scheduling_stats.get("request_id"),
                result_status=status,
                error_message=error_message if timed_out else (exec_result.error if not exec_result.success else None),
                cold_start=scheduling_stats.get("is_cold_start")
            )

        # Return dict for async jobs, JSONResponse for sync endpoints
        if is_async_job:
            status_code = status_override if status_override is not None else (504 if timed_out else (200 if exec_result.success else 500))
            return {"status_code": status_code, "data": response_payload}
        else:
            status_code = status_override if status_override is not None else (504 if timed_out else (200 if exec_result.success else 500))
            headers = {"X-Request-ID": request_id} if request_id else None
            return JSONResponse(content=exec_result.response, status_code=status_code, headers=headers)

    finally:
        if scheduling_stats and scheduling_stats.get("request_id"):
            try:
                _pipeline.scheduler.release(
                    model_id,
                    provider_id,
                    scheduling_stats.get("provider_type"),
                    scheduling_stats.get("request_id")
                )
            except Exception as e:
                logger.error(f"Failed to release scheduler resources: {e}")


def _proxy_streaming_response(forward_url: str, proxy_headers: dict, payload: dict,
                               log_id: Optional[int], provider_id: int, model_id: Optional[int],
                               policy_id: int, classified: dict, request_id: Optional[str] = None):
    """
    Build streaming response for PROXY MODE using executor.
    """
    from fastapi.responses import StreamingResponse
    import datetime

    async def streamer():
        stream_log = _StreamingLogAccumulator()
        ttft = None
        error_message = None

        try:
            async for chunk in _pipeline.executor.execute_streaming(
                forward_url, proxy_headers, payload
            ):
                # Track time to first token
                if ttft is None:
                    ttft = datetime.datetime.now(datetime.timezone.utc)
                    if log_id:
                        with DBManager() as db:
                            db.set_time_at_first_token(log_id)

                yield chunk

                stream_log.feed(chunk)
        except Exception as exc:  # noqa: BLE001
            error_message = str(exc)
            raise
        finally:
            # Log completion
            if log_id:
                stream_log.finish()
                response_payload = stream_log.response_payload()
                usage_tokens = _usage_tokens_from_payload(response_payload)

                with DBManager() as db:
                    if ttft is None and stream_log.first_chunk is not None and not error_message:
                        db.set_time_at_first_token(log_id)
                    db.set_response_payload(
                        log_id, response_payload, provider_id, model_id,
                        usage_tokens, policy_id, classified
                    )
                    db.update_log_entry_metrics(
                        log_id=log_id,
                        provider_id=provider_id,
                        model_id=model_id,
                        result_status="error" if error_message else "success",
                        error_message=error_message,
                    )

    response_headers = {"X-Request-ID": request_id} if request_id else None
    return StreamingResponse(streamer(), media_type="text/event-stream", headers=response_headers)


async def _proxy_sync_response(forward_url: str, proxy_headers: dict, payload: dict,
                                log_id: Optional[int], provider_id: int, model_id: Optional[int],
                                policy_id: int, classified: dict, is_async_job=False, request_id: Optional[str] = None):
    """
    Build synchronous response for PROXY MODE using executor.
    """
    from fastapi.responses import JSONResponse

    exec_result = await _pipeline.executor.execute_sync(
        forward_url, proxy_headers, payload
    )

    response_payload = exec_result.response
    if not exec_result.success and not response_payload and exec_result.error:
        response_payload = {"error": exec_result.error}

    if log_id:
        usage_tokens = _usage_tokens_from_payload(response_payload)

        with DBManager() as db:
            if exec_result.success:
                db.set_time_at_first_token(log_id)
            db.set_response_payload(
                log_id, response_payload, provider_id, model_id,
                usage_tokens, policy_id, classified
            )
            db.update_log_entry_metrics(
                log_id=log_id,
                provider_id=provider_id,
                model_id=model_id,
                result_status="success" if exec_result.success else "error",
                error_message=None if exec_result.success else exec_result.error,
            )

    # Return dict for async jobs, JSONResponse for sync endpoints
    if is_async_job:
        return {"status_code": 200 if exec_result.success else 500, "data": response_payload}
    else:
        headers = {"X-Request-ID": request_id} if request_id else None
        return JSONResponse(
            content=response_payload,
            status_code=200 if exec_result.success else 500,
            headers=headers,
        )


async def _execute_proxy_mode(
    body: Dict[str, Any],
    headers: Dict[str, str],
    logos_key: str,
    deployments: list[Deployment],
    log_id: Optional[int],
    is_async_job: bool,
    profile_id: Optional[int] = None,
    request_id: Optional[str] = None,
    request_path: Optional[str] = None,
):
    """
    Direct model execution: skip classification, reuse scheduling/SDI, resolve auth from DB.

    Resolves the requested model from the DB (access-controlled by logos_key), then reuses the
    resource-mode pipeline with allowed_models restricted to that model.
    """
    requested_model_name = str(body.get("model") or "").strip()
    if not requested_model_name:
        raise HTTPException(status_code=400, detail="Proxy mode requires 'model' in payload")

    with DBManager() as db:
        models_info = db.get_models_info(logos_key)

    model_name = _resolve_requested_model_name(
        requested_model_name,
        [str(row[1]) for row in models_info if len(row) > 1 and str(row[1]).strip()],
    )
    if model_name is None:
        raise HTTPException(status_code=404, detail=f"Model '{requested_model_name}' not available for this key")

    model_id = None
    for row in models_info:
        mid, name = row[0], row[1]
        if name == model_name:
            model_id = mid
            break

    if model_id is None:
        raise HTTPException(status_code=404, detail=f"Model '{requested_model_name}' not available for this key")

    # Ensure payload model matches DB name (avoid user-supplied mismatch)
    body = {**body, "model": model_name}

    # Narrow deployments to the requested model to preserve provider metadata
    model_deployments = [d for d in deployments if d["model_id"] == model_id]
    if not model_deployments:
        raise HTTPException(status_code=404, detail=f"No deployment found for model '{model_name}'")

    # Proxy mode still routes through classification/scheduling with a single allowed model.
    # This preserves policy screening while constraining execution to the requested model.
    return await _execute_resource_mode(
        deployments=model_deployments,
        body=body,
        headers=headers,
        logos_key=logos_key,
        log_id=log_id,
        is_async_job=is_async_job,
        allowed_models_override=[model_id],
        profile_id=profile_id,
        request_id=request_id,
        request_path=request_path,
    )


async def _execute_resource_mode(
    deployments: list[Deployment],
    body: Dict[str, Any],
    headers: Dict[str, str],
    logos_key: str,
    log_id: Optional[int],
    is_async_job: bool,
    allowed_models_override: Optional[list] = None,
    profile_id: Optional[int] = None,
    request_id: Optional[str] = None,
    request_path: Optional[str] = None,
):
    """
    Execute request in RESOURCE mode (classification + scheduling).

    RESOURCE mode uses the full request processing pipeline:
    1. **Classification** - Selects best model from available models using ML classifier
    2. **Scheduling** - Queues request considering model utilization and cold starts
    3. **Execution** - Makes API call to the selected model

    This mode is used when body["model"] is NOT specified, allowing the system to
    automatically choose the optimal model based on request characteristics and
    current system state.

    The scheduler is aware of:
    - Real-time model availability (via Ollama/Azure SDI facades)
    - Current queue depths per model
    - Cold start penalties
    - Model utilization levels

    Args:
        deployments: List of available deployments(model_id, provider_id) from request_setup()
        body: Request payload (should NOT contain "model" field)
        headers: Request headers
        logos_key: User's logos authentication key
        log_id: Usage log ID for tracking (None for requests without logging)
        is_async_job: Whether this is a background job (affects error handling)
            - False: Direct endpoint - raises HTTPException for errors
            - True: Background job - returns error dict for errors

    Returns:
        - For direct endpoints (is_async_job=False):
            - StreamingResponse if body["stream"] is True
            - JSONResponse if body["stream"] is False
        - For background jobs (is_async_job=True):
            - Dict with {"status_code": int, "data": response_payload}

    Raises:
        HTTPException: Only when is_async_job=False and an error occurs
    """
    allowed_models = get_unique_models_from_deployments(deployments)
    # Extract policy
    policy = _extract_policy(headers, logos_key, body)

    # Create Pipeline Request
    pipeline_req = PipelineRequest(
        logos_key=logos_key or "anon",
        payload=body,
        headers=headers,
        request_id=request_id,
        policy=policy,
        allowed_models=allowed_models,
        deployments=deployments,
        profile_id=profile_id
    )

    # Process through classification and scheduling
    result = await _pipeline.process(pipeline_req)

    if not result.success:
        error_msg = result.error or "Pipeline processing failed"
        _record_log_failure(
            log_id,
            result.scheduling_stats.get("request_id") or request_id,
            error_msg,
            model_id=result.model_id,
            provider_id=result.provider_id,
            classification_stats=result.classification_stats,
            scheduling_stats=result.scheduling_stats,
            result_status="timeout" if "timeout" in error_msg.lower() else "error",
        )
        if is_async_job:
            return {"status_code": 503, "data": {"error": error_msg}}
        else:
            raise HTTPException(status_code=503, detail=error_msg)

    # Execute and Respond
    try:
        if is_async_job:
            # Async jobs are always non-streaming - use helper
            return await _sync_response(
                result.execution_context,
                body,
                log_id,
                result.provider_id,
                result.model_id,
                -1,  # policy_id
                result.classification_stats,
                result.scheduling_stats,
                is_async_job=True,
                request_path=request_path,
            )
        else:
            # Sync endpoints support streaming
            if body.get("stream"):
                return _streaming_response(
                    result.execution_context,
                    body,
                    log_id,
                    result.provider_id,
                    result.model_id,
                    -1,  # Policy ID not implemented
                    result.classification_stats,
                    result.scheduling_stats,
                    request_path=request_path,
                )
            else:
                return await _sync_response(
                    result.execution_context,
                    body,
                    log_id,
                    result.provider_id,
                    result.model_id,
                    -1,  # Policy ID not implemented
                    result.classification_stats,
                    result.scheduling_stats,
                    request_path=request_path,
                )
    except Exception as e:
        logger.error(f"Error in _execute_resource_mode: {e}", exc_info=True)
        try:
            _pipeline.record_completion(
                request_id=result.scheduling_stats.get("request_id"),
                result_status="error",
                error_message=str(e)
            )
        except Exception as record_err:
            logger.error(f"Failed to record completion: {record_err}")

        _record_log_failure(
            log_id,
            result.scheduling_stats.get("request_id") or request_id,
            str(e),
            model_id=result.model_id,
            provider_id=result.provider_id,
            classification_stats=result.classification_stats,
            scheduling_stats=result.scheduling_stats,
        )

        if is_async_job:
            return {"status_code": 500, "data": {"error": str(e)}}
        else:
            raise e


async def route_and_execute(
    deployments: list[dict[str, int]],
    body: Dict[str, Any],
    headers: Dict[str, str],
    logos_key: str,
    path: str,
    log_id: Optional[int],
    is_async_job: bool = False,
    profile_id: Optional[int] = None,
    request_id: Optional[str] = None,
):
    """
    Route request to PROXY or RESOURCE mode and execute.

    This is the main entry point for all request handling. It decides between two execution modes:

    **PROXY MODE** (when body["model"] is specified):
    - Bypasses classification/scheduling pipeline
    - Forwards directly to the specified provider
    - User has full control over model/provider selection

    **RESOURCE MODE** (when body["model"] is NOT specified):
    - Full pipeline: Classification → Scheduling → Execution
    - System automatically selects optimal model
    - Scheduler considers utilization, queue depth, and cold starts

    Routing logic:
    - Case 1: No deployments available → 404 error
    - Case 2: body["model"] specified → PROXY mode (direct forwarding)
    - Case 3: no body["model"] → RESOURCE mode (classification + scheduling)

    Args:
        deployments: List of available deployments(model_id, provider_id) from request_setup()
        body: Request payload
        headers: Request headers
        logos_key: User's logos authentication key
        path: API endpoint path (e.g., "chat/completions")
        log_id: Usage log ID for tracking (None for requests without logging)
        is_async_job: Whether this is a background job (affects error handling)
            - False: Direct endpoint - client waits, raises HTTPException for errors
            - True: Background job - client gets job_id, returns error dict for errors
        profile_id: Profile ID for authorization (enforces profile-based model access)

    Returns:
        - For direct endpoints (is_async_job=False):
            - StreamingResponse if body["stream"] is True
            - JSONResponse if body["stream"] is False
        - For background jobs (is_async_job=True):
            - Dict with {"status_code": int, "data": response_payload}

    Raises:
        HTTPException: Only when is_async_job=False and an error occurs

    See Also:
        _execute_proxy_mode(): PROXY mode implementation
        _execute_resource_mode(): RESOURCE mode implementation
    """
    # No models available → ERROR
    if not deployments:
        _record_log_failure(log_id, request_id, "No models available for this user.", result_status="error")
        if is_async_job:
            return {"status_code": 404, "data": {"error": "No models available for this user."}}
        else:
            raise HTTPException(
                status_code=404,
                detail="No models available for this user."
            )

    try:
        # PROXY mode (body["model"] specified → direct forwarding)
        if body.get("model"):
            return await _execute_proxy_mode(
                body,
                headers,
                logos_key,
                deployments,
                log_id,
                is_async_job,
                profile_id=profile_id,
                request_id=request_id,
                request_path=path,
            )

        # RESOURCE mode (no body["model"] → classification + scheduling)
        return await _execute_resource_mode(
            deployments,
            body,
            headers,
            logos_key,
            log_id,
            is_async_job,
            profile_id=profile_id,
            request_id=request_id,
            request_path=path,
        )
    except HTTPException as exc:
        _record_log_failure(log_id, request_id, str(exc.detail), result_status="error")
        if is_async_job:
            return {"status_code": exc.status_code, "data": {"error": exc.detail}}
        raise
    except Exception as exc:
        _record_log_failure(log_id, request_id, str(exc), result_status="error")
        raise


async def handle_sync_request(path: str, request: Request):
    """
    Handle synchronous (non-job) requests for both /v1 and /openai endpoints.

    Performs authentication, model setup, and routing/execution.

    Args:
        path: API endpoint path
        request: FastAPI request object

    Returns:
        Response (StreamingResponse or JSONResponse)
    """
    # Authenticate with profile-based auth (REQUIRED for v1/openai/jobs endpoints)
    headers, auth, body, client_ip, log_id = await auth_parse_log(request, use_profile_auth=True)
    request_id = secrets.token_urlsafe(16)
    if log_id:
        with DBManager() as db:
            db.update_log_entry_metrics(
                log_id=log_id,
                request_id=request_id,
                timeout_s=body.get("timeout_s"),
            )

    # Get available deployments (model, provider tuple) for THIS profile - profile_id EXPLICITLY passed
    try:
        deployments = request_setup(headers, auth.logos_key, profile_id=auth.profile_id)
        deployments = await _filter_logosnode_deployments(deployments)
    except PermissionError as e:
        _record_log_failure(log_id, request_id, str(e), result_status="error")
        raise HTTPException(status_code=401, detail=str(e))
    except ValueError as e:
        _record_log_failure(log_id, request_id, str(e), result_status="error")
        raise HTTPException(status_code=400, detail=str(e))

    if not deployments:
        requested_model = body.get("model", "unknown")
        msg = f"No available model deployments for model '{requested_model}' in this profile"
        _record_log_failure(log_id, request_id, msg, result_status="error")
        raise HTTPException(status_code=404, detail=msg)

    # Route and execute request with profile context
    return await route_and_execute(
        deployments, body, headers, auth.logos_key, path, log_id,
        profile_id=auth.profile_id,
        request_id=request_id,
    )


async def auth_parse_log(request: Request, use_profile_auth: bool = False):
    """
    Authenticate, parse, and log incoming requests.

    This helper centralizes auth, body parsing, and logging for all endpoints.
    Used by /openai, /v1, and /jobs/* endpoints.

    Args:
        request: FastAPI request object
        use_profile_auth: If True, use profile-based auth and return AuthContext

    Returns:
        If use_profile_auth=False (default):
            (headers, logos_key, process_id, body, client_ip, log_id)
        If use_profile_auth=True:
            (headers, auth_context, body, client_ip, log_id)

    Raises:
        HTTPException(400): Invalid JSON body
        HTTPException(401): Missing or invalid authentication
    """
    # Parse body
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON payload must be an object")

    # Extract headers and client IP
    headers = dict(request.headers)
    client_ip = get_client_ip(request)

    # Authenticate
    if use_profile_auth:
        from logos.auth import authenticate_with_profile
        auth = authenticate_with_profile(headers)
        process_id = auth.process_id

        # Log request (still at process level for billing)
        log_id = None
        with DBManager() as db:
            r_log, c_log = db.log_usage(process_id, client_ip, body, headers)
            if c_log == 200:
                log_id = int(r_log["log-id"])

        return headers, auth, body, client_ip, log_id
    else:
        # For endpoints not requiring the profile-based authorization
        logos_key, process_id = authenticate_logos_key(headers)

        # Log request
        log_id = None
        with DBManager() as db:
            r_log, c_log = db.log_usage(process_id, client_ip, body, headers)
            if c_log == 200:
                log_id = int(r_log["log-id"])

        return headers, logos_key, process_id, body, client_ip, log_id


async def submit_job_request(path: str, request: Request) -> JSONResponse:
    """
    Accept a proxy request, persist it as a job, and launch async processing (poll for result via /jobs/{id}).

    Params:
        path: Upstream path to forward.
        request: Incoming FastAPI request containing headers/body.

    Returns:
        202 Accepted with job id and status URL.

    Raises:
        HTTPException(400/401) on invalid payload or auth.
    """
    # Auth with profile + logging
    headers, auth, json_data, client_ip, log_id = await auth_parse_log(request, use_profile_auth=True)

    # Persist job and run it asynchronously
    job_payload = JobSubmission(
        path=path,
        method=request.method,
        headers=headers,
        body=json_data,
        client_ip=client_ip,
        process_id=auth.process_id,
        profile_id=auth.profile_id,
    )
    job_id = JobService.create_job(job_payload)
    status_url = str(request.url_for("get_job_status", job_id=job_id))

    # Fire-and-forget: run the heavy proxy/classification pipeline off the request path.
    task = asyncio.create_task(process_job(job_id, path, headers, dict(json_data), client_ip, auth))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return JSONResponse(status_code=202, content={"job_id": job_id, "status_url": status_url, "profile_id": auth.profile_id})


async def process_job(job_id: int, path: str, headers: Dict[str, str], json_data: Dict[str, Any], client_ip: str, auth):
    """
    Execute a job and persist success or failure.

    Args:
        job_id: Job ID
        path: API path
        headers: Request headers
        json_data: Request body
        client_ip: Client IP address
        auth: AuthContext with profile information
    """
    try:
        JobService.mark_running(job_id)
        result = await execute_proxy_job(path, headers, json_data, client_ip, auth)
        JobService.mark_success(job_id, result)
    # Exception while processing the job is caught and persisted in the database
    except Exception as e:
        logging.exception("Job %s failed", job_id)
        JobService.mark_failed(job_id, str(e))
        return {"status_code": 500, "data": {"error": "Job failed"}}
    return result


async def execute_proxy_job(path: str, headers: Dict[str, str], json_data: Dict[str, Any], client_ip: str, auth) -> Dict[str, Any]:
    """
    Execute the proxy workflow using either PROXY MODE or RESOURCE MODE pipeline.
    Force non-streaming for async job execution.

    Args:
        path: API path
        headers: Request headers
        json_data: Request body
        client_ip: Client IP
        auth: AuthContext with profile information

    Returns:
        Serializable dict result with status_code and data.
    """
    headers = headers or dict()
    json_data = json_data or dict()

    # Log usage (at process level for billing)
    usage_id = None
    request_id = secrets.token_urlsafe(16)
    with DBManager() as db:
        r, c = db.log_usage(auth.process_id, client_ip, json_data, headers, request_id=request_id)
        if c != 200:
            logging.info("Error while logging a request: %s", r)
        else:
            usage_id = int(r["log-id"])
            db.update_log_entry_metrics(log_id=usage_id, timeout_s=json_data.get("timeout_s"))

    # Get available models for this profile - profile_id EXPLICITLY passed
    try:
        models = request_setup(headers, auth.logos_key, profile_id=auth.profile_id)
        models = await _filter_logosnode_deployments(models)
    except PermissionError as e:
        _record_log_failure(usage_id, request_id, str(e), result_status="error")
        return {"status_code": 401, "data": {"error": str(e)}}
    except ValueError as e:
        _record_log_failure(usage_id, request_id, str(e), result_status="error")
        return {"status_code": 400, "data": {"error": str(e)}}

    # Force non-streaming for jobs
    json_data["stream"] = False

    # Route and execute request (async job mode) with profile context
    return await route_and_execute(
        models, json_data, headers, auth.logos_key, path, usage_id,
        is_async_job=True,
        profile_id=auth.profile_id,
        request_id=request_id,
    )


# ============================================================================
# LOGOSNODE PROVIDER ENDPOINTS
# ============================================================================


def _is_tls_websocket(websocket: WebSocket) -> bool:
    if _logosnode_insecure_dev_mode_enabled():
        return True
    if websocket.url.scheme in {"wss", "https"}:
        return True
    forwarded = websocket.headers.get("x-forwarded-proto", "")
    forwarded_values = [item.strip().lower() for item in forwarded.split(",") if item.strip()]
    return "https" in forwarded_values or "wss" in forwarded_values


@app.post("/logosdb/providers/logosnode/register", tags=["logosnode"])
async def logosnode_register(data: LogosNodeRegisterRequest):
    """
    Root-only provider bootstrap endpoint for LogosWorkerNode providers.
    """
    _require_root_access(data.logos_key)

    provider_name = (data.provider_name or "").strip()
    if not provider_name:
        raise HTTPException(status_code=400, detail="provider_name is required")

    shared_key = secrets.token_urlsafe(48)
    with DBManager() as db:
        result, code = db.add_provider(
            logos_key=data.logos_key,
            provider_name=provider_name,
            base_url=(data.base_url or "").strip(),
            api_key=shared_key,
            auth_name="",
            auth_format="{}",
            provider_type="logosnode",
        )

    if code != 200:
        return JSONResponse(status_code=code, content=result)

    provider_id = result.get("provider-id")

    # Create logosnode_provider_keys entry so deployment queries work
    try:
        with DBManager() as db:
            db.sync_logosnode_capabilities(provider_id, [])
    except Exception:
        logger.exception("Failed to create logosnode_provider_keys for provider %s", provider_name)

    return {
        "provider_id": provider_id,
        "provider_name": provider_name,
        "provider_type": "logosnode",
        "shared_key": shared_key,
    }


@app.post("/logosdb/providers/logosnode/auth", tags=["logosnode"])
async def logosnode_auth(data: LogosNodeAuthRequest, request: Request):
    """
    Authenticate a LogosWorkerNode by its API key.

    The server resolves the provider from the key. The worker never needs
    to know or send a provider_id.
    """
    _require_tls_request(request)
    with DBManager() as db:
        provider = db.get_logosnode_provider_by_api_key(data.shared_key)

    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found for this API key")
    provider_type = _normalize_provider_type(provider.get("provider_type"))
    if provider_type != "logosnode":
        raise HTTPException(status_code=403, detail="Provider is not configured as logosnode")

    provider_id = provider["id"]
    worker_id = provider.get("name") or f"worker-{provider_id}"

    conflicting_session = await _logosnode_registry.get_conflicting_session(
        provider_id,
        worker_id,
        stale_after_seconds=_LOGOSNODE_STATS_STALE_AFTER_SECONDS,
    )
    if conflicting_session is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Worker '{conflicting_session.worker_id}' is already connected. "
                f"Stop the existing worker first."
            ),
        )
    token = await _logosnode_registry.issue_ticket(
        provider_id=provider_id,
        worker_id=worker_id,
        capabilities_models=data.capabilities_models,
        ttl_seconds=60,
    )
    return {
        "session_token": token,
        "ws_url": _build_logosnode_ws_url(request, token),
        "worker_id": worker_id,
        "expires_in_seconds": 60,
    }


@app.websocket("/logosdb/providers/logosnode/session")
async def logosnode_session(websocket: WebSocket, token: str):
    if not _is_tls_websocket(websocket):
        await websocket.close(code=1008, reason="TLS required")
        return

    ticket = await _logosnode_registry.consume_ticket(token)
    if ticket is None:
        await websocket.close(code=1008, reason="Invalid or expired token")
        return

    await websocket.accept()
    try:
        await _logosnode_registry.attach_session(ticket, websocket)
    except LogosNodeSessionConflictError as exc:
        await websocket.close(code=1008, reason=str(exc))
        return

    try:
        while True:
            payload = await websocket.receive_json()
            if not isinstance(payload, dict):
                continue
            msg_type = payload.get("type")
            if msg_type == "hello":
                await _logosnode_registry.on_hello(
                    provider_id=ticket.provider_id,
                    worker_id=str(payload.get("worker_id", "")).strip() or ticket.worker_id,
                    capabilities_models=payload.get("capabilities_models")
                    if isinstance(payload.get("capabilities_models"), list)
                    else None,
                )
            elif msg_type == "status":
                runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
                await _logosnode_registry.update_runtime(
                    provider_id=ticket.provider_id,
                    runtime=runtime,
                    capabilities_models=payload.get("capabilities_models")
                    if isinstance(payload.get("capabilities_models"), list)
                    else None,
                )
                _capture_logosnode_provider_snapshot(ticket.provider_id, runtime)
            elif msg_type == "event":
                await _logosnode_registry.append_event(
                    provider_id=ticket.provider_id,
                    event=payload.get("event") if isinstance(payload.get("event"), dict) else {},
                )
            elif msg_type == "heartbeat":
                await _logosnode_registry.mark_heartbeat(ticket.provider_id)
            elif msg_type == "command_result":
                await _logosnode_registry.on_command_result(ticket.provider_id, payload)
            elif msg_type == "stream_start":
                await _logosnode_registry.on_stream_start(ticket.provider_id, payload)
            elif msg_type == "stream_chunk":
                await _logosnode_registry.on_stream_chunk(ticket.provider_id, payload)
            elif msg_type == "stream_end":
                await _logosnode_registry.on_stream_end(ticket.provider_id, payload)
    except WebSocketDisconnect:
        pass
    finally:
        await _logosnode_registry.detach_session(ticket.provider_id, websocket)


@app.post("/logosdb/providers/logosnode/status", tags=["logosnode"])
async def logosnode_status(data: LogosNodeStatusRequest):
    _require_root_access(data.logos_key)
    try:
        return await _logosnode_registry.get_runtime_snapshot(data.provider_id)
    except LogosNodeOfflineError as exc:
        return JSONResponse(status_code=503, content={"error": str(exc)})


@app.post("/logosdb/providers/logosnode/devices", tags=["logosnode"])
async def logosnode_devices(data: LogosNodeStatusRequest):
    _require_root_access(data.logos_key)
    try:
        return {"devices": await _logosnode_registry.get_devices(data.provider_id)}
    except LogosNodeOfflineError as exc:
        return JSONResponse(status_code=503, content={"error": str(exc)})


@app.post("/logosdb/providers/logosnode/lanes", tags=["logosnode"])
async def logosnode_lanes(data: LogosNodeStatusRequest):
    _require_root_access(data.logos_key)
    try:
        return {"lanes": await _logosnode_registry.get_lanes(data.provider_id)}
    except LogosNodeOfflineError as exc:
        return JSONResponse(status_code=503, content={"error": str(exc)})


_LOGOSNODE_CMD_TIMEOUTS: dict[str, int] = {
    "apply_lanes": 180,
    "reconfigure_lane": 180,
    "sleep_lane": 30,
    "wake_lane": 120,
    "delete_lane": 30,
}


async def _dispatch_logosnode_command(provider_id: int, action: str, params: dict[str, Any] | None = None):
    try:
        timeout = _LOGOSNODE_CMD_TIMEOUTS.get(action, 20)
        return await _logosnode_registry.send_command(
            provider_id, action=action, params=params or {}, timeout_seconds=timeout,
        )
    except LogosNodeOfflineError as exc:
        return JSONResponse(status_code=503, content={"error": str(exc)})
    except LogosNodeCommandError as exc:
        return JSONResponse(status_code=502, content={"error": str(exc)})


@app.post("/logosdb/providers/logosnode/lanes/apply", tags=["logosnode"])
async def logosnode_apply_lanes(data: LogosNodeApplyLanesRequest):
    _require_root_access(data.logos_key)
    return await _dispatch_logosnode_command(
        provider_id=data.provider_id,
        action="apply_lanes",
        params={"lanes": data.lanes},
    )


@app.post("/logosdb/providers/logosnode/lanes/sleep", tags=["logosnode"])
async def logosnode_sleep_lane(data: LogosNodeSleepLaneRequest):
    _require_root_access(data.logos_key)
    return await _dispatch_logosnode_command(
        provider_id=data.provider_id,
        action="sleep_lane",
        params={"lane_id": data.lane_id, "level": data.level, "mode": data.mode},
    )


@app.post("/logosdb/providers/logosnode/lanes/wake", tags=["logosnode"])
async def logosnode_wake_lane(data: LogosNodeWakeLaneRequest):
    _require_root_access(data.logos_key)
    return await _dispatch_logosnode_command(
        provider_id=data.provider_id,
        action="wake_lane",
        params={"lane_id": data.lane_id},
    )


@app.post("/logosdb/providers/logosnode/lanes/delete", tags=["logosnode"])
async def logosnode_delete_lane(data: LogosNodeDeleteLaneRequest):
    _require_root_access(data.logos_key)
    return await _dispatch_logosnode_command(
        provider_id=data.provider_id,
        action="delete_lane",
        params={"lane_id": data.lane_id},
    )


@app.post("/logosdb/providers/logosnode/lanes/reconfigure", tags=["logosnode"])
async def logosnode_reconfigure_lane(data: LogosNodeReconfigureLaneRequest):
    _require_root_access(data.logos_key)
    return await _dispatch_logosnode_command(
        provider_id=data.provider_id,
        action="reconfigure_lane",
        params={"lane_id": data.lane_id, "updates": data.updates},
    )


# ============================================================================
# DATABASE MANAGEMENT ENDPOINTS
# ============================================================================


@app.post("/logosdb/add_service_proxy", tags=["admin"])
async def add_service_proxy(data: AddServiceProxyRequest):
    try:
        with DBManager() as db:
            db.is_root_initialized()
        if not DBManager.is_initialized():
            return {"error": "Database not initialized"}, 500
        lk = setup_proxy.add_service(**data.dict())
        if "error" in lk:
            return lk, 500
        return {"service-key": lk,}, 200
    except Exception as e:
        return {"error": f"{str(e)}"}, 500


@app.post("/logosdb/set_log", tags=["admin"])
async def set_log(data: SetLogRequest):
    with DBManager() as db:
        check, code = db.get_process_id(data.dict()["logos_key"])
        if "error" in check:
            return check, code
        if check["result"] != data.dict()["process_id"] and _fetch_role(data.dict()["logos_key"]) != "logos_admin":
            return {"error": "Missing authentication to set log"}
        return db.set_process_log(data.dict()["process_id"], data.dict()["set_log"])

def _fetch_role(logos_key: str) -> str | None:
    with DBManager() as db:
        user = db.get_user_by_logos_key(logos_key)
    return user["role"] if user else None

@app.post("/logosdb/add_provider", tags=["admin"])
async def add_provider(data: AddProviderRequest):
    with DBManager() as db:
        result = db.add_provider(**data.dict())
    await refresh_pipeline_runtime_state()
    return result


@app.post("/logosdb/update_provider_sdi_config", tags=["admin"])
async def update_provider_sdi_config(data: UpdateProviderSdiConfigRequest):
    with DBManager() as db:
        result = db.update_provider_sdi_config(**data.dict())
    await refresh_pipeline_runtime_state()
    return result


@app.post("/logosdb/add_profile", tags=["admin"])
async def add_profile(data: AddProfileRequest):
    with DBManager() as db:
        return db.add_profile(**data.dict())


@app.post("/logosdb/connect_process_provider", tags=["admin"])
async def connect_process_provider(data: ConnectProcessProviderRequest):
    with DBManager() as db:
        result = db.connect_process_provider(**data.dict())
    await refresh_pipeline_runtime_state()
    return result


@app.post("/logosdb/connect_process_model", tags=["admin"])
async def connect_process_model(data: ConnectProcessModelRequest):
    with DBManager() as db:
        result = db.connect_process_model(**data.dict())
    await refresh_pipeline_runtime_state()
    return result


@app.post("/logosdb/connect_profile_model", tags=["admin"])
async def connect_profile_model(data: ConnectProcessModelRequest):
    with DBManager() as db:
        result = db.connect_profile_model(**data.dict())
    await refresh_pipeline_runtime_state()
    return result


@app.post("/logosdb/connect_service_process", tags=["admin"])
async def connect_service_process(data: ConnectServiceProcessRequest):
    with DBManager() as db:
        return db.connect_service_process(**data.dict())


@app.post("/logosdb/connect_model_provider", tags=["admin"])
async def connect_model_provider(data: ConnectModelProviderRequest):
    with DBManager() as db:
        result = db.connect_model_provider(**data.dict())
    await refresh_pipeline_runtime_state()
    return result


@app.post("/logosdb/connect_model_api", tags=["admin"])
async def connect_model_api(data: ConnectModelApiRequest):
    with DBManager() as db:
        result = db.connect_model_api(**data.dict())
    await refresh_pipeline_runtime_state()
    return result


@app.post("/logosdb/add_model", tags=["admin"])
async def add_model(data: AddModelRequest):
    with DBManager() as db:
        back = db.add_model(**data.dict())
    await refresh_pipeline_runtime_state(rebuild_model_classifier=True)
    return back


@app.post("/logosdb/add_full_model", tags=["admin"])
async def add_full_model(data: AddFullModelRequest):
    with DBManager() as db:
        back = db.add_full_model(**data.dict())
    await refresh_pipeline_runtime_state(rebuild_model_classifier=True)
    return back


@app.post("/logosdb/update_model", tags=["admin"])
async def update_model(data: GiveFeedbackRequest):
    with DBManager() as db:
        back = db.update_model_weights(**data.dict())
    await refresh_pipeline_runtime_state(rebuild_model_classifier=True)
    return back


@app.post("/logosdb/delete_model", tags=["admin"])
async def delete_model(data: DeleteModelRequest):
    with DBManager() as db:
        back = db.delete_model(**data.dict())
    await refresh_pipeline_runtime_state(rebuild_model_classifier=True)
    return back


@app.post("/logosdb/get_model", tags=["admin"])
async def get_model(data: GetModelRequest):
    with DBManager() as db:
        payload = db.get_model(data.id)
    return JSONResponse(content=jsonable_encoder(payload), status_code=200)


@app.post("/logosdb/add_policy", tags=["admin"])
async def add_policy(data: AddPolicyRequest):
    with DBManager() as db:
        return db.add_policy(**data.dict())


@app.post("/logosdb/update_policy", tags=["admin"])
async def update_policy(data: UpdatePolicyRequest):
    with DBManager() as db:
        return db.update_policy(**data.dict())


@app.post("/logosdb/delete_policy", tags=["admin"])
async def delete_policy(data: DeletePolicyRequest):
    with DBManager() as db:
        return db.delete_policy(**data.dict())


@app.post("/logosdb/get_policy", tags=["admin"])
async def add_model(data: GetPolicyRequest):
    with DBManager() as db:
        return db.get_policy(**data.dict()), 200


@app.post("/logosdb/add_service", tags=["admin"])
async def add_service(data: AddServiceRequest):
    with DBManager() as db:
        return db.add_service(**data.dict())


@app.post("/logosdb/get_process_id", tags=["admin"])
async def get_process_id(data: GetProcessIdRequest):
    with DBManager() as db:
        return db.get_process_id(data.logos_key)

@app.get("/me", tags=["users"])
async def get_me(request: Request):
    logos_key, _ = authenticate_logos_key(dict(request.headers))
    with DBManager() as db:
        user = db.get_user_by_logos_key(logos_key)
    if user is None:
        raise HTTPException(
            status_code=404,
            detail="No user linked to this key. Service keys cannot log into the UI."
        )
    return {
        "user_id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "role": user["role"],
        "teams": user["teams"],
    }

@app.patch("/users/{user_id}/role", tags=["users"])
async def patch_user_role(user_id: int, body: UpdateRoleRequest, request: Request):
    """Change a user's role (for Logos Admin only)"""
    logos_key = authenticate_logos_key(dict(request.headers))[0]
    with DBManager() as db:
        require_logos_admin_key(logos_key, db)
        result, status = db.set_user_role(user_id, body.role)
    if status != 200:
        raise HTTPException(status_code=status, detail=result.get("error"))
    return result

@app.get("/users", tags=["users"])
async def list_users(request: Request):
    logos_key = authenticate_logos_key(dict(request.headers))[0]
    with DBManager() as db:
        require_logos_admin_key(logos_key, db)
        users = db.list_users()
    return users


@app.post("/users", tags=["users"])
async def create_user(body: CreateUserRequest, request: Request):
    logos_key = authenticate_logos_key(dict(request.headers))[0]
    valid_roles = {"app_developer", "app_admin", "logos_admin"}
    if body.role not in valid_roles:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid role. Must be one of: {sorted(valid_roles)}",
        )
    with DBManager() as db:
        require_logos_admin_key(logos_key, db)
        user_dict, new_key, status = db.create_user(
            body.username, body.prename, body.name, body.email, body.role
        )
    if status != 200:
        raise HTTPException(status_code=status, detail=user_dict.get("error"))
    return {**user_dict, "logos_key": new_key}


@app.delete("/users/{user_id}", tags=["users"])
async def delete_user(user_id: int, request: Request):
    logos_key = authenticate_logos_key(dict(request.headers))[0]
    with DBManager() as db:
        require_logos_admin_key(logos_key, db)
        result, status = db.delete_user(user_id)
    if status != 200:
        raise HTTPException(status_code=status, detail=result.get("error"))
    return result

@app.post("/logosdb/get_role", tags=["admin"])
async def get_role(data: GetRole):
    with DBManager() as db:
        return db.get_role(**data.dict())


@app.post("/logosdb/get_providers", tags=["admin"])
async def get_providers(data: LogosKeyModel):
    with DBManager() as db:
        return db.get_provider_info(**data.dict()), 200


@app.post("/logosdb/get_general_provider_stats", tags=["admin"])
async def get_general_provider_stats(data: LogosKeyModel):
    with DBManager() as db:
        return db.get_general_provider_stats(**data.dict())


@app.post("/logosdb/get_models", tags=["admin"])
async def get_models(data: LogosKeyModel):
    with DBManager() as db:
        return db.get_models_info(**data.dict()), 200


@app.post("/logosdb/get_policies", tags=["admin"])
async def get_models(data: LogosKeyModel):
    with DBManager() as db:
        return db.get_policy_info(**data.dict()), 200


@app.post("/logosdb/get_general_model_stats", tags=["admin"])
async def get_general_model_stats(data: LogosKeyModel):
    with DBManager() as db:
        return db.get_general_model_stats(**data.dict())


@app.post("/logosdb/export", tags=["admin"])
async def export(data: LogosKeyModel):
    with DBManager() as db:
        payload, status = db.export(**data.dict())
    return JSONResponse(content=jsonable_encoder(payload), status_code=status)


@app.post("/logosdb/import", tags=["admin"])
async def import_json(data: GetImportDataRequest):
    with DBManager() as db:
        return db.import_from_json(**data.dict())


@app.get("/forward_host", tags=["admin"])
def route_handler(request: Request):
    host = request.headers.get("x-forwarded-host") or request.headers.get("forwarded")
    return {"host": host}


@app.post("/logosdb/add_billing", tags=["admin"])
async def add_billing(data: AddBillingRequest):
    with DBManager() as db:
        return db.add_billing(**data.dict())


@app.post("/logosdb/generalstats", tags=["admin"])
async def generalstats(data: LogosKeyModel):
    with DBManager() as db:
        return db.generalstats(**data.dict())


async def _build_request_log_stats_response(request: Request) -> JSONResponse:
    """
    Aggregate request log metrics for dashboards.

    Args:
        request: FastAPI request; must include authentication headers.
        Body supports:
            - start_date / end_date: ISO strings for the time window (defaults to last 30 days)
            - target_buckets: hint for how granular the time-series should be
            - include_raw_rows: optional raw rows for debugging (capped)

    Auth:
        - `logos_key` header (preferred), or
        - `Authorization: Bearer <logos_key>`

    Returns:
        Tuple[dict, int]: (payload, status) from DBManager.get_request_log_stats.
    """
    headers = dict(request.headers)
    logos_key, _ = authenticate_logos_key(headers)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}

    start_date = body.get("start_date")
    end_date = body.get("end_date")
    target_buckets = body.get("target_buckets", 120)

    with DBManager() as db:
        payload, status = db.get_request_log_stats(
            logos_key,
            start_date=start_date,
            end_date=end_date,
            target_buckets=target_buckets,
        )
        return JSONResponse(
            content=payload,
            status_code=status,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
            },
        )


@app.post("/logosdb/request_log_stats", tags=["admin"])
async def request_log_stats(request: Request):
    return await _build_request_log_stats_response(request)


@app.options("/logosdb/request_log_stats", tags=["admin"])
async def request_log_stats_options():
    """
    Local testing helper to dodge CORS preflight failures.
    Safe to remove once Traefik/CORS is sorted.
    """
    return JSONResponse(
        content={},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
        },
    )


@app.get("/logosdb/scheduler_state", tags=["admin"])
async def scheduler_state(request: Request):
    """
    Debug endpoint to inspect in-memory scheduler and LogosWorkerNode capacity state.
    """
    headers = dict(request.headers)
    authenticate_logos_key(headers)

    if not _pipeline or not _logosnode_facade:
        return JSONResponse(content={"error": "Scheduler not initialized"}, status_code=503)

    payload = {
        "queue_total": _pipeline.scheduler.get_total_queue_depth(),
        "logosnode": _logosnode_facade.debug_state(),
    }
    return JSONResponse(content=payload, status_code=200)


@app.post("/logosdb/get_ollama_vram_stats", tags=["admin"])
async def get_ollama_vram_stats(request: Request):
    """
    Return live LogosWorkerNode provider VRAM usage for dashboards.

    Request body:
    {
        "day": "2025-01-05",                    # Optional, ignored for runtime-backed stats
        "bucket_seconds": 5                     # Optional, ignored for compatibility
    }

    Response:
    {
        "providers": [
            {
                "url": "http://host.docker.internal:11435",
                "data": [
                    {"timestamp": "2025-01-05T10:00:00Z", "vram_mb": 4608},
                    ...
                ]
            }
        ]
    }
    """
    headers = dict(request.headers)
    logos_key, _ = authenticate_logos_key(headers)

    day = _today_utc()

    # Tolerate empty/no-body requests for compatibility with older clients.
    try:
        body = await request.json()
        if isinstance(body, dict) and isinstance(body.get("day"), str) and body.get("day", "").strip():
            day = body["day"].strip()
    except json.JSONDecodeError:
        pass

    return JSONResponse(
        content=_build_live_local_provider_vram_payload(logos_key, day=day, after_snapshot_id=0),
        status_code=200,
    )


@app.options("/logosdb/get_ollama_vram_stats", tags=["admin"])
async def get_ollama_vram_stats_options():
    """CORS preflight for get_ollama_vram_stats."""
    return JSONResponse(
        content={},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, logos_key",
        }
    )


# ============================================================================
# OPENAI-COMPATIBLE MODEL LISTING
# ============================================================================

@app.get("/v1/models", tags=["user-facing"])
async def list_models(request: Request):
    """
    List models accessible to the authenticated user (OpenAI-compatible).

    Returns an OpenAI-compatible response listing all models the user's
    current profile has access to via profile_model_permissions.

    Returns:
        JSONResponse matching the OpenAI GET /v1/models spec.
    """
    from logos.auth import authenticate_with_profile
    auth = authenticate_with_profile(dict(request.headers))

    with DBManager() as db:
        models = db.get_models_for_profile(auth.profile_id)

    data = [
        {
            "id": model["name"],
            "object": "model",
            "created": _SERVER_START_TIME,
            "owned_by": "logos",
        }
        for model in models
    ]

    return JSONResponse(content={"object": "list", "data": data})


@app.get("/v1/models/{model_id:path}", tags=["user-facing"])
async def retrieve_model(model_id: str, request: Request):
    """
    Retrieve a single model by name (OpenAI-compatible).

    Verifies the authenticated user has access to the requested model
    through their profile's model permissions.

    Params:
        model_id: The model name (used as the OpenAI-style model id).
        request: Incoming request.

    Returns:
        JSONResponse matching the OpenAI GET /v1/models/{model} spec.

    Raises:
        HTTPException(404): Model not found or user lacks access.
    """
    from logos.auth import authenticate_with_profile
    auth = authenticate_with_profile(dict(request.headers))

    with DBManager() as db:
        model = db.get_model_for_profile(auth.profile_id, model_id)
        if not model:
            models = db.get_models_for_profile(auth.profile_id)
            canonical_model_name = _resolve_requested_model_name(
                model_id,
                [str(entry.get("name") or "").strip() for entry in models],
            )
            if canonical_model_name is not None:
                model = next((entry for entry in models if entry.get("name") == canonical_model_name), None)

    if not model:
        raise HTTPException(status_code=404, detail="Model not found or access denied")

    return JSONResponse(content={
        "id": model["name"],
        "object": "model",
        "created": _SERVER_START_TIME,
        "owned_by": "logos",
    })


# ============================================================================
# MAIN API ENDPOINTS
# ============================================================================

@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"], tags=["user-facing"])
async def logos_service_sync(path: str, request: Request):
    """
    Dynamic proxy for OpenAI-compatible API endpoints (/v1/*).
    Supports both PROXY and RESOURCE modes with streaming.
    """
    return await handle_sync_request(f"v1/{path}", request)


@app.api_route("/v2/{path:path}", methods=["GET", "POST", "PUT", "DELETE"], tags=["user-facing"])
async def logos_service_v2_sync(path: str, request: Request):
    """
    Dynamic proxy for Cohere-compatible API endpoints (/v2/embed, /v2/rerank).
    """
    return await handle_sync_request(f"v2/{path}", request)


@app.api_route("/openai/{path:path}", methods=["GET", "POST", "PUT", "DELETE"], tags=["user-facing"])
async def logos_service_long_sync(request: Request, path: str = None):
    """
    Dynamic proxy for LLM API endpoints (OpenAI-compatible paths).
    Supports two modes:
    - PROXY MODE: Direct forwarding to provider (no classification/scheduling)
    - RESOURCE MODE: Classification + scheduling with SDI-aware pipeline

    :param request: Request object containing headers, body, and client metadata
    :param path: API endpoint path (e.g., 'chat/completions', 'completions', 'embeddings')
    :return: StreamingResponse for streaming requests, JSONResponse for synchronous requests
    """
    return await handle_sync_request(f"v1/{path}", request)


# vLLM non-prefixed endpoints (not part of OpenAI API spec, but user-facing).
# These are canonical paths for pooling, scoring, reranking, and tokenization.
async def _handle_vllm_native(request: Request):
    """Forward to vLLM using the original request path."""
    path = request.url.path.lstrip("/")
    return await handle_sync_request(path, request)

for _vllm_path in ("/pooling", "/score", "/rerank", "/tokenize", "/detokenize"):
    app.add_api_route(
        _vllm_path,
        _handle_vllm_native,
        methods=["POST"],
        tags=["user-facing"],
        name=f"vllm_native_{_vllm_path.lstrip('/')}",
    )


@app.api_route("/jobs/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"], tags=["user-facing"])
async def logos_service_async(path: str, request: Request):
    """
    Async job-based proxy for long running/low-priority requests.

    Params:
        path: Upstream path to forward.
        request: Incoming request.

    Returns:
        202 with job metadata; poll /jobs/{id} for result.
    """
    return await submit_job_request(f"v1/{path}", request)


@app.api_route("/jobs/v2/{path:path}", methods=["GET", "POST", "PUT", "DELETE"], tags=["user-facing"])
async def logos_service_v2_async(path: str, request: Request):
    """Async job-based proxy for Cohere-compatible endpoints."""
    return await submit_job_request(f"v2/{path}", request)


@app.api_route("/jobs/openai/{path:path}", methods=["GET", "POST", "PUT", "DELETE"], tags=["user-facing"])
async def logos_service_long_async(path: str, request: Request):
    """
    Async job-based proxy for OpenAI-compatible, long running/low-priority requests.

    Params:
        path: Upstream path to forward.
        request: Incoming request.

    Returns:
        202 with job metadata; poll /jobs/{id} for result.
    """
    return await submit_job_request(f"v1/{path}", request)


@app.get("/jobs/{job_id}", tags=["user-facing"])
async def get_job_status(job_id: int, request: Request):
    """
    Return current state of a submitted job, including result or error when finished.

    Uses profile-based authorization - you can only view jobs created by your current profile.

    Params:
        job_id: Identifier of the async job.
        request: Incoming request

    Returns:
        Job status, result/error, and timestamps.

    Raises:
        HTTPException(401/403/404) on auth or missing job.
    """
    # Profile-based auth
    from logos.auth import authenticate_with_profile
    auth = authenticate_with_profile(dict(request.headers))

    job = JobService.fetch(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    # Authorization checks
    job_process_id = job.get("process_id")
    job_profile_id = job.get("profile_id")

    # 1. Job must belong to this process
    if job_process_id != auth.process_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this job")

    # 2. Job must belong to this profile
    if job_profile_id != auth.profile_id:
        raise HTTPException(
            status_code=403,
            detail="Job belongs to a different profile. Use the correct use_profile header."
        )

    return {
        "job_id": job_id,
        "status": job["status"],
        "result": job["result_payload"] if job["status"] == JobStatus.SUCCESS.value else None,
        "error": job["error_message"] if job["status"] == JobStatus.FAILED.value else None,
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "profile_id": job_profile_id,
    }


@app.post("/logosdb/latest_requests", tags=["admin"])
async def latest_requests(request: Request):
    """
    Fetch the latest 10 requests for the dashboard stack.
    """
    headers = dict(request.headers)
    logos_key, _ = authenticate_logos_key(headers)

    with DBManager() as db:
        payload, status = db.get_latest_requests(logos_key, limit=10)
        return JSONResponse(content=payload, status_code=status)


@app.post("/logosdb/request_logs", tags=["admin"])
async def request_logs(request: Request):
    """
    Fetch request logs by request_id for performance replay correlation.
    """
    headers = dict(request.headers)
    logos_key, _ = authenticate_logos_key(headers)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(content={"error": "Invalid JSON body"}, status_code=400)

    if not isinstance(body, dict):
        return JSONResponse(content={"error": "JSON payload must be an object"}, status_code=400)

    request_ids = body.get("request_ids")
    if not isinstance(request_ids, list) or any(not isinstance(item, str) for item in request_ids):
        return JSONResponse(content={"error": "request_ids must be a list of strings"}, status_code=400)

    with DBManager() as db:
        payload, status = db.get_request_logs(logos_key, request_ids)
        return JSONResponse(content=payload, status_code=status)


@app.options("/logosdb/latest_requests", tags=["admin"])
async def latest_requests_options():
    return JSONResponse(
        content={},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
        },
    )


@app.options("/logosdb/request_logs", tags=["admin"])
async def request_logs_options():
    return JSONResponse(
        content={},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
        },
    )


# ============================================================================
# WEBSOCKET: Unified stats stream  (/ws/stats)
# ============================================================================
# Replaces the three polling HTTP calls from the statistics page with a single
# persistent WebSocket connection that pushes lightweight delta updates.
#
# Protocol (server → client):
#   { "type": "vram",     "payload": <same shape as GET /logosdb/get_ollama_vram_stats> }
#   { "type": "requests", "payload": <same shape as POST /logosdb/latest_requests> }
#
# Protocol (client → server):
#   { "action": "set_vram_day", "day": "2025-06-15" }  – change the VRAM day filter
#   { "action": "ping" }                                – keepalive (server replies pong)
#
# Auth: pass `?key=<logos_key>` as a query parameter when opening the socket.
# ============================================================================

_ws_stats_connections: Set[WebSocket] = set()


def _build_vram_signature(providers: list) -> str:
    """Deterministic signature of VRAM provider data for change detection."""
    parts = []
    for p in sorted(providers, key=lambda x: x.get("name", "")):
        data = p.get("data", [])
        last = data[-1] if data else {}
        models_str = "|".join(
            f"{m.get('name', '')}:{m.get('size_vram_mb', m.get('size_vram', ''))}"
            for m in (last.get("loaded_models") or [])
        ) if isinstance(last.get("loaded_models"), list) else ""
        parts.append(
            f"{p.get('name', '')}::{p.get('connection_state', '')}::"
            f"{(p.get('runtime_modes') or [])}::{last.get('timestamp', '')}::"
            f"{last.get('used_vram_mb', last.get('vram_mb', ''))}::"
            f"{last.get('remaining_vram_mb', '')}::"
            f"{last.get('total_vram_mb', '')}::{models_str}"
        )
    return "||".join(parts)


def _requests_signature(requests_list: list) -> str:
    """Quick hash of request IDs + statuses + timestamps for change detection."""
    parts = []
    for r in requests_list:
        rid = str(r.get("request_id", ""))
        status = str(r.get("status", ""))
        sched = str(r.get("scheduled_ts", ""))
        done = str(r.get("request_complete_ts", ""))
        parts.append(f"{rid}:{status}:{sched}:{done}")
    return ",".join(parts)


def _parse_iso_utc(value: Optional[str]) -> Optional[datetime.datetime]:
    """Parse an ISO timestamp into UTC datetime (or return None on invalid input)."""
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


def _default_timeline_window() -> Tuple[str, str, int]:
    """Default timeline window: trailing 30 days, target 120 buckets."""
    end_dt = datetime.datetime.now(datetime.timezone.utc)
    start_dt = end_dt - datetime.timedelta(days=30)
    return start_dt.isoformat(), end_dt.isoformat(), 120


@app.websocket("/ws/stats")
async def ws_stats(websocket: WebSocket):
    """
    Unified WebSocket endpoint for statistics page.
    Streams VRAM snapshots and latest-requests with change detection so only
    actual updates are pushed.
    """
    # --- Auth via query param ---
    key = websocket.query_params.get("key", "")
    if not key:
        await websocket.close(code=4001, reason="Missing key query parameter")
        return

    try:
        logos_key, _ = authenticate_logos_key({"logos_key": key})
    except HTTPException:
        await websocket.close(code=4003, reason="Invalid logos key")
        return

    await websocket.accept()
    _ws_stats_connections.add(websocket)
    logger.info("[ws/stats] Client connected (%d total)", len(_ws_stats_connections))

    # Per-connection state
    vram_day: Optional[str] = None  # Will be set by client or default to today
    prev_vram_sig = ""
    prev_req_sig = ""

    async def _push_vram():
        nonlocal prev_vram_sig, vram_day
        day = vram_day or _today_utc()
        try:
            payload = _build_live_local_provider_vram_payload(logos_key, day=day, after_snapshot_id=0)
            if payload.get("providers"):
                sig = _build_vram_signature(payload["providers"])
                if sig != prev_vram_sig:
                    prev_vram_sig = sig
                    await websocket.send_json({"type": "vram", "payload": payload})
        except Exception as exc:
            logger.warning("[ws/stats] VRAM push error: %s", exc)

    async def _push_requests():
        nonlocal prev_req_sig
        try:
            with DBManager() as db:
                payload, status = db.get_latest_requests(logos_key, limit=10)
            if status == 200:
                reqs = payload.get("requests", [])
                sig = _requests_signature(reqs)
                if sig != prev_req_sig:
                    prev_req_sig = sig
                    await websocket.send_json({"type": "requests", "payload": payload})
        except Exception as exc:
            logger.warning("[ws/stats] Requests push error: %s", exc)

    # Background push loop
    async def _push_loop():
        tick = 0
        while True:
            try:
                # Push latest requests every 2s, VRAM every 5s
                await _push_requests()
                if tick % 5 == 0:
                    await _push_vram()
                tick += 1
                await asyncio.sleep(1)
            except (WebSocketDisconnect, RuntimeError):
                break
            except Exception as exc:
                logger.warning("[ws/stats] Push loop error: %s", exc)
                await asyncio.sleep(2)

    push_task = asyncio.create_task(_push_loop())

    try:
        # Listen for client messages (day changes, pings)
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            action = msg.get("action")
            if action == "set_vram_day":
                new_day = msg.get("day")
                if new_day and isinstance(new_day, str):
                    vram_day = new_day
                    prev_vram_sig = ""  # Force re-push on day change
                    await _push_vram()
            elif action == "ping":
                await websocket.send_json({"type": "pong"})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        push_task.cancel()
        _ws_stats_connections.discard(websocket)
        logger.info("[ws/stats] Client disconnected (%d remaining)", len(_ws_stats_connections))


_ws_stats_v2_connections: Set[WebSocket] = set()


@app.websocket("/ws/stats/v2")
async def ws_stats_v2(websocket: WebSocket):
    """
    Incremental websocket stream for statistics (v2).

    Messages (server -> client):
      - vram_init: full VRAM day snapshot with cursor
      - vram_delta: only new VRAM rows since cursor
      - timeline_init: request_log_stats payload for selected range
      - timeline_delta: enqueue-event deltas since cursor
      - requests: latest requests list (same shape as v1)
      - pong

    Client init options:
      - timeline_deltas (bool, default true): when false, the server skips
        periodic timeline delta polling for this connection.
    """
    key = websocket.query_params.get("key", "")
    if not key:
        await websocket.close(code=4001, reason="Missing key query parameter")
        return

    try:
        logos_key, _ = authenticate_logos_key({"logos_key": key})
    except HTTPException:
        await websocket.close(code=4003, reason="Invalid logos key")
        return

    await websocket.accept()
    _ws_stats_v2_connections.add(websocket)
    logger.info("[ws/stats/v2] Client connected (%d total)", len(_ws_stats_v2_connections))

    vram_day: str = "all"
    vram_cursor: int = 0

    timeline_start_iso, timeline_end_iso, timeline_target_buckets = _default_timeline_window()
    timeline_window_seconds = 30 * 24 * 3600.0
    timeline_bucket_seconds = 60
    timeline_live = True
    timeline_deltas_enabled = False
    timeline_cursor_ts = timeline_end_iso
    timeline_cursor_request_id = ""

    prev_req_sig = ""
    stats_initialized = False

    def _coerce_bool(value: Any, default: bool = True) -> bool:
        """Best-effort boolean parser for websocket client flags."""
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        return default

    def _set_timeline_state(start_iso: str, end_iso: str, target_buckets: Any) -> Tuple[bool, Optional[str]]:
        nonlocal timeline_start_iso, timeline_end_iso
        nonlocal timeline_target_buckets, timeline_window_seconds
        nonlocal timeline_live, timeline_cursor_ts, timeline_cursor_request_id

        start_dt = _parse_iso_utc(start_iso)
        end_dt = _parse_iso_utc(end_iso)
        if not start_dt or not end_dt:
            return False, "Invalid start/end timestamp format"
        if start_dt >= end_dt:
            return False, "Timeline start must be before end"

        now_dt = datetime.datetime.now(datetime.timezone.utc)
        if end_dt > now_dt:
            end_dt = now_dt
            if start_dt >= end_dt:
                start_dt = end_dt - datetime.timedelta(minutes=1)

        timeline_start_iso = start_dt.isoformat()
        timeline_end_iso = end_dt.isoformat()
        try:
            parsed_target_buckets = int(target_buckets or 120)
        except (TypeError, ValueError):
            parsed_target_buckets = 120

        timeline_target_buckets = max(1, parsed_target_buckets)
        timeline_window_seconds = (end_dt - start_dt).total_seconds()
        timeline_live = (now_dt - end_dt) <= datetime.timedelta(minutes=2)
        timeline_cursor_ts = timeline_end_iso
        timeline_cursor_request_id = ""
        return True, None

    async def _send_vram_init() -> None:
        nonlocal vram_cursor
        try:
            payload = _build_live_local_provider_vram_payload(
                logos_key,
                day=vram_day,
                after_snapshot_id=0,
            )
            vram_cursor = int(payload.get("last_snapshot_id") or 0)
            await websocket.send_json({"type": "vram_init", "payload": payload})
        except Exception as exc:
            logger.warning("[ws/stats/v2] VRAM init error: %s", exc)
            await websocket.send_json({
                "type": "vram_init",
                "payload": {"error": "Failed to load VRAM data"},
            })

    async def _push_vram_delta() -> None:
        nonlocal vram_cursor
        try:
            payload = _build_live_local_provider_vram_payload(
                logos_key,
                day=vram_day,
                after_snapshot_id=vram_cursor,
            )
            providers = payload.get("providers") or []
            next_cursor = int(payload.get("last_snapshot_id") or vram_cursor or 0)
            if providers or next_cursor != vram_cursor:
                vram_cursor = next_cursor
                await websocket.send_json({"type": "vram_delta", "payload": payload})
        except Exception as exc:
            logger.warning("[ws/stats/v2] VRAM delta push error: %s", exc)

    async def _send_timeline_init() -> None:
        nonlocal timeline_bucket_seconds
        nonlocal timeline_cursor_ts, timeline_cursor_request_id
        try:
            with DBManager() as db:
                payload, status = db.get_request_log_stats(
                    logos_key,
                    start_date=timeline_start_iso,
                    end_date=timeline_end_iso,
                    target_buckets=timeline_target_buckets,
                )
                events_payload, events_status = db.get_request_enqueues_in_range(
                    logos_key,
                    start_ts=timeline_start_iso,
                    end_ts=timeline_end_iso,
                    limit=200000,
                )
            if status != 200:
                await websocket.send_json({
                    "type": "timeline_init",
                    "payload": {"error": payload.get("error", "Failed to load timeline data")},
                })
                return

            timeline_bucket_seconds = int(payload.get("bucketSeconds") or timeline_bucket_seconds)
            timeline_cursor_ts = timeline_end_iso
            timeline_cursor_request_id = ""
            payload["cursor"] = {
                "enqueue_ts": timeline_cursor_ts,
                "request_id": timeline_cursor_request_id,
            }
            payload["events"] = events_payload.get("events", []) if events_status == 200 else []
            await websocket.send_json({"type": "timeline_init", "payload": payload})
        except Exception as exc:
            logger.warning("[ws/stats/v2] Timeline init error: %s", exc)
            await websocket.send_json({
                "type": "timeline_init",
                "payload": {"error": "Failed to load timeline data"},
            })

    async def _push_timeline_delta() -> None:
        nonlocal timeline_start_iso, timeline_end_iso
        nonlocal timeline_cursor_ts, timeline_cursor_request_id
        if not timeline_live:
            return

        now_dt = datetime.datetime.now(datetime.timezone.utc)
        until_iso = now_dt.isoformat()

        try:
            with DBManager() as db:
                payload, status = db.get_request_enqueues_deltas(
                    logos_key,
                    after_enqueue_ts=timeline_cursor_ts,
                    after_request_id=timeline_cursor_request_id,
                    until_ts=until_iso,
                    limit=5000,
                )
            if status != 200:
                return

            cursor = payload.get("cursor") or {}
            if cursor.get("enqueue_ts") is not None:
                timeline_cursor_ts = cursor.get("enqueue_ts")
            if cursor.get("request_id") is not None:
                timeline_cursor_request_id = str(cursor.get("request_id") or "")

            events = payload.get("events") or []
            if not events:
                return

            timeline_end_iso = until_iso
            start_dt = now_dt - datetime.timedelta(seconds=timeline_window_seconds)
            timeline_start_iso = start_dt.isoformat()

            await websocket.send_json({
                "type": "timeline_delta",
                "payload": {
                    "events": events,
                    "cursor": {
                        "enqueue_ts": timeline_cursor_ts,
                        "request_id": timeline_cursor_request_id,
                    },
                    "bucketSeconds": timeline_bucket_seconds,
                    "range": {
                        "start": timeline_start_iso,
                        "end": timeline_end_iso,
                    },
                },
            })
        except Exception as exc:
            logger.warning("[ws/stats/v2] Timeline delta push error: %s", exc)

    async def _push_requests(force: bool = False) -> None:
        nonlocal prev_req_sig
        try:
            with DBManager() as db:
                payload, status = db.get_latest_requests(logos_key, limit=10)
            if status != 200:
                return

            reqs = payload.get("requests", [])
            sig = _requests_signature(reqs)
            if force or sig != prev_req_sig:
                prev_req_sig = sig
                await websocket.send_json({"type": "requests", "payload": payload})
        except Exception as exc:
            logger.warning("[ws/stats/v2] Requests push error: %s", exc)

    async def _push_loop():
        nonlocal stats_initialized
        tick = 0
        while True:
            try:
                if not stats_initialized:
                    await asyncio.sleep(1)
                    continue
                if tick % 2 == 0:
                    await _push_requests()
                    if timeline_deltas_enabled:
                        await _push_timeline_delta()
                if tick % 5 == 0:
                    await _push_vram_delta()

                tick += 1
                await asyncio.sleep(1)
            except (WebSocketDisconnect, RuntimeError):
                break
            except Exception as exc:
                logger.warning("[ws/stats/v2] Push loop error: %s", exc)
                await asyncio.sleep(2)

    push_task = asyncio.create_task(_push_loop())

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            action = msg.get("action")
            if action == "init":
                stats_initialized = False
                requested_day = msg.get("vram_day")
                if isinstance(requested_day, str) and requested_day.strip():
                    vram_day = requested_day
                vram_cursor = 0
                timeline_deltas_enabled = _coerce_bool(msg.get("timeline_deltas"), default=True)

                timeline_cfg = msg.get("timeline") or {}
                start_iso = timeline_cfg.get("start")
                end_iso = timeline_cfg.get("end")
                target_buckets = timeline_cfg.get("target_buckets", 120)
                if not start_iso or not end_iso:
                    start_iso, end_iso, target_buckets = _default_timeline_window()
                ok, err_msg = _set_timeline_state(str(start_iso), str(end_iso), target_buckets)
                if not ok:
                    await websocket.send_json({
                        "type": "timeline_init",
                        "payload": {"error": err_msg or "Invalid timeline range"},
                    })
                else:
                    await _send_timeline_init()

                await _send_vram_init()
                await _push_requests(force=True)
                stats_initialized = True
            elif action == "set_vram_day":
                new_day = msg.get("day")
                if isinstance(new_day, str) and new_day.strip():
                    vram_day = new_day
                    vram_cursor = 0
                    await _send_vram_init()
            elif action == "set_timeline_range":
                start_iso = msg.get("start")
                end_iso = msg.get("end")
                target_buckets = msg.get("target_buckets", 120)
                ok, err_msg = _set_timeline_state(str(start_iso), str(end_iso), target_buckets)
                if not ok:
                    await websocket.send_json({
                        "type": "timeline_init",
                        "payload": {"error": err_msg or "Invalid timeline range"},
                    })
                else:
                    await _send_timeline_init()
            elif action == "ping":
                await websocket.send_json({"type": "pong"})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        push_task.cancel()
        _ws_stats_v2_connections.discard(websocket)
        logger.info("[ws/stats/v2] Client disconnected (%d remaining)", len(_ws_stats_v2_connections))


def _today_utc() -> str:
    """Return today's date as YYYY-MM-DD in UTC."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
