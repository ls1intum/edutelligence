import asyncio
import base64
import binascii
import datetime
import hmac
import json
import logging
import math
import os
import re
import secrets
import threading
import time
from contextlib import aclosing, asynccontextmanager, suppress
from dataclasses import dataclass
from typing import Any, Dict, Optional, Set

import grpc
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from grpclocal import model_pb2_grpc
from grpclocal.grpc_server import LogosServicer
from logos.auth import AuthContext, authenticate_api_key
from logos.benchmarks.guidellm_runner import (
    BENCHMARK_JOB_HEADER,
    BENCHMARK_PHASE_HEADER,
    BENCHMARK_PROVIDER_HEADER,
    BENCHMARK_TOKEN_HEADER,
    benchmark_affinity_token,
)
from logos.capacity.calibration_orchestrator import CalibrationConfig, CalibrationOrchestrator
from logos.capacity.capacity_planner import CapacityPlanner
from logos.capacity.demand_tracker import DemandTracker
from logos.classification.classification_balancer import Balancer
from logos.classification.classification_manager import ClassificationManager
from logos.context_budget import estimate_prompt_tokens, required_context_tokens
from logos.dbutils.dbmanager import DBManager
from logos.dbutils.dbmodules import JobStatus
from logos.dbutils.dbrequest import *
from logos.dbutils.types import (
    Deployment,
    get_unique_models_from_deployments,
    infer_cloud_provider_type,
    normalize_provider_type,
)
from logos.errors import UpstreamStreamError, coerce_upstream_error, openai_error_response
from logos.jobs.job_service import JobService, JobSubmission
from logos.live_stream import _LiveStreamRegistry, _StreamingLogAccumulator, _usage_tokens_from_payload
from logos.logosnode_registry import LogosNodeCommandError, LogosNodeOfflineError, LogosNodeRuntimeRegistry
from logos.logosnode_snapshot import (
    _build_live_local_provider_sample,
    _is_today_or_all_utc,
    _lane_served_context_window,
    _logosnode_snapshot_is_connected,
    _merge_provider_samples,
    _profile_native_context_length,
    _resolve_requested_model_name,
    _runtime_modes_for_lanes,
    _safe_float,
    _sample_snapshot_id,
)
from logos.middleware import APIPrefixStripperMiddleware
from logos.pipeline.context_resolver import ContextResolver
from logos.pipeline.correcting_scheduler import ClassificationCorrectingScheduler
from logos.pipeline.executor import ExecutionResult, Executor, StreamingExecutionStatus
from logos.pipeline.pipeline import PipelineRequest, RequestPipeline
from logos.queue.priority_queue import PriorityQueueManager
from logos.request_content import (
    force_non_streaming_payload,
    is_audio_upload_path,
    is_multipart_payload,
    is_whisper_payload,
    metered_whisper_response_format,
    parse_audio_upload,
    payload_requests_streaming,
    render_metered_whisper_response,
    sanitized_headers_for_persistence,
    sanitized_payload_for_logging,
    set_payload_field,
)
from logos.responses import extract_model, extract_token_usage, get_client_ip, request_setup
from logos.sdi.azure_deployment_sync import AzureDeploymentSyncService
from logos.sdi.azure_facade import AzureSchedulingDataFacade
from logos.sdi.logosnode_facade import LogosNodeSchedulingDataFacade
from logos.sdi.providers.azure_provider import extract_azure_deployment_name
from logos.terminal_logging import (
    GREEN,
    RED,
    YELLOW,
    MultiLineFormatter,
    UvicornAccessFilter,
    UvicornErrorFilter,
    format_number,
    model_name_cache,
    paint,
    style_duration,
    style_model,
    style_request_id,
)
from logos.timeouts import (
    _LOGOSNODE_INFER_TIMEOUT_SECONDS,
    _LOGOSNODE_PRETOKEN_RETRIES,
    _LOGOSNODE_PRETOKEN_RETRY_BACKOFF_S,
    _LOGOSNODE_STREAM_TIMEOUT_SECONDS,
)

logger = logging.getLogger("LogosLogger")
_grpc_server = None
_background_tasks: Set[asyncio.Task] = set()
_benchmark_tasks: Set[asyncio.Task] = set()
_benchmark_tasks_by_job: dict[int, asyncio.Task] = {}
_benchmark_sessions_by_job: dict[int, tuple[int, str]] = {}
_benchmark_admission_lock = threading.Lock()


def _forget_benchmark_task(job_id: int, task: asyncio.Task) -> None:
    _background_tasks.discard(task)
    _benchmark_tasks.discard(task)
    _benchmark_tasks_by_job.pop(job_id, None)
    _benchmark_sessions_by_job.pop(job_id, None)


def _cancel_benchmark_job(job_id: int, reason: str) -> bool:
    """Persist cancellation first, then stop the local GuideLLM process."""
    with DBManager() as db:
        cancelled = db.cancel_model_benchmark_job(job_id, reason)
    task = _benchmark_tasks_by_job.get(job_id)
    if task is not None and not task.done():
        task.cancel(reason)
    return cancelled


def _resolve_provider_name(provider_id: int) -> str:
    """Best-effort resolve a provider ID to its worker name."""
    snap = _logosnode_registry.peek_runtime_snapshot(provider_id)
    if snap:
        return snap.get("worker_id") or str(provider_id)
    return str(provider_id)


def _sync_logosnode_capabilities_to_db(provider_id: int, model_names: list[str]) -> None:
    """Callback: sync announced capabilities into DB tables and reload the
    SDI facade so the new (provider, model) deployments are visible to
    in-memory lookups. Without the reload, ``_model_id_to_name`` on the
    provider keeps whatever was loaded at server boot — the DB row is
    inserted but the planner's queue-depth-by-model-name lookup falls
    through the name match and returns 0, so the planner never sees
    ``queue_here>0`` for newly-declared capabilities and the model never
    gets loaded on the worker that just declared it.
    """
    pname = _resolve_provider_name(provider_id)
    newly_inserted: list[str] = []
    try:
        with DBManager() as db:
            newly_inserted = db.sync_logosnode_capabilities(provider_id, model_names)
        logger.info(
            "Synced %d capability model(s) to DB for provider %s%s",
            len(model_names),
            pname,
            f" (new: {', '.join(newly_inserted)})" if newly_inserted else "",
        )
    except Exception:
        logger.exception("Failed to sync capabilities to DB for provider %s", pname)
        return
    # Schedule facade refresh on the running loop. The callback is invoked
    # from async paths in the registry (attach_session / on_hello /
    # update_runtime) so a loop is always running; use a try/except to be
    # defensive against future sync callers.
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug(
            "No running event loop; skipping facade refresh for %s " "(next admin call will reload)",
            pname,
        )
        return
    # Rebuild the classifier only when sync inserted a fresh row in `models`
    # — otherwise the classifier's in-memory list already covers everything
    # the worker advertised. (Capability changes that only add or drop
    # model_provider links don't affect the classifier; it sees model rows,
    # not provider links.) Routine heartbeats and re-announcements skip the
    # rebuild entirely.
    task = loop.create_task(
        refresh_pipeline_runtime_state(
            rebuild_model_classifier=bool(newly_inserted),
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


_logosnode_registry = LogosNodeRuntimeRegistry(
    on_capabilities_changed=_sync_logosnode_capabilities_to_db,
)
_demand_tracker: Optional[DemandTracker] = None
_capacity_planner: Optional[CapacityPlanner] = None
_calibration_orchestrator: Optional[CalibrationOrchestrator] = None
_azure_deployment_sync: Optional[AzureDeploymentSyncService] = None


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
            # Initial WS load with no cursor. Cap to a recent window so the
            # init payload stays small even after weeks of accumulated
            # snapshots — the UI only renders a 30-min live window anyway,
            # and live deltas keep flowing afterwards via after_snapshot_id.
            recent_since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
            payload, status = db.get_ollama_vram_deltas(
                logos_key,
                day="all",
                after_snapshot_id=0,
                since=recent_since,
            )
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
        transport = (
            runtime.get("transport") if isinstance(runtime, dict) and isinstance(runtime.get("transport"), dict) else {}
        )
        if transport:
            entry["transport_connected"] = bool(transport.get("connected", connected))

        runtime_devices = runtime.get("devices") if isinstance(runtime, dict) else {}
        if isinstance(runtime_devices, dict):
            raw_device_list = runtime_devices.get("devices") or []
            if isinstance(raw_device_list, list) and raw_device_list:
                entry["devices"] = [
                    {
                        "device_id": d.get("device_id", ""),
                        "kind": d.get("kind", "nvidia"),
                        "name": d.get("name", ""),
                        "memory_used_mb": float(d.get("memory_used_mb") or 0.0),
                        "memory_total_mb": float(d.get("memory_total_mb") or 0.0),
                        "memory_free_mb": float(d.get("memory_free_mb") or 0.0),
                        "utilization_percent": _safe_float(d.get("utilization_percent")),
                        "temperature_celsius": _safe_float(d.get("temperature_celsius")),
                        "power_draw_watts": _safe_float(d.get("power_draw_watts")),
                    }
                    for d in raw_device_list
                    if isinstance(d, dict)
                ]

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


def _discard_in_flight(request_id: Optional[str], result_status: str) -> None:
    """Stop counting a request that ended without reaching ``record_complete``.

    Metrics only — the caller persists the log row itself. Safe to call for a
    request that was already settled, or one that never got as far as being
    enqueued.
    """
    if not request_id:
        return
    # `_pipeline` is bound by start_pipeline(), not at module scope, so before
    # startup the *name* does not exist — a bare reference raises NameError
    # rather than yielding None. This runs on the failure path, which is
    # reachable before the pipeline is up: a request arriving during the
    # startup grace period is rejected without one.
    pipeline = globals().get("_pipeline")
    if pipeline is None:
        return
    try:
        pipeline.discard_request(request_id, result_status)
    except Exception:  # noqa: BLE001 — monitoring must never break a request
        logger.debug("Failed to discard in-flight state for %s", request_id, exc_info=True)


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
    # Close out the in-flight accounting first, and unconditionally: this is
    # the common funnel for terminal failures that write the log row
    # themselves (client disconnect, rate-limit and budget rejects), and
    # none of them used to tell the recorder the request had ended. It also
    # has to happen for requests without a log row — the `not log_id` return
    # below is about persistence, not about whether the request finished.
    _discard_in_flight(request_id, result_status)

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
        logger.exception(
            "Failed to record terminal log failure (log_id=%s, request_id=%s)",
            log_id,
            request_id,
        )


_live_streams = _LiveStreamRegistry()


# One currency unit = 100 cents = 1e8 micro-cents. The unit is USD, not EUR:
# token_prices is filled from litellm's model catalog, whose input_cost_per_token
# is USD per token (gpt-4o reads 2.5e-6, i.e. its $2.50 per 1M list price),
# scaled by 1e11 = 1e8 micro-cents x 1e3 per-1k. No exchange rate is applied
# anywhere in the stack, so reporting these amounts as EUR mislabelled them.
_MICRO_CENTS_PER_USD = 100_000_000


def _response_with_cost(
    response_payload: Any,
    provider_id: Optional[int],
    model_id: Optional[int],
    response_at: datetime.datetime,
) -> tuple[Any, bool]:
    """Add the configured EUR cost to a cloud response's usage object.

    Cost enrichment is deliberately best-effort: a billing lookup must never
    turn a successful inference into an error. The DB method returns ``None``
    for local providers, so proxy mode can safely use the same helper without
    separately resolving the provider type.
    """
    if not isinstance(response_payload, dict) or provider_id is None or model_id is None:
        return response_payload, False
    usage = response_payload.get("usage")
    if not isinstance(usage, dict):
        return response_payload, False
    usage_tokens = extract_token_usage(usage)
    if not usage_tokens:
        return response_payload, False

    try:
        with DBManager() as db:
            cost_micro_cents = db.get_usage_cost_micro_cents(
                model_id,
                provider_id,
                usage_tokens,
                response_at,
            )
    except Exception:
        logger.exception(
            "Failed to calculate response cost (model_id=%s, provider_id=%s)",
            model_id,
            provider_id,
        )
        return response_payload, False
    if cost_micro_cents is None:
        return response_payload, False

    enriched_usage = dict(usage)
    enriched_usage["cost"] = round(cost_micro_cents / _MICRO_CENTS_PER_USD, 8)
    enriched_usage["cost_currency"] = "USD"
    enriched_payload = dict(response_payload)
    enriched_payload["usage"] = enriched_usage
    return enriched_payload, True


@dataclass
class _StreamingCostEnricher:
    """Enrich terminal SSE usage events while preserving all other frames."""

    provider_id: Optional[int]
    model_id: Optional[int]
    buffer: bytes = b""

    def feed(self, chunk: bytes | str) -> list[bytes]:
        self.buffer += chunk.encode("utf-8") if isinstance(chunk, str) else chunk
        frames: list[bytes] = []
        while True:
            delimiter = re.search(rb"\r?\n\r?\n", self.buffer)
            if delimiter is None:
                break
            end = delimiter.end()
            frame = self.buffer[:end]
            self.buffer = self.buffer[end:]
            frames.append(self._enrich_frame(frame, delimiter.start(), delimiter.group()))
        return frames

    def finish(self) -> list[bytes]:
        if not self.buffer:
            return []
        remainder = self.buffer
        self.buffer = b""
        return [remainder]

    def _enrich_frame(self, frame: bytes, payload_end: int, delimiter: bytes) -> bytes:
        event = frame[:payload_end]
        newline = b"\r\n" if b"\r\n" in event else b"\n"
        lines = event.split(newline)
        for index, line in enumerate(lines):
            if not line.startswith(b"data:"):
                continue
            raw_data = line[5:].lstrip()
            if raw_data == b"[DONE]":
                return frame
            try:
                blob = json.loads(raw_data)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(blob, dict):
                continue

            target = blob.get("response") if isinstance(blob.get("response"), dict) else blob
            enriched_target, changed = _response_with_cost(
                target,
                self.provider_id,
                self.model_id,
                datetime.datetime.now(datetime.timezone.utc),
            )
            if not changed:
                continue
            if target is blob:
                blob = enriched_target
            else:
                blob = dict(blob)
                blob["response"] = enriched_target
            lines[index] = b"data: " + json.dumps(blob, separators=(",", ":")).encode("utf-8")
            return newline.join(lines) + delimiter
        return frame


ORPHANED_REQUEST_ERROR = "Orchestrator restarted while the request was in flight; outcome unknown."


def _close_orphaned_request_logs() -> None:
    """Finalise log rows a previous orchestrator process left open.

    Without this a deploy or crash strands every in-flight request in the
    "running" state permanently — nothing else ever revisits those rows, so
    the live-request views keep counting requests that ended when the process
    did. Failing here must not keep the orchestrator from starting: stale rows
    are a reporting defect, an orchestrator that will not boot is an outage.
    """
    try:
        with DBManager() as db:
            closed = db.close_orphaned_request_logs(ORPHANED_REQUEST_ERROR)
    except Exception:  # noqa: BLE001
        logger.warning("Could not close orphaned request logs at startup", exc_info=True)
        return
    if closed:
        logger.info("Closed %d request log(s) left in-flight by a previous orchestrator process", closed)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup/shutdown lifecycle.
    Initializes the request pipeline components and gRPC server.
    """

    # Configure logging
    logging.basicConfig(level=logging.INFO, force=True)
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

    # The shared `logosdb` schema and all admin provisioning are owned by
    # logos-webservice: Liquibase creates and migrates the schema, and Keycloak
    # `itg-admin` users are synced to `logos_admin` on first login. The
    # orchestrator no longer bootstraps a `root` user, initialises the schema,
    # or runs migrations — it expects an already-provisioned database and goes
    # straight to start_pipeline(), which queries that schema.

    # Any request still marked in-flight belongs to the process that just
    # went away — close it before accepting new traffic, while "no terminal
    # state" unambiguously means "orphaned by a restart".
    _close_orphaned_request_logs()

    # Start Pipeline
    await start_pipeline()

    # Start gRPC server
    global _grpc_server
    _grpc_server = grpc.aio.server()
    model_pb2_grpc.add_LogosServicer_to_server(LogosServicer(_pipeline), _grpc_server)
    _grpc_server.add_insecure_port("[::]:50051")
    await _grpc_server.start()

    yield

    # Shutdown logic
    benchmark_tasks = list(_benchmark_tasks)
    for task in benchmark_tasks:
        task.cancel()
    if benchmark_tasks:
        await asyncio.gather(*benchmark_tasks, return_exceptions=True)
    if _capacity_planner:
        await _capacity_planner.stop()
    if _calibration_orchestrator:
        await _calibration_orchestrator.stop()
    if _azure_deployment_sync:
        await _azure_deployment_sync.stop()
    if _grpc_server:
        await _grpc_server.stop(0)


# Prometheus metrics auth: set PROMETHEUS_API_KEY env var to require auth; if unset, deny all.
_PROMETHEUS_API_KEY = os.getenv("PROMETHEUS_API_KEY")
_INTERNAL_SECRET = os.getenv("LOGOS_INTERNAL_SECRET")

# Initialize FastAPI app with lifespan
app = FastAPI(
    docs_url="/docs",
    openapi_url="/openapi.json",
    lifespan=lifespan,
    swagger_ui_init_oauth={},
    openapi_tags=[
        {
            "name": "user-facing",
            "description": "OpenAI-compatible API endpoints for model inference, model listing, and async jobs",
        },
        {
            "name": "admin",
            "description": "Database management, statistics, dashboards, and system configuration",
        },
        {
            "name": "logosnode",
            "description": "LogosWorkerNode provider registration, sessions, and lane management",
        },
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
    if _logos_domain == "localhost":
        schema["servers"] = [{"url": "/", "description": "Current local server"}]
    else:
        schema["servers"] = [
            {
                "url": f"https://{_logos_domain}",
                "description": "All surfaces (default HTTPS port): /v1, /openai, /jobs, /logosdb, /metrics, /health",
            },
            {
                "url": f"https://{_logos_domain}:8080",
                "description": "Completion API alias for existing clients: /v1, /openai, /jobs, /health",
            },
        ]
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


app.add_middleware(APIPrefixStripperMiddleware, prefix="/api")


# ============================================================================
# GLOBAL EXCEPTION HANDLERS – OpenAI-spec error shapes
# ============================================================================


# Registered on Starlette's base HTTPException so it also catches the ones the
# framework itself raises (e.g. the 405 for a method mismatch on an existing
# path) — FastAPI's HTTPException is a subclass and matches too.
@app.exception_handler(StarletteHTTPException)
async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """
    Convert every HTTPException raised in user-facing code to the OpenAI error shape.

    If ``exc.detail`` is already a dict with an ``"error"`` key (as raised by
    ``raise_openai_error()``) it is forwarded as-is so that code and param are
    preserved.  Plain string details are wrapped automatically.

    Exception headers are forwarded so protocol-mandated headers survive the
    conversion — e.g. the ``Allow`` header Starlette attaches to 405s and the
    ``Retry-After`` set on 429 rate-limit rejections.
    """
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail:
        return JSONResponse(content=detail, status_code=exc.status_code, headers=exc.headers)
    return openai_error_response(
        exc.status_code,
        str(detail) if detail is not None else "",
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Convert Pydantic / FastAPI validation errors to the OpenAI error shape (HTTP 422)."""
    errors = exc.errors()
    param: str | None = None
    message = "Request validation failed"
    if errors:
        first = errors[0]
        loc = first.get("loc") or ()
        if loc:
            param = str(loc[-1])
        message = first.get("msg") or message
    return openai_error_response(422, message, param=param)


@app.exception_handler(Exception)
async def _generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all: return HTTP 500 without leaking stack traces or internal details."""
    logger.exception("Unhandled exception on %s", request.url.path)
    return openai_error_response(500, "Internal server error")


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


def _normalize_provider_type(provider_type: str | None) -> str:
    return normalize_provider_type(provider_type)


async def _filter_logosnode_deployments(
    deployments: list[Deployment],
    payload: Optional[dict] = None,
) -> list[Deployment]:
    """
    Enforce provider model scope intersection:
    DB deployment assignment AND node capabilities.

    When ``payload`` is given, also prefers the workers whose served context
    window fits the request; see :func:`_prefer_deployments_with_context_room`.
    """
    if not deployments:
        return []

    filtered: list[Deployment] = []
    _local_name_lookup: dict[int, str] = {}

    with DBManager() as db:
        for deployment in deployments:
            provider_type = _normalize_provider_type(deployment.get("type"))
            if provider_type != "logosnode":
                filtered.append(deployment)
                continue

            model_id = int(deployment["model_id"])
            if model_id not in _local_name_lookup:
                model_info = db.get_model(model_id)
                name = (model_info or {}).get("name", "")
                _local_name_lookup[model_id] = name
                # Prime the module-level cache so log lines resolve without a DB hit.
                model_name_cache.prime(model_id, name)

            model_name = _local_name_lookup[model_id]
            if not model_name:
                continue

            allowed = await _logosnode_registry.is_model_allowed(
                int(deployment["provider_id"]),
                model_name,
            )
            if allowed:
                filtered.append({**deployment, "type": "logosnode"})

    # Audio uploads carry a file, not a conversation: their "prompt" field is a
    # transcription hint of a few words and says nothing about how much context
    # the request needs. Leave their routing alone.
    if payload is not None and not is_multipart_payload(payload):
        filtered = _prefer_deployments_with_context_room(filtered, payload, _local_name_lookup)

    return filtered


def _provider_served_context_windows() -> dict[tuple[int, str], int]:
    """(provider_id, model name) -> smallest window that worker serves for it.

    Per worker rather than per model, which is what routing needs: the
    model-level minimum in :func:`_served_context_window_stats` is the floor
    across the whole cluster and says nothing about which node is the roomy
    one. A worker running several lanes for the same model is reduced to its
    narrowest, since any of them may take the request.
    """
    windows: dict[tuple[int, str], int] = {}
    try:
        provider_ids = _logosnode_registry.active_provider_ids()
    except Exception:
        return windows
    for provider_id in provider_ids:
        snap = _logosnode_registry.peek_runtime_snapshot(provider_id)
        runtime = (snap or {}).get("runtime")
        if not isinstance(runtime, dict):
            continue
        lanes = runtime.get("lanes")
        if not isinstance(lanes, list):
            continue
        model_profiles = runtime.get("model_profiles")
        if not isinstance(model_profiles, dict):
            model_profiles = {}
        for lane in lanes:
            if not isinstance(lane, dict):
                continue
            window = _lane_served_context_window(lane, model_profiles)
            if window <= 0:
                continue
            key = (int(provider_id), lane["model"])
            windows[key] = min(windows[key], window) if key in windows else window
    return windows


def _prefer_deployments_with_context_room(
    deployments: list[Deployment],
    payload: dict,
    model_names: dict[int, str],
) -> list[Deployment]:
    """Drop workers whose context window is too narrow for this request.

    A model can be placed with very different windows on different nodes: the
    planner gives a lane as much context as the node's free KV cache allows,
    so the same model may serve 262144 tokens on one worker and a fraction of
    that on another. Routing a long conversation to the narrow one earns a 400
    from vLLM even though a worker that could have answered was idle next to
    it.

    So: estimate what the request needs (prompt + its own output reservation +
    the same 3000-token margin Claude Code keeps) and keep only the workers
    that offer it.

    Deliberate escape hatches, because this filter runs on an estimate:

    * A worker whose window is unknown is always kept. ``max_model_len`` is
      absent for cloud providers, for Ollama lanes and for a vLLM lane the
      worker has not reported a window for — none of those are evidence of a
      *narrow* window.
    * A model is never filtered out entirely. If every lane of a model has a
      known window that is too narrow, the widest of them is kept anyway.
      Downstream, proxy mode narrows this list to the requested model and
      turns an emptied model into a 404 "no deployment found" that hides the
      real state; the engine, by contrast, either serves the request or
      answers its own honest 400 — which is what the client should see (#810).
    * When no worker is left, the widest ones are returned instead of nothing,
      so the request fails upstream exactly as it did before this filter
      existed.
    """
    required = required_context_tokens(payload)
    if required is None:
        return deployments

    windows = _provider_served_context_windows()
    if not windows:
        return deployments

    def _window_of(deployment: Deployment) -> Optional[int]:
        if _normalize_provider_type(deployment.get("type")) != "logosnode":
            return None
        model_name = model_names.get(int(deployment["model_id"]))
        if not model_name:
            return None
        return windows.get((int(deployment["provider_id"]), model_name))

    # Models whose known windows are all too narrow. Keep their widest lane
    # anyway: proxy mode narrows the result to the requested model, so an
    # emptied model would 404 "no deployment found" here, while the engine
    # would either serve the request or answer its own honest 400.
    rescued_widest: dict[int, int] = {}
    by_model: dict[int, list[Deployment]] = {}
    for deployment in deployments:
        by_model.setdefault(int(deployment["model_id"]), []).append(deployment)
    for model_id, model_deployment in by_model.items():
        if any((_window_of(d) or required) >= required for d in model_deployment):
            continue
        widest = max((_window_of(d) for d in model_deployment), default=0)
        if widest > 0:
            rescued_widest[model_id] = widest
            logger.warning(
                "Context routing: request needs ~%d tokens but the widest served window for "
                "model %s is %d — keeping the widest lane so the engine can answer",
                required,
                model_names.get(model_id, str(model_id)),
                widest,
            )

    def _keep(deployment: Deployment) -> bool:
        if (_window_of(deployment) or required) >= required:
            return True
        widest = rescued_widest.get(int(deployment["model_id"]))
        return widest is not None and (_window_of(deployment) or 0) >= widest

    fitting = [d for d in deployments if _keep(d)]
    if len(fitting) != len(deployments):
        logger.info(
            "Context routing: request needs ~%d tokens; %d of %d deployment(s) serve a wide " "enough window%s",
            required,
            len(fitting),
            len(deployments),
            f" (+{len(rescued_widest)} widest lane(s) of fully-filtered model(s) kept)" if rescued_widest else "",
        )
    return fitting or deployments


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
    # Every worker report restores the forwarding gate's budget, so it is
    # also the moment to reconsider requests being held for it.
    _logosnode_registry.set_on_runtime_updated(scheduler.on_worker_report)
    _context_resolver = ContextResolver(
        logosnode_registry=_logosnode_registry,
        lane_preparer=_capacity_planner,
    )
    _pipeline._context_resolver = _context_resolver

    # Wire capacity-needed callback: when the scheduler queues a request
    # for a sleeping/unloaded model, kick the planner cycle immediately
    # so it acts on the new demand within milliseconds. The cycle's
    # globally-fair eviction logic is the single source of truth for
    # what to wake/load — request-time work no longer races for the
    # provider lock, so a low-demand request can't starve out a
    # high-demand one waiting on the same provider.
    async def _on_capacity_needed(model_name: str, provider_id: int | None = None) -> None:
        try:
            _capacity_planner.hint_capacity_needed(model_name, provider_id=provider_id)
        except Exception:
            logger.debug(
                "Capacity hint for %s (originating provider=%s) failed",
                model_name,
                provider_id,
                exc_info=True,
            )

    scheduler._on_capacity_needed = _on_capacity_needed

    await _capacity_planner.start()

    global _calibration_orchestrator
    _calibration_orchestrator = CalibrationOrchestrator(
        registry=_logosnode_registry,
        facade=_logosnode_facade,
        config=CalibrationConfig.from_env(),
    )
    await _calibration_orchestrator.start()
    logger.info(
        "Calibration orchestrator started (enabled=%s)",
        _calibration_orchestrator._config.enabled,
    )

    # Azure deployment auto-sync: discover deployed models and upsert them into
    # the DB on startup and every 24h. Runs after facade registration so its
    # initial pass can trigger a runtime refresh for any newly added models.
    global _azure_deployment_sync
    _azure_deployment_sync = AzureDeploymentSyncService(
        on_models_changed=lambda *, rebuild_classifier: refresh_pipeline_runtime_state(
            rebuild_model_classifier=rebuild_classifier
        ),
    )
    await _azure_deployment_sync.start()

    logger.info(
        "Request Pipeline Initialized with ClassificationCorrectingScheduler " "(planner=%s, ettft=%s)",
        planner_enabled,
        ettft_enabled,
    )


async def _register_models_with_facades(
    logosnode_facade: LogosNodeSchedulingDataFacade,
    azure_facade: AzureSchedulingDataFacade,
):
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
            provider_type = normalize_provider_type(deployment.get("type"))
            cloud_provider_type = provider_info.get("cloud_provider_type") or infer_cloud_provider_type(
                deployment.get("type"), base_url=provider_info.get("base_url")
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
                # A live worker is the source of truth for what it serves:
                # skip DB deployments it no longer announces (stale
                # model_provider link, e.g. from a manual connect_model_provider)
                # so the planner doesn't spawn lanes for non-capable models.
                # Only applied to providers the scheduler also treats as
                # online (fresh heartbeat): a stale session (worker hung,
                # connection still open) counts as offline and its DB
                # deployments stay registered as before, matching the
                # scheduler's is_provider_online view of the same state.
                if _logosnode_registry.is_provider_online(provider_id):
                    snapshot = _logosnode_registry.peek_runtime_snapshot(provider_id)
                    if snapshot is not None and model_name not in snapshot["capabilities_models"]:
                        logger.warning(
                            "Skipping deployment model %s for connected logosnode provider %s (%s): "
                            "not in the worker's live capabilities (stale DB link)",
                            model_name,
                            provider_name,
                            provider_id,
                        )
                        continue
                logosnode_registrations.append(
                    {
                        "model_id": model_id,
                        "provider_name": provider_name,
                        "logosnode_admin_url": (
                            provider_config.get("ollama_admin_url") or provider_info.get("base_url")
                        ),
                        "model_name": model_name,
                        "total_vram_mb": provider_config.get("total_vram_mb", 65536),
                        "provider_id": provider_id,
                    }
                )
            elif cloud_provider_type == "azure":
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
            elif provider_type == "cloud":
                # Cloud upstream has no local SDI state to track — it manages
                # its own scheduling. The (model_id, provider_id) -> "cloud"
                # mapping in the model registry is enough for the scheduler
                # to route to it.
                continue
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
            provider_type = normalize_provider_type(deployment.get("type"))
            cloud_provider_type = provider_info.get("cloud_provider_type") or infer_cloud_provider_type(
                deployment.get("type"), base_url=provider_info.get("base_url")
            )
            # Azure has a dedicated scheduling facade. Every other managed
            # cloud provider (OpenAI, Anthropic, Gemini, etc.) shares the
            # generic cloud scheduler path instead of becoming an unknown
            # provider type such as "openai".
            effective_type = "azure" if provider_type == "cloud" and cloud_provider_type == "azure" else provider_type
            if effective_type:
                registry[(model_id, provider_id)] = effective_type
    return registry


def classifier() -> ClassificationManager:
    """Build classifier with all models from database."""
    mdls = []
    with DBManager() as db:
        for model_id in db.get_all_models():
            tpl = db.get_model(model_id)
            if tpl:
                mdls.append(
                    {
                        "id": tpl["id"],
                        "name": tpl["name"],
                        "weight_latency": tpl["weight_latency"],
                        "weight_accuracy": tpl["weight_accuracy"],
                        "weight_cost": tpl["weight_cost"],
                        "weight_quality": tpl["weight_quality"],
                        "tags": tpl["tags"],
                        "description": tpl["description"],
                        "classification_weight": Balancer(),
                    }
                )

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


def _cached_prompt_tokens(usage: Dict[str, Any]) -> Optional[int]:
    """Cached-prompt tokens as reported by the provider, or None when absent.

    Handles both shapes that reach the completion log: the flattened dict
    from ``extract_token_usage`` (``prompt_cached_tokens``) and the raw
    streaming usage (``prompt_tokens_details.cached_tokens``).
    """
    cached = usage.get("prompt_cached_tokens")
    if isinstance(cached, int) and not isinstance(cached, bool):
        return cached
    details = usage.get("prompt_tokens_details")
    if isinstance(details, dict):
        cached = details.get("cached_tokens")
        if isinstance(cached, int) and not isinstance(cached, bool):
            return cached
    return None


def _log_request_completion(
    model_id: int,
    request_id: Optional[str],
    start_time: float,
    usage: Dict[str, Any],
    status: str,
    is_streaming: bool,
) -> None:
    """Emit one consolidated INFO line summarising a completed inference request."""
    duration_ms = (time.perf_counter() - start_time) * 1000.0
    prompt_tokens = usage.get("prompt_tokens", 0) or 0
    completion_tokens = usage.get("completion_tokens", 0) or 0
    cached_tokens = _cached_prompt_tokens(usage)
    generation_s = duration_ms / 1000.0
    tps = (completion_tokens / generation_s) if generation_s > 0 and completion_tokens > 0 else 0.0

    if status == "success":
        status_str = paint("ok", GREEN)
    elif status == "timeout":
        status_str = paint("timeout", YELLOW)
    else:
        status_str = paint(status, RED)

    mode = "stream" if is_streaming else "sync"
    model_name = model_name_cache.get(model_id) if model_id else str(model_id)

    parts = [
        f"done {style_model(model_name)}",
        f"req={style_request_id(request_id or '?')}",
        f"mode={mode}",
        f"status={status_str}",
        f"dur={style_duration(duration_ms)}",
    ]
    if completion_tokens > 0:
        total_tokens = prompt_tokens + completion_tokens
        parts.append(
            f"tokens={format_number(prompt_tokens)} + {format_number(completion_tokens)} "
            f"= {format_number(total_tokens)}"
        )
        if tps > 0:
            parts.append(f"tps={tps:.1f}")
    # Prefix-cache hit share of this request's prompt; only shown when the
    # provider reports cached tokens (vLLM, Azure, OpenAI prompt caching).
    if prompt_tokens > 0 and cached_tokens is not None:
        parts.append(f"prefix_hit={cached_tokens / prompt_tokens:.0%}")
    logger.info(" ".join(parts))


def _decision_response_headers(request_id, scheduling_stats) -> Optional[dict]:
    """Response headers exposing the scheduling decision to the client.

    Benchmarks correlate the scheduler's view (ETTFT estimate, warmth state
    at decision time) with the observed TTFT — headers are the only channel
    that reaches a streaming client before the first token.
    """
    headers: dict[str, str] = {}
    if request_id:
        headers["X-Request-ID"] = request_id
    if scheduling_stats:
        ettft_ms = scheduling_stats.get("ettft_estimate_ms")
        if isinstance(ettft_ms, (int, float)) and math.isfinite(ettft_ms):
            headers["X-Logos-ETTFT-Ms"] = f"{ettft_ms:.0f}"
        tier = scheduling_stats.get("ettft_tier")
        if tier:
            headers["X-Logos-ETTFT-Tier"] = str(tier)
        warmth = scheduling_stats.get("warmth_state")
        if warmth is not None:
            headers["X-Logos-Warmth-State"] = str(int(warmth))
    return headers or None


async def _streaming_response(
    context,
    payload,
    log_id,
    provider_id,
    model_id,
    policy_id,
    classification_stats,
    scheduling_stats=None,
    request_path=None,
    rl_key=None,
    api_key_id: Optional[int] = None,
):
    """Build streaming response using executor.

    Returns a ``JSONResponse`` when the upstream returns a non-2xx status code
    *before* emitting any SSE chunks so that clients receive the correct HTTP
    status code. Returns a ``StreamingResponse`` for normal 2xx streams while
    preserving the upstream content type. Mid-stream errors append an
    OpenAI-spec error frame only for SSE responses.
    """
    from fastapi.responses import JSONResponse, StreamingResponse

    request_id = scheduling_stats.get("request_id") if scheduling_stats else None
    _req_start = time.perf_counter()

    # Prepare headers and payload using context resolver
    headers, prepared_payload = _context_resolver.prepare_headers_and_payload(context, payload)

    upstream_stream_headers: dict[str, str] = {}

    def process_headers(hdrs: dict):
        upstream_stream_headers.update({str(key).lower(): str(value) for key, value in hdrs.items()})
        try:
            _pipeline.update_provider_stats(model_id, provider_id, hdrs)
        except Exception:
            pass
        try:
            _record_azure_rate_limits(scheduling_stats, hdrs)
        except Exception:
            pass

    def _release():
        """Release scheduler slot (called on early-return error paths)."""
        if scheduling_stats and scheduling_stats.get("request_id"):
            try:
                _pipeline.scheduler.release(
                    model_id,
                    provider_id,
                    scheduling_stats.get("provider_type"),
                    scheduling_stats.get("request_id"),
                )
            except Exception as _e:
                logger.error(f"Failed to release scheduler resources: {_e}")

    def _pre_stream_error_response(status_code: int, body: Any, error_message: str):
        """Record an error that occurred before a streaming response was committed."""
        corrected_sc, error_body = coerce_upstream_error(status_code, body)
        _release()
        if log_id:
            try:
                with DBManager() as db:
                    db.set_response_payload(
                        log_id,
                        error_body,
                        provider_id,
                        model_id,
                        {},
                        policy_id,
                        classification_stats,
                        request_id=(scheduling_stats.get("request_id") if scheduling_stats else None),
                        queue_depth_at_arrival=(
                            scheduling_stats.get("queue_depth_at_arrival") if scheduling_stats else None
                        ),
                        utilization_at_arrival=(
                            scheduling_stats.get("utilization_at_arrival") if scheduling_stats else None
                        ),
                    )
                    db.update_log_entry_metrics(
                        log_id=log_id,
                        request_id=request_id,
                        model_id=model_id,
                        provider_id=provider_id,
                        result_status="error",
                        error_message=error_message,
                        cold_start=(scheduling_stats.get("is_cold_start") if scheduling_stats else None),
                    )
            except Exception:
                logger.exception(
                    "Failed to record pre-stream error (log_id=%s, request_id=%s)",
                    log_id,
                    request_id,
                )
        if scheduling_stats:
            _pipeline.record_completion(
                request_id=scheduling_stats.get("request_id"),
                result_status="error",
                error_message=error_message,
                cold_start=scheduling_stats.get("is_cold_start"),
            )
        _log_request_completion(
            model_id=model_id,
            request_id=request_id,
            start_time=_req_start,
            usage={},
            status="error",
            is_streaming=True,
        )
        return JSONResponse(
            content=error_body,
            status_code=corrected_sc,
            headers=_decision_response_headers(request_id, scheduling_stats),
        )

    # ── logosnode path ────────────────────────────────────────────────────
    # LogosNode streams come via WebSocket; status errors are raised as
    # LogosNodeOfflineError / LogosNodeCommandError *before* streaming starts
    # (handled in _sync_response). Just wrap in StreamingResponse as before.
    if context.provider_type == "logosnode" and context.lane_id:
        stream_payload = set_payload_field(prepared_payload, "stream", True)
        if not is_audio_upload_path(request_path or ""):
            stream_payload = {
                **stream_payload,
                "stream_options": {"include_usage": True},
            }

        def _new_logosnode_chunk_iter():
            return _logosnode_registry.send_stream_command(
                provider_id=provider_id,
                action="infer_stream",
                params={
                    "lane_id": context.lane_id,
                    "payload": stream_payload,
                    "request_path": request_path,
                },
                timeout_seconds=_LOGOSNODE_STREAM_TIMEOUT_SECONDS,
            )

        async def logosnode_streamer():
            stream_log = _StreamingLogAccumulator()
            error_message = None
            ttft_recorded = False
            # Publish this request to the live view for as long as it runs. The
            # registry is dropped in the finally below, so a client that walks
            # away cannot leave an entry behind.
            _live_streams.start(request_id, model_name_cache.get(model_id) if model_id else None)
            # A client that walks away mid-stream closes this generator, which
            # raises GeneratorExit at the `yield` — no exception reaches the
            # handler below, so without this flag the request was recorded as
            # a success. It is not one: nobody read the answer, and the
            # generation was cancelled on the worker. Recording it honestly
            # also completes the disconnect count, which until now only saw
            # the clients that left *before* the first token.
            stream_completed = False
            try:
                attempts = _LOGOSNODE_PRETOKEN_RETRIES + 1
                for attempt in range(attempts):
                    produced = False
                    try:
                        # `aclosing` is what makes an abandoned request reach
                        # the worker promptly. When this generator is closed
                        # mid-stream — a client that walked away — a bare
                        # `async for` would leave the inner generator to the
                        # async-generator GC hook, so its cleanup (which is
                        # what sends the cancellation) would run at some
                        # unspecified later point. Closing it here runs that
                        # cleanup while the disconnect is being handled.
                        async with aclosing(_new_logosnode_chunk_iter()) as chunk_iter:
                            async for chunk in chunk_iter:
                                produced = True
                                # Parse before yielding: GuideLLM closes its HTTP
                                # stream as soon as it receives [DONE]. If the
                                # completion flag were set afterwards, that normal
                                # close would be misreported as a disconnect.
                                stream_log.feed(chunk)
                                if stream_log.terminal_event_received:
                                    stream_completed = True
                                if chunk and not ttft_recorded:
                                    if log_id:
                                        with DBManager() as db:
                                            db.set_time_at_first_token(log_id)
                                    ttft_recorded = True
                                _live_streams.update(request_id, stream_log.streamed_tokens())
                                yield chunk
                    except Exception as e:
                        # Retry ONLY if nothing has been streamed to the client yet:
                        # a pre-token failure (e.g. a just-woken level-1 lane whose
                        # engine was not yet serveable — the worker fails cleanly
                        # before stream_start). Nothing was sent downstream, so a
                        # fresh dispatch is transparent. Once any chunk has gone to
                        # the client we cannot un-send it, so re-raise.
                        if not produced and attempt < attempts - 1:
                            logger.warning(
                                "logosnode pre-token stream failure (attempt %d/%d), retrying: %s",
                                attempt + 1,
                                attempts,
                                e,
                            )
                            await asyncio.sleep(_LOGOSNODE_PRETOKEN_RETRY_BACKOFF_S)
                            continue
                        error_message = str(e)
                        raise e
                    stream_completed = True
                    break  # stream completed without raising
            finally:
                if not stream_completed and error_message is None:
                    error_message = (
                        "Client disconnected mid-stream; upstream generation cancelled "
                        f"after {stream_log.streamed_tokens().get('completion_tokens', 0)} token(s)."
                    )
                _live_streams.finish(request_id)
                stream_log.finish()
                response_payload = stream_log.response_payload()
                usage_tokens = _usage_tokens_from_payload(response_payload)
                if log_id:
                    with DBManager() as db:
                        db.set_response_payload(
                            log_id,
                            response_payload,
                            provider_id,
                            model_id,
                            usage_tokens,
                            policy_id,
                            classification_stats,
                            request_id=(scheduling_stats.get("request_id") if scheduling_stats else None),
                            queue_depth_at_arrival=(
                                scheduling_stats.get("queue_depth_at_arrival") if scheduling_stats else None
                            ),
                            utilization_at_arrival=(
                                scheduling_stats.get("utilization_at_arrival") if scheduling_stats else None
                            ),
                        )
                if rl_key:
                    from logos.rate_limiter import get_rate_limiter

                    total = usage_tokens.get("total_tokens") or (
                        usage_tokens.get("prompt_tokens", 0) + usage_tokens.get("completion_tokens", 0)
                    )
                    get_rate_limiter().record_tokens(rl_key, total)
                if scheduling_stats:
                    _pipeline.record_completion(
                        request_id=scheduling_stats.get("request_id"),
                        result_status="error" if error_message else "success",
                        error_message=error_message,
                        cold_start=scheduling_stats.get("is_cold_start"),
                        usage_tokens=usage_tokens,
                    )
                _log_request_completion(
                    model_id=model_id,
                    request_id=request_id,
                    start_time=_req_start,
                    usage=stream_log.usage(),
                    status="error" if error_message else "success",
                    is_streaming=True,
                )
                _release()

        return StreamingResponse(
            logosnode_streamer(),
            media_type="text/event-stream",
            headers=_decision_response_headers(request_id, scheduling_stats),
        )

    # ── HTTP executor path ────────────────────────────────────────────────
    stream_status = StreamingExecutionStatus()
    chunk_iter = _pipeline.executor.execute_streaming(
        context.forward_url,
        headers,
        prepared_payload,
        on_headers=process_headers,
        status=stream_status,
    )

    # Peek at the first chunk.  This triggers the initial HTTP connection so
    # that on_headers fires and – crucially – UpstreamStreamError is raised
    # for non-2xx responses before we commit to a StreamingResponse.
    try:
        first_chunk = await chunk_iter.__anext__()
    except UpstreamStreamError as exc:
        logger.error(
            "Pre-stream error from upstream (model_id=%s, provider_id=%s): HTTP %s",
            model_id,
            provider_id,
            exc.status_code,
        )
        return _pre_stream_error_response(exc.status_code, exc.body, str(exc))
    except StopAsyncIteration:
        first_chunk = None
    except Exception as exc:
        logger.error(
            "Pre-stream transport error from upstream (model_id=%s, provider_id=%s): %s: %s",
            model_id,
            provider_id,
            type(exc).__name__,
            exc,
        )
        return _pre_stream_error_response(502, {"error": str(exc)}, str(exc))

    upstream_content_type = upstream_stream_headers.get("content-type", "")
    upstream_media_type = upstream_content_type.split(";", 1)[0].strip().lower()
    response_headers = _decision_response_headers(request_id, scheduling_stats) or {}
    response_headers["content-type"] = upstream_content_type or "text/event-stream"

    async def http_streamer():
        stream_log = _StreamingLogAccumulator()
        cost_enricher = (
            _StreamingCostEnricher(provider_id, model_id)
            if context.provider_type == "cloud" and upstream_media_type in {"", "text/event-stream"}
            else None
        )
        error_message = None
        ttft_recorded = False

        def enriched_chunks(chunk: bytes | str) -> list[bytes | str]:
            return cost_enricher.feed(chunk) if cost_enricher else [chunk]

        # Same live view the logosnode path publishes to — a cloud request is
        # just as opaque while it runs, and the page shows both together.
        _live_streams.start(request_id, model_name_cache.get(model_id) if model_id else None)
        try:
            # Yield the already-peeked first chunk
            if first_chunk:
                for outgoing_chunk in enriched_chunks(first_chunk):
                    yield outgoing_chunk
                    stream_log.feed(outgoing_chunk)
                if not ttft_recorded:
                    if log_id:
                        with DBManager() as db:
                            db.set_time_at_first_token(log_id)
                    ttft_recorded = True

            async for chunk in chunk_iter:
                for outgoing_chunk in enriched_chunks(chunk):
                    yield outgoing_chunk
                    stream_log.feed(outgoing_chunk)
                _live_streams.update(request_id, stream_log.streamed_tokens())
                if chunk and not ttft_recorded:
                    if log_id:
                        with DBManager() as db:
                            db.set_time_at_first_token(log_id)
                    ttft_recorded = True
            if cost_enricher:
                for outgoing_chunk in cost_enricher.finish():
                    yield outgoing_chunk
                    stream_log.feed(outgoing_chunk)
        except Exception as exc:
            error_message = str(exc)
            if cost_enricher:
                for outgoing_chunk in cost_enricher.finish():
                    yield outgoing_chunk
                    stream_log.feed(outgoing_chunk)
            # Once bytes have reached the client, only SSE can carry the
            # synthetic OpenAI error frame without corrupting its protocol.
            if upstream_media_type == "text/event-stream":
                import json as _json

                _, error_body = coerce_upstream_error(500, {"error": str(exc)})
                # The last upstream chunk may have ended inside an SSE event.
                # Close it before emitting recovery frames so clients can parse
                # the synthetic error independently.
                yield b"\n\n"
                yield f"data: {_json.dumps(error_body)}\n\n".encode()
                yield b"data: [DONE]\n\n"
        finally:
            _live_streams.finish(request_id)
            if error_message is None:
                error_message = stream_status.error
            failed = error_message is not None
            stream_log.finish()
            response_payload = stream_log.response_payload()
            usage_tokens = _usage_tokens_from_payload(response_payload)
            if log_id:
                with DBManager() as db:
                    db.set_response_payload(
                        log_id,
                        response_payload,
                        provider_id,
                        model_id,
                        usage_tokens,
                        policy_id,
                        classification_stats,
                        request_id=(scheduling_stats.get("request_id") if scheduling_stats else None),
                        queue_depth_at_arrival=(
                            scheduling_stats.get("queue_depth_at_arrival") if scheduling_stats else None
                        ),
                        utilization_at_arrival=(
                            scheduling_stats.get("utilization_at_arrival") if scheduling_stats else None
                        ),
                    )
                    if failed:
                        db.update_log_entry_metrics(
                            log_id=log_id,
                            request_id=request_id,
                            model_id=model_id,
                            provider_id=provider_id,
                            result_status="error",
                            error_message=error_message,
                        )
            if rl_key:
                from logos.rate_limiter import get_rate_limiter

                total = usage_tokens.get("total_tokens") or (
                    usage_tokens.get("prompt_tokens", 0) + usage_tokens.get("completion_tokens", 0)
                )
                get_rate_limiter().record_tokens(rl_key, total)
            if scheduling_stats:
                _pipeline.record_completion(
                    request_id=scheduling_stats.get("request_id"),
                    result_status="error" if failed else "success",
                    error_message=error_message,
                    cold_start=scheduling_stats.get("is_cold_start"),
                    usage_tokens=usage_tokens,
                )
            _log_request_completion(
                model_id=model_id,
                request_id=request_id,
                start_time=_req_start,
                usage=stream_log.usage(),
                status="error" if failed else "success",
                is_streaming=True,
            )
            _release()

    return StreamingResponse(
        http_streamer(),
        headers=response_headers,
    )


async def _sync_response(
    context,
    payload,
    log_id,
    provider_id,
    model_id,
    policy_id,
    classification_stats,
    scheduling_stats=None,
    is_async_job=False,
    request_path=None,
    rl_key=None,
    api_key_id: Optional[int] = None,
):
    """Execute sync request and return response."""
    from fastapi.responses import JSONResponse

    request_id = scheduling_stats.get("request_id") if scheduling_stats else None
    _req_start = time.perf_counter()

    try:
        raw_audio_format = metered_whisper_response_format(
            payload,
            request_path or "",
            resolved_model_name=getattr(context, "model_name", None),
        )
        upstream_payload = (
            set_payload_field(payload, "response_format", "verbose_json") if raw_audio_format else payload
        )
        # Prepare headers and payload using context resolver
        headers, prepared_payload = _context_resolver.prepare_headers_and_payload(context, upstream_payload)

        timed_out = False
        error_message = None
        status_override = None

        if context.provider_type == "logosnode" and context.lane_id:
            sync_payload = force_non_streaming_payload(prepared_payload)
            try:
                rpc_result = await _logosnode_registry.send_command(
                    provider_id=provider_id,
                    action="infer",
                    params={
                        "lane_id": context.lane_id,
                        "payload": sync_payload,
                        "request_path": request_path,
                    },
                    timeout_seconds=_LOGOSNODE_INFER_TIMEOUT_SECONDS,
                )
                status_override = int(rpc_result.get("status_code", 200))
                response_payload = rpc_result.get("body")
                rpc_headers = rpc_result.get("headers") if isinstance(rpc_result.get("headers"), dict) else {}
                rpc_content_type = rpc_headers.get("content-type")
                has_binary_marker = "body_encoding" in rpc_result or "body_base64" in rpc_result
                encoded_rpc_body = rpc_result.get("body_base64")
                if has_binary_marker and (
                    rpc_result.get("body_encoding") != "base64" or not isinstance(encoded_rpc_body, str)
                ):
                    raise LogosNodeCommandError("logosnode infer returned invalid binary response metadata")
                binary_rpc_response = status_override < 400 and has_binary_marker
                raw_audio_response = False
                if binary_rpc_response:
                    try:
                        rpc_raw_body = base64.b64decode(encoded_rpc_body, validate=True)
                    except (ValueError, binascii.Error) as exc:
                        raise LogosNodeCommandError("logosnode infer returned invalid base64 response data") from exc
                    response_payload = {
                        "binary_response": True,
                        "content_type": rpc_content_type or "application/octet-stream",
                        "size": len(rpc_raw_body),
                    }
                else:
                    if response_payload is None:
                        response_payload = {}
                    raw_audio_response = (
                        status_override < 400
                        and isinstance(response_payload, str)
                        and is_multipart_payload(sync_payload)
                    )
                    rpc_raw_body = response_payload.encode("utf-8") if raw_audio_response else None
                if not isinstance(response_payload, dict) and not raw_audio_response:
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
                    headers=rpc_headers,
                    raw_body=rpc_raw_body,
                    content_type=rpc_content_type,
                )
            except LogosNodeOfflineError as exc:
                status_override = 503
                _, coerced_body = coerce_upstream_error(503, {"error": str(exc)})
                exec_result = ExecutionResult(
                    success=False,
                    response=coerced_body,
                    error=str(exc),
                    usage={},
                    is_streaming=False,
                    headers=None,
                )
            except LogosNodeCommandError as exc:
                status_override = 502
                _, coerced_body = coerce_upstream_error(502, {"error": str(exc)})
                exec_result = ExecutionResult(
                    success=False,
                    response=coerced_body,
                    error=str(exc),
                    usage={},
                    is_streaming=False,
                    headers=None,
                )
        else:
            exec_result = await _pipeline.executor.execute_sync(context.forward_url, headers, prepared_payload)
        response_at = datetime.datetime.now(datetime.timezone.utc)

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
        if exec_result.success and raw_audio_format:
            try:
                exec_result.raw_body, exec_result.content_type = render_metered_whisper_response(
                    response_payload, raw_audio_format
                )
            except ValueError as exc:
                exec_result.success = False
                exec_result.error = str(exc)
                exec_result.status_code = 502
                response_payload = {"error": str(exc)}
                status_override = 502
        if not exec_result.success:
            if not response_payload and exec_result.error:
                response_payload = {"error": exec_result.error}
            logger.error(
                f"Request failed (model_id={model_id}, provider_id={provider_id}): "
                f"{exec_result.error}, response={response_payload}"
            )

        if exec_result.success and context.provider_type == "cloud":
            response_payload, _ = _response_with_cost(response_payload, provider_id, model_id, response_at)

        usage_tokens = _usage_tokens_from_payload(response_payload)

        if log_id:
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
                    request_id=(scheduling_stats.get("request_id") if scheduling_stats else None),
                    queue_depth_at_arrival=(
                        scheduling_stats.get("queue_depth_at_arrival") if scheduling_stats else None
                    ),
                    utilization_at_arrival=(
                        scheduling_stats.get("utilization_at_arrival") if scheduling_stats else None
                    ),
                )
                # Persist the final result_status directly by log_id. record_completion
                # below only runs when scheduling_stats is present (it keys off
                # request_id), which left cloud requests with no scheduling stats —
                # e.g. a failed Azure call — at result_status NULL, rendering grey
                # (neither success nor error) on the statistics page.
                db.update_log_entry_metrics(
                    log_id=log_id,
                    provider_id=provider_id,
                    model_id=model_id,
                    result_status=("timeout" if timed_out else ("success" if exec_result.success else "error")),
                    error_message=(
                        error_message if timed_out else (exec_result.error if not exec_result.success else None)
                    ),
                )

        if scheduling_stats:
            status = "timeout" if timed_out else ("success" if exec_result.success else "error")
            _pipeline.record_completion(
                request_id=scheduling_stats.get("request_id"),
                result_status=status,
                error_message=(
                    error_message if timed_out else (exec_result.error if not exec_result.success else None)
                ),
                cold_start=scheduling_stats.get("is_cold_start"),
                usage_tokens=usage_tokens,
            )

        if rl_key:
            from logos.rate_limiter import get_rate_limiter

            total = usage_tokens.get("total_tokens") or (
                usage_tokens.get("prompt_tokens", 0) + usage_tokens.get("completion_tokens", 0)
            )
            get_rate_limiter().record_tokens(rl_key, total)

        _log_request_completion(
            model_id=model_id,
            request_id=request_id,
            start_time=_req_start,
            usage=usage_tokens,
            status=("timeout" if timed_out else ("success" if exec_result.success else "error")),
            is_streaming=False,
        )

        # Determine effective HTTP status code:
        #   1. status_override (from logosnode RPC result or error handlers) takes highest priority
        #   2. exec_result.status_code from the upstream HTTP response
        #   3. Fallback: 504 for timeout, 200 for success, 500 for error
        if status_override is not None:
            status_code = status_override
        elif exec_result.status_code is not None:
            status_code = exec_result.status_code
        else:
            status_code = 504 if timed_out else (200 if exec_result.success else 500)

        # Normalise error bodies to OpenAI shape and correct any wrongly-labelled
        # 5xx status codes (e.g. vLLM context-length sent as 500 → 400).
        if not exec_result.success:
            status_code, response_payload = coerce_upstream_error(
                status_code, response_payload or {"error": exec_result.error}
            )

        # Return dict for async jobs, JSONResponse for sync endpoints
        if is_async_job:
            if exec_result.raw_body is not None and exec_result.success:
                media_type = (exec_result.content_type or "").partition(";")[0].strip().lower()
                is_text_body = (
                    bool(raw_audio_format)
                    or media_type.startswith("text/")
                    or media_type
                    in {
                        "application/json",
                        "application/x-subrip",
                    }
                )
                if not is_text_body:
                    job_data = {
                        "content_base64": base64.b64encode(exec_result.raw_body).decode("ascii"),
                        "content_type": exec_result.content_type or "application/octet-stream",
                        "encoding": "base64",
                    }
                else:
                    try:
                        decoded_body = exec_result.raw_body.decode("utf-8")
                    except UnicodeDecodeError:
                        job_data = {
                            "content_base64": base64.b64encode(exec_result.raw_body).decode("ascii"),
                            "content_type": exec_result.content_type or "application/octet-stream",
                            "encoding": "base64",
                        }
                    else:
                        job_data = json.loads(decoded_body) if raw_audio_format == "json" else decoded_body
            else:
                job_data = response_payload
            return {"status_code": status_code, "data": job_data}
        else:
            response_headers = _decision_response_headers(request_id, scheduling_stats) or {}
            if exec_result.raw_body is not None and exec_result.success:
                if exec_result.content_type:
                    response_headers["content-type"] = exec_result.content_type
                return Response(
                    content=exec_result.raw_body,
                    status_code=status_code,
                    headers=response_headers,
                )
            return JSONResponse(content=response_payload, status_code=status_code, headers=response_headers)

    finally:
        if scheduling_stats and scheduling_stats.get("request_id"):
            try:
                _pipeline.scheduler.release(
                    model_id,
                    provider_id,
                    scheduling_stats.get("provider_type"),
                    scheduling_stats.get("request_id"),
                )
            except Exception as e:
                logger.error(f"Failed to release scheduler resources: {e}")


def _proxy_streaming_response(
    forward_url: str,
    proxy_headers: dict,
    payload: dict,
    log_id: Optional[int],
    provider_id: int,
    model_id: Optional[int],
    policy_id: int,
    classified: dict,
    request_id: Optional[str] = None,
):
    """
    Build streaming response for PROXY MODE using executor.
    """
    import datetime

    from fastapi.responses import StreamingResponse

    async def streamer():
        stream_log = _StreamingLogAccumulator()
        cost_enricher = _StreamingCostEnricher(provider_id, model_id)
        stream_status = StreamingExecutionStatus()
        ttft = None
        error_message = None

        try:
            async for chunk in _pipeline.executor.execute_streaming(
                forward_url,
                proxy_headers,
                payload,
                status=stream_status,
            ):
                # Track time to first token
                if ttft is None:
                    ttft = datetime.datetime.now(datetime.timezone.utc)
                    if log_id:
                        with DBManager() as db:
                            db.set_time_at_first_token(log_id)

                for outgoing_chunk in cost_enricher.feed(chunk):
                    yield outgoing_chunk
                    stream_log.feed(outgoing_chunk)
            for outgoing_chunk in cost_enricher.finish():
                yield outgoing_chunk
                stream_log.feed(outgoing_chunk)
        except Exception as exc:  # noqa: BLE001
            error_message = str(exc)
            for outgoing_chunk in cost_enricher.finish():
                yield outgoing_chunk
                stream_log.feed(outgoing_chunk)
            raise
        finally:
            if error_message is None:
                error_message = stream_status.error
            failed = error_message is not None
            # Log completion
            if log_id:
                stream_log.finish()
                response_payload = stream_log.response_payload()
                usage_tokens = _usage_tokens_from_payload(response_payload)

                with DBManager() as db:
                    if ttft is None and stream_log.first_chunk is not None and not error_message:
                        db.set_time_at_first_token(log_id)
                    db.set_response_payload(
                        log_id,
                        response_payload,
                        provider_id,
                        model_id,
                        usage_tokens,
                        policy_id,
                        classified,
                    )
                    db.update_log_entry_metrics(
                        log_id=log_id,
                        provider_id=provider_id,
                        model_id=model_id,
                        result_status="error" if failed else "success",
                        error_message=error_message,
                    )

    response_headers = {"X-Request-ID": request_id} if request_id else None
    return StreamingResponse(streamer(), media_type="text/event-stream", headers=response_headers)


async def _proxy_sync_response(
    forward_url: str,
    proxy_headers: dict,
    payload: dict,
    log_id: Optional[int],
    provider_id: int,
    model_id: Optional[int],
    policy_id: int,
    classified: dict,
    is_async_job=False,
    request_id: Optional[str] = None,
):
    """
    Build synchronous response for PROXY MODE using executor.
    """
    from fastapi.responses import JSONResponse

    exec_result = await _pipeline.executor.execute_sync(forward_url, proxy_headers, payload)
    response_at = datetime.datetime.now(datetime.timezone.utc)

    response_payload = exec_result.response
    if not exec_result.success and not response_payload and exec_result.error:
        response_payload = {"error": exec_result.error}
    if exec_result.success:
        response_payload, _ = _response_with_cost(response_payload, provider_id, model_id, response_at)

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
                classified,
            )
            db.update_log_entry_metrics(
                log_id=log_id,
                provider_id=provider_id,
                model_id=model_id,
                result_status="success" if exec_result.success else "error",
                error_message=None if exec_result.success else exec_result.error,
            )

    # Use upstream HTTP status code; fall back to 200/500 if unavailable
    status_code = (
        exec_result.status_code if exec_result.status_code is not None else (200 if exec_result.success else 500)
    )

    # Normalise error bodies to OpenAI shape
    if not exec_result.success:
        status_code, response_payload = coerce_upstream_error(
            status_code, response_payload or {"error": exec_result.error}
        )

    # Return dict for async jobs, JSONResponse for sync endpoints
    if is_async_job:
        return {"status_code": status_code, "data": response_payload}
    else:
        resp_headers = {"X-Request-ID": request_id} if request_id else None
        return JSONResponse(
            content=response_payload,
            status_code=status_code,
            headers=resp_headers,
        )


async def _execute_proxy_mode(
    body: Dict[str, Any],
    headers: Dict[str, str],
    auth: "AuthContext",
    deployments: list[Deployment],
    log_id: Optional[int],
    is_async_job: bool,
    request_id: Optional[str] = None,
    request_path: Optional[str] = None,
    priority: int = 1,
    required_provider_id: Optional[int] = None,
):
    """
    Direct model execution: skip classification, reuse scheduling/SDI, resolve auth from DB.

    Resolves the requested model from the DB (access-controlled by logos_key), then reuses the
    resource-mode pipeline with allowed_models restricted to that model.
    """
    requested_model_name = str(body.get("model") or "").strip()
    if not requested_model_name:
        raise HTTPException(status_code=400, detail="Proxy mode requires 'model' in payload")

    is_internal_benchmark = auth.environment == "model-provider-benchmark" and required_provider_id is not None
    if is_internal_benchmark:
        matching_deployments = [
            deployment for deployment in deployments if deployment["provider_id"] == required_provider_id
        ]
        model_id = matching_deployments[0]["model_id"] if len(matching_deployments) == 1 else None
        model_name = requested_model_name if model_id is not None else None
    else:
        with DBManager() as db:
            models_info = db.get_models_info(auth.key_value)

        model_name = _resolve_requested_model_name(requested_model_name, models_info)
        if model_name is None:
            raise HTTPException(
                status_code=404,
                detail=f"Model '{requested_model_name}' not available for this key",
            )

        model_id = None
        for row in models_info:
            mid, name = row["id"], row["name"]
            if name == model_name:
                model_id = mid
                break

    if model_id is None:
        raise HTTPException(
            status_code=404,
            detail=f"Model '{requested_model_name}' not available for this key",
        )

    # Ensure payload model matches DB name (avoid user-supplied mismatch)
    body = set_payload_field(body, "model", model_name)

    # Narrow deployments to the requested model to preserve provider metadata
    model_deployments = [d for d in deployments if d["model_id"] == model_id]
    if not model_deployments:
        raise HTTPException(status_code=404, detail=f"No deployment found for model '{model_name}'")

    # Proxy mode reuses the scheduling/execution pipeline. Policy + token
    # screening still run (we want policy thresholds enforced even when the
    # user names the model), but Laura's heavy ML ranking is skipped — it
    # has nothing to decide once the model is pinned.
    return await _execute_resource_mode(
        deployments=model_deployments,
        body=body,
        headers=headers,
        auth=auth,
        log_id=log_id,
        is_async_job=is_async_job,
        allowed_models_override=[model_id],
        request_id=request_id,
        request_path=request_path,
        skip_laura=True,
        priority=priority,
        required_provider_id=required_provider_id,
    )


async def _execute_resource_mode(
    deployments: list[Deployment],
    body: Dict[str, Any],
    headers: Dict[str, str],
    auth: "AuthContext",
    log_id: Optional[int],
    is_async_job: bool,
    allowed_models_override: Optional[list] = None,
    request_id: Optional[str] = None,
    request_path: Optional[str] = None,
    skip_laura: bool = False,
    priority: int = 1,
    required_provider_id: Optional[int] = None,
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
        auth: AuthContext containing api_key, team and routing limits
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
    policy = _extract_policy(headers, auth.key_value, body)

    # Create Pipeline Request
    pipeline_req = PipelineRequest(
        payload=body,
        headers=headers,
        request_id=request_id,
        policy=policy,
        allowed_models=allowed_models,
        deployments=deployments,
        skip_laura=skip_laura,
        request_path=request_path,
        required_provider_id=required_provider_id,
        # The key owner's queue priority; 0 falls back to the
        # policy-level priority inside the pipeline.
        default_priority=auth.default_priority,
        api_key_id=auth.api_key_id,
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

    provider_type = result.scheduling_stats.get("provider_type", "")

    rl_tpm_key = None
    if auth.cloud_rl is not None or auth.local_rl is not None:
        from logos.rate_limiter import RateLimitConfig, get_rate_limiter

        is_local = provider_type == "logosnode"
        rl_info = auth.local_rl if is_local else auth.cloud_rl
        rl_key = f"api_key:{auth.api_key_id}:{'local' if is_local else 'cloud'}"

        if rl_info:
            rl_cfg = RateLimitConfig(rpm=rl_info.get("rpm"), tpm=rl_info.get("tpm"))
            allowed, reason = get_rate_limiter().check_and_record(rl_key, rl_cfg)
            if not allowed:
                try:
                    _pipeline.scheduler.release(
                        result.model_id,
                        result.provider_id,
                        provider_type,
                        result.scheduling_stats.get("request_id") or request_id,
                    )
                except Exception:
                    logger.warning("Failed to release scheduler slot after rate limit reject")
                if is_async_job:
                    return {
                        "status_code": 429,
                        "data": {"error": f"Rate limit exceeded: {reason}"},
                    }
                # Retry-After: the limiter uses a sliding 60s window, so the
                # budget is guaranteed to have room again after one window.
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded: {reason}",
                    headers={"Retry-After": str(RateLimitConfig.window_seconds)},
                )

            if rl_info.get("tpm") is not None:
                rl_tpm_key = rl_key

    with DBManager() as db:
        try:
            _check_budget_if_cloud(
                db, auth, provider_type != "logosnode", datetime.date.today().replace(day=1).isoformat()
            )
        except Exception as e:
            try:
                _pipeline.scheduler.release(
                    result.model_id,
                    result.provider_id,
                    provider_type,
                    result.scheduling_stats.get("request_id") or request_id,
                )
            except Exception:
                logger.warning("Failed to release scheduler slot after budget reject")
            if isinstance(e, HTTPException) and is_async_job:
                _, err_body = coerce_upstream_error(e.status_code, {"error": str(e.detail)})
                _record_log_failure(
                    log_id,
                    result.scheduling_stats.get("request_id") or request_id,
                    str(e.detail),
                    model_id=result.model_id,
                    provider_id=result.provider_id,
                    classification_stats=result.classification_stats,
                    scheduling_stats=result.scheduling_stats,
                )
                return {"status_code": e.status_code, "data": err_body}
            raise

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
                rl_key=rl_tpm_key,
                api_key_id=auth.api_key_id,
            )
        else:
            # Sync endpoints support streaming
            # whisper-1 ignores stream=true and returns a normal JSON/text
            # response. Keep it on the synchronous response path so Logos
            # preserves the upstream content type instead of framing it as SSE.
            resolved_model_name = getattr(result.execution_context, "model_name", "") or ""
            resolved_whisper_model = "whisper" in resolved_model_name.lower()
            if payload_requests_streaming(body) and not (is_whisper_payload(body) or resolved_whisper_model):
                return await _streaming_response(
                    result.execution_context,
                    body,
                    log_id,
                    result.provider_id,
                    result.model_id,
                    -1,  # Policy ID not implemented
                    result.classification_stats,
                    result.scheduling_stats,
                    request_path=request_path,
                    rl_key=rl_tpm_key,
                    api_key_id=auth.api_key_id,
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
                    rl_key=rl_tpm_key,
                    api_key_id=auth.api_key_id,
                )
    except Exception as e:
        logger.error(f"Error in _execute_resource_mode: {e}", exc_info=True)
        try:
            _pipeline.record_completion(
                request_id=result.scheduling_stats.get("request_id"),
                result_status="error",
                error_message=str(e),
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
    auth: "AuthContext",
    path: str,
    log_id: Optional[int],
    is_async_job: bool = False,
    request_id: Optional[str] = None,
    priority: int = 1,
    required_provider_id: Optional[int] = None,
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
        auth: AuthContext mapping to the requesting API key
        path: API endpoint path (e.g., "chat/completions")
        log_id: Usage log ID for tracking (None for requests without logging)
        is_async_job: Whether this is a background job (affects error handling)
            - False: Direct endpoint - client waits, raises HTTPException for errors
            - True: Background job - client gets job_id, returns error dict for errors

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
        _record_log_failure(
            log_id,
            request_id,
            "No models available for this API key.",
            result_status="error",
        )
        if is_async_job:
            return {
                "status_code": 404,
                "data": {"error": "No models available for this API key."},
            }
        else:
            raise HTTPException(status_code=404, detail="No models available for this API key.")

    # Jobs reach this point without going through handle_sync_request, so they
    # publish their live view here. start() is non-destructive, so a request
    # that already arrived on the sync path keeps the entry it has.
    _live_streams.start(request_id, prompt_tokens=estimate_prompt_tokens(body), prompt_estimated=True)

    response = None
    try:
        # PROXY mode (body["model"] specified → direct forwarding)
        if body.get("model"):
            response = await _execute_proxy_mode(
                body=body,
                headers=headers,
                auth=auth,
                deployments=deployments,
                log_id=log_id,
                is_async_job=is_async_job,
                request_id=request_id,
                request_path=path,
                priority=priority,
                required_provider_id=required_provider_id,
            )

        else:
            # RESOURCE mode (no body["model"] → classification + scheduling)
            response = await _execute_resource_mode(
                deployments=deployments,
                body=body,
                headers=headers,
                auth=auth,
                log_id=log_id,
                is_async_job=is_async_job,
                request_id=request_id,
                request_path=path,
                priority=priority,
                required_provider_id=required_provider_id,
            )
        return response
    except HTTPException as exc:
        _record_log_failure(log_id, request_id, str(exc.detail), result_status="error")
        if is_async_job:
            return {"status_code": exc.status_code, "data": {"error": exc.detail}}
        raise
    except Exception as exc:
        _record_log_failure(log_id, request_id, str(exc), result_status="error")
        raise
    finally:
        # Same hand-off as handle_sync_request: a stream keeps its entry until
        # the streamer ends it, everything else ends here.
        if not isinstance(response, StreamingResponse):
            _live_streams.finish(request_id)


_CLIENT_DISCONNECT_POLL_SECONDS = 1.0


async def _wait_for_client_disconnect(request: Request) -> None:
    """Return once the client has gone away."""
    while not await request.is_disconnected():
        await asyncio.sleep(_CLIENT_DISCONNECT_POLL_SECONDS)


async def _settle(task: asyncio.Task) -> Any:
    """Cancel ``task`` and wait for its cleanup to finish.

    The pipeline releases the scheduler slot in a ``finally`` block, so the
    caller must not unwind before that has run — otherwise the lane stays
    booked for a request that is already gone.
    """
    task.cancel()
    with suppress(asyncio.CancelledError, Exception):
        return await task
    return None


async def _discard_response(response: Any) -> None:
    """Close a response nobody is left to read.

    ``_streaming_response`` pulls the first chunk before handing the response
    over, so by then the upstream connection is already open. Closing the body
    iterator unwinds the executor's stream contexts instead of leaving them to
    the garbage collector.
    """
    iterator = getattr(response, "body_iterator", None)
    if iterator is None:
        return
    with suppress(Exception):
        await iterator.aclose()


async def _execute_cancelling_on_disconnect(request: Request, **kwargs):
    """Run ``route_and_execute``, dropping the work if the client leaves.

    Uvicorn does not tear the handler down when a client vanishes mid-request,
    so the call kept a worker generating a response nobody would read — a ghost
    request holding a GPU lane for as long as the generation took. Cancelling
    the task unwinds the executor's ``httpx.AsyncClient`` context, which closes
    the upstream connection so vLLM aborts the sequence.

    Whether the response ends up streaming is decided deep inside the pipeline:
    resource mode can resolve to Whisper and answer synchronously even for
    ``stream: true``. So this reacts to what came back rather than predicting
    it. Once a streaming response is handed on, Starlette's own watcher takes
    over — it listens for the disconnect while the body is consumed and cancels
    the generator, which unwinds the same stream context.
    """
    work = asyncio.create_task(route_and_execute(**kwargs))
    watcher = asyncio.create_task(_wait_for_client_disconnect(request))
    try:
        done, _ = await asyncio.wait({work, watcher}, return_when=asyncio.FIRST_COMPLETED)
    except asyncio.CancelledError:
        await _settle(work)
        raise
    finally:
        watcher.cancel()

    # The watcher may land in the same batch as a finished task. Its probe
    # consumes the http.disconnect message, so a response produced in that
    # same tick can no longer be handed to Starlette's watcher — drop it here
    # instead of streaming it into a closed socket.
    if work in done and watcher not in done:
        return work.result()

    await _discard_response(await _settle(work))

    request_id = kwargs.get("request_id")
    logger.info("Cancelled request %s: client disconnected before the response was ready", request_id)
    _record_log_failure(
        kwargs.get("log_id"),
        request_id,
        "Client disconnected before the response was ready; upstream request cancelled.",
    )
    # 499, as nginx uses it: the client closed the request. Nobody is left to
    # read this, but the status keeps the access log honest.
    return JSONResponse(status_code=499, content={"detail": "Client closed request"})


def _benchmark_provider_affinity(
    headers: Dict[str, str],
    body: Dict[str, Any],
    deployments: list[Deployment],
) -> Optional[int]:
    """Validate a signed active benchmark job and return its required worker."""

    normalized_headers = {str(name).lower(): str(value) for name, value in headers.items()}
    job_value = normalized_headers.get(BENCHMARK_JOB_HEADER)
    provider_value = normalized_headers.get(BENCHMARK_PROVIDER_HEADER)
    token = normalized_headers.get(BENCHMARK_TOKEN_HEADER)
    phase = normalized_headers.get(BENCHMARK_PHASE_HEADER, "measurement")
    affinity_values = (job_value, provider_value, token)

    if not any(affinity_values):
        return None
    if not all(affinity_values) or not _INTERNAL_SECRET:
        raise HTTPException(status_code=401, detail="Invalid benchmark worker affinity")
    if phase not in {"warmup", "measurement"}:
        raise HTTPException(status_code=401, detail="Invalid benchmark worker affinity")

    try:
        job_id = int(job_value)
        provider_id = int(provider_value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid benchmark worker affinity") from exc
    if job_id <= 0 or provider_id <= 0:
        raise HTTPException(status_code=401, detail="Invalid benchmark worker affinity")

    model_name = str(body.get("model") or "").strip()
    expected_token = benchmark_affinity_token(
        secret=_INTERNAL_SECRET,
        job_id=job_id,
        provider_id=provider_id,
        model=model_name,
    )
    if not hmac.compare_digest(token.encode("utf-8"), expected_token.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid benchmark worker affinity")

    with DBManager() as db:
        job = db.get_job(job_id)
    if not job or job.get("environment") != "model-provider-benchmark":
        raise HTTPException(status_code=401, detail="Invalid benchmark worker affinity")

    job_status = job.get("status")
    if hasattr(job_status, "value"):
        job_status = job_status.value
    if job_status != JobStatus.RUNNING.value:
        raise HTTPException(status_code=409, detail="Benchmark job is no longer running")

    payload = job.get("request_payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=401, detail="Invalid benchmark worker affinity") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=401, detail="Invalid benchmark worker affinity")

    try:
        payload_provider_id = int(payload.get("provider_id"))
        payload_model_id = int(payload.get("model_id"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid benchmark worker affinity") from exc
    if payload_provider_id != provider_id or str(payload.get("model_name") or "") != model_name:
        raise HTTPException(status_code=401, detail="Invalid benchmark worker affinity")
    expected_session_id = payload.get("provider_session_id")
    if expected_session_id:
        snapshot = _logosnode_registry.peek_runtime_snapshot(provider_id)
        if snapshot is None or snapshot.get("session_id") != expected_session_id:
            raise HTTPException(status_code=409, detail="Benchmark provider restarted or disconnected")

    if not any(
        deployment["provider_id"] == provider_id and deployment["model_id"] == payload_model_id
        for deployment in deployments
    ):
        raise HTTPException(
            status_code=403,
            detail="Benchmark API key cannot access the required provider-model pair",
        )

    if phase == "measurement":
        with DBManager() as db:
            db.record_benchmark_request_started(job_id)

    return provider_id


# How often the startup grace period re-checks for a (re)connected worker.
_WORKER_CONNECT_POLL_SECONDS = 1.0
# How long the grace period lasts, both for the window after the orchestrator
# starts and for the window after an already-connected worker drops (reboot).
# Such a window is one in which no worker node serves a model, during which
# every logosnode deployment of it is filtered out and the request 404s with
# "No available model deployments" — enough to kill a running consumer
# mid-task. Workers re-attach within seconds of coming back up, so while the
# window is open a request for a model no worker serves yet waits instead of
# failing, turning the outage into a delay. Once it has run out, the instant
# 404 comes back: a worker still missing then is down, not mid-redeploy.
_STARTUP_GRACE_PERIOD_S = 120.0
# Monotonic anchor for the grace window. The wall-clock _SERVER_START_TIME
# can jump (NTP) and must not stretch or shrink the window with it.
_SERVER_START_MONOTONIC = time.monotonic()


def _startup_grace_remaining_s() -> float:
    """How much of the startup grace period is left (0 once it has run out)."""
    return max(0.0, _STARTUP_GRACE_PERIOD_S - (time.monotonic() - _SERVER_START_MONOTONIC))


def _worker_reconnect_grace_remaining_s(raw_deployments: list[Deployment]) -> float:
    """How long a request may wait because one of the key's workers recently dropped.

    The startup window only covers the orchestrator's own (re)start. A worker
    node that reboots or is redeployed on its own drops its session later,
    and its models go unroutable the moment the registry loses them — the
    same failure, anchored to the drop instead of the boot. For every
    logosnode deployment of the key, take the latest of the drop-grace
    deadlines; the freshest drop dominates.
    """
    remaining = 0.0
    for deployment in raw_deployments:
        if _normalize_provider_type(deployment.get("type")) != "logosnode":
            continue
        remaining = max(
            remaining,
            _logosnode_registry.disconnect_grace_remaining_s(int(deployment["provider_id"]), _STARTUP_GRACE_PERIOD_S),
        )
    return remaining


def _client_timeout_s(payload: dict) -> Optional[float]:
    """The client's ``timeout_s`` as a positive float, or None if absent/invalid."""
    try:
        value = float(payload.get("timeout_s"))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


async def _wait_for_worker_connect(
    raw_deployments: list[Deployment],
    payload: dict,
    request: Optional[Request] = None,
    client_timeout_s: Optional[float] = None,
) -> list[Deployment]:
    """Re-run the deployment filter until a worker serves the model, the grace period runs out, or the client leaves.

    ``raw_deployments`` is what the DB granted this key before the logosnode
    filter dropped everything because no worker is connected (redeploy). Each
    poll re-asks the registry; the moment a worker re-attaches and declares
    its capabilities, the filter hands the deployments back and the request
    proceeds. The wait is bounded by the later of the two grace windows —
    what is left of the startup window, and what is left of a recently
    dropped worker's reconnect window (see ``_worker_reconnect_grace_remaining_s``)
    — and by the client's ``timeout_s`` if it is smaller. Neither window
    resets per request, and a worker that already re-attached does not cancel
    the wait for the models still missing.
    """
    wait_s = max(_startup_grace_remaining_s(), _worker_reconnect_grace_remaining_s(raw_deployments))
    if client_timeout_s is not None:
        wait_s = min(wait_s, client_timeout_s)
    if wait_s <= 0:
        return []
    deadline = time.monotonic() + wait_s
    logger.info("No worker is serving the requested model right now; waiting up to %ss for one to (re)connect", wait_s)
    deployments: list[Deployment] = []
    while time.monotonic() < deadline:
        if request is not None and await request.is_disconnected():
            break
        await asyncio.sleep(min(_WORKER_CONNECT_POLL_SECONDS, deadline - time.monotonic()))
        deployments = await _filter_logosnode_deployments(raw_deployments, payload=payload)
        if deployments:
            logger.info("Worker connected during startup grace period; routing the request")
            return deployments
    return deployments


async def handle_sync_request(path: str, request: Request):
    """
    Handle synchronous (non-job) requests for both /v1 and /openai endpoints.
    Performs authentication, model setup, and routing/execution. Queue
    priority is derived from the authenticated API key's default_priority
    (falling back to the policy-level priority inside the pipeline).
    """
    # Authenticate with profile-based auth (REQUIRED for v1/openai/jobs endpoints)
    headers, auth, body, client_ip, log_id = await auth_parse_log(request, use_profile_auth=True)
    request_id = secrets.token_urlsafe(16)

    # Publish the request to the live view from the moment it is known, so the
    # statistics feed shows its (estimated) prompt size while it waits for a
    # deployment or a reconnecting worker instead of sitting as a blank row.
    _live_streams.start(request_id, prompt_tokens=estimate_prompt_tokens(body), prompt_estimated=True)

    response = None
    try:
        try:
            with DBManager() as db:
                if log_id:
                    db.update_log_entry_metrics(
                        log_id=log_id,
                        request_id=request_id,
                        timeout_s=body.get("timeout_s"),
                    )
                raw_deployments, allowed_models = request_setup(headers, auth.api_key_id, db=db)
            required_provider_id = _benchmark_provider_affinity(headers, body, raw_deployments)
            if required_provider_id is not None:
                raw_deployments = [
                    deployment for deployment in raw_deployments if deployment["provider_id"] == required_provider_id
                ]
            deployments = await _filter_logosnode_deployments(raw_deployments, payload=body)
        except HTTPException as e:
            _record_log_failure(log_id, request_id, str(e.detail), result_status="error")
            raise
        except PermissionError as e:
            _record_log_failure(log_id, request_id, str(e), result_status="error")
            raise HTTPException(status_code=401, detail=str(e))
        except ValueError as e:
            _record_log_failure(log_id, request_id, str(e), result_status="error")
            raise HTTPException(status_code=400, detail=str(e))

        if not deployments and raw_deployments:
            # The key is granted models that no worker serves right now — either
            # the orchestrator just (re)started and the workers are still
            # (re)attaching, or a worker dropped a moment ago (reboot) and its
            # models are unroutable until it comes back. Give the missing
            # workers a chance to (re)connect instead of failing instantly; the
            # window stays in effect even though other workers may already have
            # re-attached.
            deployments = await _wait_for_worker_connect(
                raw_deployments, payload=body, request=request, client_timeout_s=_client_timeout_s(body)
            )

        if not deployments:
            requested_model = body.get("model", "unknown")
            msg = f"No available model deployments for model '{requested_model}' for this key"
            _record_log_failure(log_id, request_id, msg, result_status="error")
            raise HTTPException(status_code=404, detail=msg)

        execute_kwargs = dict(
            deployments=deployments,
            body=body,
            headers=headers,
            auth=auth,
            path=path,
            log_id=log_id,
            request_id=request_id,
            required_provider_id=required_provider_id,
        )
        response = await _execute_cancelling_on_disconnect(request, **execute_kwargs)
        return response
    finally:
        # A streaming response hands the live entry to its generator: the
        # streamer drops it when the stream ends. Every other outcome — sync
        # response, an error raise, the client walking away — ends the request
        # here.
        if not isinstance(response, StreamingResponse):
            _live_streams.finish(request_id)


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
    # Authenticate before parsing multipart bodies. This prevents unauthenticated
    # callers from consuming the audio upload/base64 memory budget.
    headers = dict(request.headers)
    client_ip = get_client_ip(request)
    auth = authenticate_api_key(headers) if use_profile_auth else None

    # OpenAI-compatible audio uploads use multipart/form-data. Other inference
    # operations retain the existing JSON request contract.
    if is_audio_upload_path(request.url.path):
        body = await parse_audio_upload(request)
    else:
        try:
            body = await request.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON body") from exc

    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON payload must be an object")

    if use_profile_auth:
        with DBManager() as db:

            # Rate limits apply to every key, including those owned by
            # logos_admins. Admin keys derive their limits from their team /
            # key settings exactly like any other key. Budget is checked later,
            # once permitted deployments are known (see _check_budget_if_cloud).
            s = auth.settings or {}
            team_info = db.get_team(auth.team_id) if auth.team_id is not None else None

            generic_rpm = s.get("rpm_limit")
            generic_tpm = s.get("tpm_limit")

            cloud_rpm = (
                s.get("cloud_rpm_limit") or generic_rpm or (team_info and team_info.get("default_cloud_rpm_limit"))
            )
            cloud_tpm = (
                s.get("cloud_tpm_limit") or generic_tpm or (team_info and team_info.get("default_cloud_tpm_limit"))
            )
            local_rpm = (
                s.get("local_rpm_limit") or generic_rpm or (team_info and team_info.get("default_local_rpm_limit"))
            )
            local_tpm = (
                s.get("local_tpm_limit") or generic_tpm or (team_info and team_info.get("default_local_tpm_limit"))
            )

            if cloud_rpm is not None or cloud_tpm is not None:
                auth.cloud_rl = {"rpm": cloud_rpm, "tpm": cloud_tpm}
            if local_rpm is not None or local_tpm is not None:
                auth.local_rl = {"rpm": local_rpm, "tpm": local_tpm}

            r_log, c_log = db.log_usage(
                api_key_id=auth.api_key_id,
                team_id=auth.team_id,
                user_id=auth.user_id,
                environment=auth.environment,
                log_level=auth.log_level,
                client_ip=client_ip,
                input_payload=sanitized_payload_for_logging(body),
                headers=sanitized_headers_for_persistence(headers),
            )
            if c_log == 200:
                log_id = int(r_log["log-id"])

        return headers, auth, body, client_ip, log_id

    return headers, None, body, client_ip, None


def _check_budget_if_cloud(db: DBManager, auth: "AuthContext", is_cloud: bool, month_start: str) -> None:
    """
    Raise HTTPException(402) if this key/team is over its monthly budget.

    Only cloud usage is metered (logosnode/local providers have no configured
    token pricing in token_prices, so they always cost $0), so this is a
    no-op when the request that actually got scheduled isn't routing to a
    cloud provider at all. Called post-scheduling (see _execute_resource_mode)
    with the real resolved provider type, not a guess from the permission list --
    that's what lets this be exact for mixed cloud+local keys instead of only
    for pure-type ones.
    """
    if not is_cloud:
        return

    key_type = getattr(auth, "key_type", "user")

    if key_type == "application":
        app_budget_limit = db.get_api_key_budget_limit(auth.api_key_id)
        if app_budget_limit is not None:
            app_used = db.get_api_key_budget_usage(auth.api_key_id, month_start)
            if app_used >= app_budget_limit:
                raise HTTPException(status_code=402, detail="Application monthly budget exceeded.")
    else:
        if auth.team_id is not None:
            team_info = db.get_team(auth.team_id)
            if team_info and team_info.get("team_monthly_budget_micro_cents"):
                team_limit = team_info["team_monthly_budget_micro_cents"]
                team_used = db.get_team_budget_usage(auth.team_id, month_start)
                if team_used >= team_limit:
                    raise HTTPException(status_code=402, detail="Team monthly budget exceeded. Contact your admin.")

        personal_limit = db.get_api_key_budget_limit(auth.api_key_id)
        if personal_limit is not None:
            personal_used = db.get_api_key_budget_usage(auth.api_key_id, month_start)
            if personal_used >= personal_limit:
                raise HTTPException(status_code=402, detail="Personal monthly budget exceeded.")


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
    # Auth with full context + initial logging
    headers, auth, json_data, client_ip, log_id = await auth_parse_log(request, use_profile_auth=True)

    # Persist job and run it asynchronously
    job_payload = JobSubmission(
        path=path,
        method=request.method,
        headers=sanitized_headers_for_persistence(headers),
        body=sanitized_payload_for_logging(json_data),
        client_ip=client_ip,
        api_key_id=auth.api_key_id,
        team_id=auth.team_id,
        user_id=auth.user_id,
        environment=auth.environment,
    )
    job_id = JobService.create_job(job_payload)
    status_url = str(request.url_for("get_job_status", job_id=job_id))

    # Fire-and-forget: run the heavy proxy/classification pipeline off the request path.
    task = asyncio.create_task(process_job(job_id, path, headers, dict(json_data), client_ip, auth, log_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return JSONResponse(
        status_code=202,
        content={
            "job_id": job_id,
            "status_url": status_url,
            "team_id": auth.team_id,
        },
        # Standard async-request pattern: 202 points at the status resource.
        headers={"Location": status_url},
    )


async def process_job(
    job_id: int,
    path: str,
    headers: Dict[str, str],
    json_data: Dict[str, Any],
    client_ip: str,
    auth: "AuthContext",
    log_id: Optional[int],
):
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
        result = await execute_proxy_job(path, headers, json_data, client_ip, auth, log_id)
        JobService.mark_success(job_id, result)
    # Exception while processing the job is caught and persisted in the database
    except Exception as e:
        logging.exception("Job %s failed", job_id)
        JobService.mark_failed(job_id, str(e))
        return {"status_code": 500, "data": {"error": "Job failed"}}
    return result


async def execute_proxy_job(
    path: str,
    headers: Dict[str, str],
    json_data: Dict[str, Any],
    client_ip: str,
    auth: "AuthContext",
    log_id: Optional[int],
) -> Dict[str, Any]:
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

    request_id = secrets.token_urlsafe(16)

    # Same early publication as the sync path: the moment the job has a
    # request id, its (estimated) prompt is on the feed instead of the row
    # sitting blank through the worker wait below.
    _live_streams.start(request_id, prompt_tokens=estimate_prompt_tokens(json_data), prompt_estimated=True)
    try:
        # Get available models for this API key
        try:
            with DBManager() as db:
                if log_id:
                    db.update_log_entry_metrics(
                        log_id=log_id,
                        request_id=request_id,
                        timeout_s=json_data.get("timeout_s"),
                    )
                raw_deployments, allowed_models = request_setup(headers, auth.api_key_id, db=db)
            deployments = await _filter_logosnode_deployments(raw_deployments, payload=json_data)
        except PermissionError as e:
            _record_log_failure(log_id, request_id, str(e), result_status="error")
            _, err_body = coerce_upstream_error(401, {"error": str(e)})
            return {"status_code": 401, "data": err_body}
        except ValueError as e:
            _record_log_failure(log_id, request_id, str(e), result_status="error")
            _, err_body = coerce_upstream_error(400, {"error": str(e)})
            return {"status_code": 400, "data": err_body}

        # Same windows as the sync path: a job submitted while no worker is
        # connected (startup or a worker reboot) must not fail before the
        # workers re-attach.
        if not deployments and raw_deployments:
            deployments = await _wait_for_worker_connect(
                raw_deployments, payload=json_data, client_timeout_s=_client_timeout_s(json_data)
            )

        # Force non-streaming for jobs without adding unsupported multipart fields.
        json_data = force_non_streaming_payload(json_data)

        # Route and execute request
        return await route_and_execute(
            deployments=deployments,
            body=json_data,
            headers=headers,
            auth=auth,
            path=path,
            log_id=log_id,
            is_async_job=True,
            request_id=request_id,
        )
    finally:
        # A job never streams, so nothing here hands the entry on: every way
        # out — error dict above, route_and_execute's own finally, an
        # unexpected raise — ends the entry here at the latest.
        _live_streams.finish(request_id)


_LOGOSNODE_CMD_TIMEOUTS: dict[str, int] = {
    "apply_lanes": 180,
    "reconfigure_lane": 180,
    # sleep_lane with mode="wait" first drains in-flight requests (the worker
    # budgets 30 s for that), so a fixed 30 s here would time out exactly when
    # a busy lane actually drains. The planner uses 120 s for its own sleeps.
    "sleep_lane": 120,
    "wake_lane": 120,
    "delete_lane": 30,
}


async def _dispatch_logosnode_command(provider_id: int, action: str, params: dict[str, Any] | None = None):
    try:
        timeout = _LOGOSNODE_CMD_TIMEOUTS.get(action, 20)
        return await _logosnode_registry.send_command(
            provider_id,
            action=action,
            params=params or {},
            timeout_seconds=timeout,
        )
    except LogosNodeOfflineError as exc:
        return JSONResponse(status_code=503, content={"error": str(exc)})
    except LogosNodeCommandError as exc:
        return JSONResponse(status_code=502, content={"error": str(exc)})


def _find_uncalibrated_models_on_provider(provider_id: int) -> list[str]:
    """Return every configured model on a provider that still needs calibration.

    Used by the admin endpoint to report what the worker is likely to walk
    in its next calibration session — the worker makes the final selection,
    but this lets the API caller see the candidate list up front. Sourced
    from configured_models so models the worker stripped from
    capabilities_models (because they have no profile yet) are visible.
    """
    if _logosnode_facade is None:
        return []
    candidates = _logosnode_facade.get_configured_models(provider_id)
    if not candidates:
        candidates = _logosnode_facade.get_worker_capabilities(provider_id)
    try:
        profiles = _logosnode_facade.get_model_profiles(provider_id)
    except Exception:
        profiles = {}
    uncalibrated: list[str] = []
    for model_name in candidates:
        profile = profiles.get(model_name)
        collapsed_envelope = (
            profile is not None
            and profile.min_kv_cache_mb is not None
            and profile.max_kv_cache_mb is not None
            and profile.min_kv_cache_mb > 0
            and profile.min_kv_cache_mb == profile.max_kv_cache_mb
        )
        if (
            profile is None
            or profile.base_residency_mb is None
            or profile.sleeping_residual_mb is None
            or profile.sleep_l1_transient_host_ram_mb is None
            or (
                profile is not None
                and profile.residency_source == "calibrated"
                and not profile.kv_cache_to_max_model_len_pairs
            )
            or collapsed_envelope
        ):
            uncalibrated.append(model_name)
    return uncalibrated


# ============================================================================
# OPENAI-COMPATIBLE MODEL LISTING
# ============================================================================


# The high-water mark only changes when a worker snapshot arrives (a few to a
# dozen seconds per node), and every model endpoint calls into this, so the
# lookup result is cached for a short TTL instead of opening a fresh
# DBManager session per call — /v1/models took two connections where it
# previously took one. A failed lookup is never cached, so a broken database
# recovers on the very next call. No lock is needed: every caller runs on the
# asyncio event loop.
_HISTORIC_MAX_CONTEXT_TTL_SECONDS = 10.0
_historic_max_context_cache: tuple[float, dict[str, int]] | None = None


def _clear_historic_max_context_cache() -> None:
    """Drop the cached historic maxima (used by the tests; production never needs it)."""
    global _historic_max_context_cache
    _historic_max_context_cache = None


def _historic_max_context_by_model() -> dict[str, int]:
    """Model name -> widest context ever reported for it, from the database.

    The durable counterpart of the live runtime snapshots: ``upsert_model_profiles``
    keeps a high-water mark per (provider, model) in ``model_profiles`` on every
    worker snapshot, so this is still what a model's context is when no
    workernode is connected to say otherwise. Returns an empty mapping when the
    database cannot be reached — the live figures then stand on their own, as
    before. The result is cached for a short TTL (see above) because the value
    only changes when a worker snapshot arrives.
    """
    global _historic_max_context_cache
    now = time.monotonic()
    cached = _historic_max_context_cache
    if cached is not None and now - cached[0] < _HISTORIC_MAX_CONTEXT_TTL_SECONDS:
        return cached[1]
    try:
        with DBManager() as db:
            historic = db.get_historic_max_context_by_model()
    except Exception:
        # Fail open — the live snapshots still stand on their own — but say so:
        # a persistently broken lookup must not look like "no model has a
        # historic context".
        logger.warning("Failed to load the historic max context by model", exc_info=True)
        return {}
    _historic_max_context_cache = (now, historic)
    return historic


def _served_context_window_stats() -> dict[str, dict[str, int]]:
    """Per-model context windows derived from the logosnode runtime snapshots.

    Three numbers per model, all in tokens and all omitted when unknown:

    ``current_min``  the smallest window being served right now. A request may
                     be routed to any deployment, so this is the only value
                     that holds unconditionally.
    ``current_max``  the largest window being served right now. Reachable only
                     when the request lands there, which is what the
                     context-aware routing in ``_filter_logosnode_deployments``
                     arranges.
    ``overall``      the widest this model is ever served with — what a lane
                     runs at once it gets all the KV cache it asks for.
                     Independent of what is loaded at the moment, so it is
                     known even for a model with no live lane, and it is the
                     ceiling ``current_max`` can grow to. The live snapshots
                     only say this while a workernode is connected, so the
                     number is topped up from the historic maximum the
                     database keeps per model (#829): when every workernode
                     is offline, that — not a client-side guess — is what the
                     clients size the session from.
    """
    stats: dict[str, dict[str, int]] = {}
    try:
        provider_ids = _logosnode_registry.active_provider_ids()
    except Exception:
        provider_ids = []

    def _record(model: str, field: str, value: int, *, keep_smallest: bool = False) -> None:
        entry = stats.setdefault(model, {})
        current = entry.get(field)
        if current is None:
            entry[field] = value
        elif keep_smallest:
            entry[field] = min(current, value)
        else:
            entry[field] = max(current, value)

    for provider_id in provider_ids:
        snap = _logosnode_registry.peek_runtime_snapshot(provider_id)
        runtime = (snap or {}).get("runtime")
        if not isinstance(runtime, dict):
            continue
        model_profiles = runtime.get("model_profiles")
        if not isinstance(model_profiles, dict):
            model_profiles = {}
        for model, profile in model_profiles.items():
            native = _profile_native_context_length(profile)
            if native > 0:
                _record(model, "overall", native)
        lanes = runtime.get("lanes")
        if not isinstance(lanes, list):
            continue
        for lane in lanes:
            if not isinstance(lane, dict):
                continue
            window = _lane_served_context_window(lane, model_profiles)
            if window <= 0:
                continue
            model = lane["model"]
            _record(model, "current_min", window, keep_smallest=True)
            _record(model, "current_max", window)

    # The live snapshots above only exist while workernodes are connected.
    # Top the "overall" figure up with the historic maximum the database keeps
    # per model, so it is still known when every node is offline (#829) and so
    # a wider window reported on another node (or by an earlier calibration)
    # is not lost while this node runs the model narrower.
    for model, value in _historic_max_context_by_model().items():
        entry = stats.setdefault(model, {})
        if value > entry.get("overall", 0):
            entry["overall"] = value
    return stats


def _served_context_windows() -> dict[str, int]:
    """Model name -> smallest currently served context window (tokens).

    The conservative view of :func:`_served_context_window_stats`, kept as its
    own helper because most callers only ever want the safe number.
    """
    return {
        model: entry["current_min"] for model, entry in _served_context_window_stats().items() if "current_min" in entry
    }


def _model_context_fields(entry: Optional[dict[str, int]]) -> dict[str, int]:
    """Context-window fields for one model in an OpenAI-style model object.

    Three numbers, named for what they are:

    ``max_model_len_current_min``  the smallest window being served right now.
                                   The one figure that holds whichever worker
                                   answers, so a client that never wants a
                                   rejected request sizes itself from this.
    ``max_model_len_current_max``  the largest window being served right now.
                                   Reachable because long requests are routed
                                   to a deployment that fits them.
    ``max_model_len_overall``      the widest this model is ever served with,
                                   independent of what is loaded at the moment.
                                   The number to write into a config file that
                                   is only read at startup.

    ``max_model_len`` repeats the first of those under the name vLLM itself
    uses, so an OpenAI-compatible client that already reads that field keeps
    working. Every field is omitted when unknown, so cloud models and
    never-calibrated models keep the object they had before any of this existed.
    """
    if not entry:
        return {}
    fields: dict[str, int] = {}
    if entry.get("current_min"):
        fields["max_model_len"] = entry["current_min"]
        fields["max_model_len_current_min"] = entry["current_min"]
    if entry.get("current_max"):
        fields["max_model_len_current_max"] = entry["current_max"]
    if entry.get("overall"):
        fields["max_model_len_overall"] = entry["overall"]
    return fields


# ============================================================================
# ROUTERS
# ============================================================================
#
# The route handlers live in logos/routers/, grouped by domain. They are
# imported here, at the bottom of the module, because the routers import the
# module-level state defined above; importing them at the top would make main
# and the routers import each other mid-initialisation.
#
# The include order matters: user_facing holds the /v1/{path:path} catch-all
# and is included last, so no route of another router can be shadowed by it.
# Add new routers above that line.

from logos.routers import admin, internal, logosnode, monitoring, user_facing  # noqa: E402

app.include_router(monitoring.router)
app.include_router(internal.router)
app.include_router(logosnode.router)
app.include_router(admin.router)
app.include_router(user_facing.router)
