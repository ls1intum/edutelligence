"""Worker (LogosWorkerNode) provider endpoints under /logosdb/providers/logosnode."""

import asyncio
import json
import logging
import os
import secrets
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

import logos.main as _main
from logos.dbutils.dbmanager import DBManager
from logos.dbutils.dbrequest import (
    LogosNodeApplyLanesRequest,
    LogosNodeAuthRequest,
    LogosNodeDeleteLaneRequest,
    LogosNodeReconfigureLaneRequest,
    LogosNodeRegisterRequest,
    LogosNodeSleepLaneRequest,
    LogosNodeStatusRequest,
    LogosNodeWakeLaneRequest,
)
from logos.logosnode_registry import LogosNodeCommandError, LogosNodeOfflineError, LogosNodeSessionConflictError
from logos.logosnode_snapshot import (
    _LOGOSNODE_STATS_STALE_AFTER_SECONDS,
    _build_live_local_provider_sample,
    _parse_iso_datetime,
)
from logos.main import (
    _benchmark_sessions_by_job,
    _cancel_benchmark_job,
    _dispatch_logosnode_command,
    _find_uncalibrated_models_on_provider,
    _logosnode_registry,
    _normalize_provider_type,
    _resolve_provider_name,
)
from logos.role_auth import require_logos_admin_key

logger = logging.getLogger("LogosLogger")

router = APIRouter()


def _cancel_benchmarks_for_changed_session(provider_id: int, session_id: str | None) -> None:
    for job_id, (job_provider_id, expected_session_id) in list(_benchmark_sessions_by_job.items()):
        if job_provider_id == provider_id and expected_session_id != session_id:
            _cancel_benchmark_job(job_id, "Provider restarted or disconnected")


def _capture_logosnode_provider_snapshot(
    provider_id: int,
    runtime: Dict[str, Any],
) -> None:
    sample = _build_live_local_provider_sample(
        None,
        {
            "last_heartbeat": runtime.get("timestamp"),
            "runtime": runtime,
        },
    )
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
            runtime_payload=(sample.get("runtime_payload") if isinstance(sample.get("runtime_payload"), dict) else {}),
            scheduler_signals=(
                sample.get("scheduler_signals") if isinstance(sample.get("scheduler_signals"), dict) else {}
            ),
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
                    db.session.rollback()
                    logger.warning(
                        "Failed to upsert model profiles for provider %s, the "
                        "entire row update (base_residency_mb, loaded_vram_mb, "
                        "kv_budget_mb, measurement_count, last_measured_at) is "
                        "lost until this recovers",
                        _resolve_provider_name(provider_id),
                        exc_info=True,
                    )

    sample["snapshot_id"] = snapshot_id
    asyncio.create_task(_logosnode_registry.record_runtime_sample(provider_id, sample))


def _capture_calibration_probe_log(provider_id: int, event: Dict[str, Any]) -> None:
    """Persist a worker's ``calibration_probe_log`` event into the DB.

    Fired once per model per calibration attempt (see
    ``LogosBridgeClient._record_calibration_probe_log`` on the worker side).
    Keeps only the most recent row per (provider_id, model_name) via
    ``upsert_calibration_probe_log``'s ON CONFLICT — mirrors how
    ``upsert_model_profiles`` above keeps one row per (provider_id,
    model_name).
    """
    model_name = str(event.get("model") or "").strip()
    if not model_name:
        return
    recorded_at = _parse_iso_datetime(event.get("timestamp"))
    details_raw = event.get("details")
    payload = json.loads(details_raw) if isinstance(details_raw, str) and details_raw else {}
    if not isinstance(payload, dict):
        return
    # Pop out before it goes into `summary` below — otherwise the (large,
    # deliberately un-truncated) raw log text would be duplicated into both
    # the dedicated `log_text` column and the JSONB summary blob.
    log_text = payload.pop("log_text", None)

    with DBManager() as db:
        db.upsert_calibration_probe_log(provider_id, model_name, recorded_at, payload, log_text)


def _require_root_access(logos_key: str) -> None:
    with DBManager() as db:
        require_logos_admin_key(logos_key, db)


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
        raise HTTPException(
            status_code=400,
            detail="TLS is required for logosnode auth/session endpoints",
        )


def _build_logosnode_ws_url(request: Request, token: str) -> str:
    _require_tls_request(request)
    ws_scheme = "ws" if _logosnode_insecure_dev_mode_enabled() else "wss"
    host = request.headers.get("host", "")
    if not host:
        raise HTTPException(status_code=400, detail="Missing Host header for websocket URL generation")
    return f"{ws_scheme}://{host}/logosdb/providers/logosnode/session?token={token}"


def _is_tls_websocket(websocket: WebSocket) -> bool:
    if _logosnode_insecure_dev_mode_enabled():
        return True
    if websocket.url.scheme in {"wss", "https"}:
        return True
    forwarded = websocket.headers.get("x-forwarded-proto", "")
    forwarded_values = [item.strip().lower() for item in forwarded.split(",") if item.strip()]
    return "https" in forwarded_values or "wss" in forwarded_values


@router.post("/logosdb/providers/logosnode/register", tags=["logosnode"])
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


@router.post("/logosdb/providers/logosnode/auth", tags=["logosnode"])
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
                f"Worker '{conflicting_session.worker_id}' is already connected. " f"Stop the existing worker first."
            ),
        )
    token = await _logosnode_registry.issue_ticket(
        provider_id=provider_id,
        worker_id=worker_id,
        capabilities_models=data.capabilities_models,
        configured_models=data.configured_models or None,
        ttl_seconds=60,
    )
    return {
        "session_token": token,
        "ws_url": _build_logosnode_ws_url(request, token),
        "worker_id": worker_id,
        "expires_in_seconds": 60,
    }


@router.websocket("/logosdb/providers/logosnode/session")
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
        session = await _logosnode_registry.attach_session(ticket, websocket)
    except LogosNodeSessionConflictError as exc:
        await websocket.close(code=1008, reason=str(exc))
        return
    _cancel_benchmarks_for_changed_session(ticket.provider_id, session.session_id)

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
                    capabilities_models=(
                        payload.get("capabilities_models")
                        if isinstance(payload.get("capabilities_models"), list)
                        else None
                    ),
                    configured_models=(
                        payload.get("configured_models") if isinstance(payload.get("configured_models"), list) else None
                    ),
                    max_lanes=(
                        int(payload.get("max_lanes", 0)) if isinstance(payload.get("max_lanes"), (int, float)) else 0
                    ),
                    calibrating=(
                        bool(payload.get("calibrating")) if isinstance(payload.get("calibrating"), bool) else None
                    ),
                    actions=(payload.get("actions") if isinstance(payload.get("actions"), list) else None),
                )
            elif msg_type == "status":
                runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
                await _logosnode_registry.update_runtime(
                    provider_id=ticket.provider_id,
                    runtime=runtime,
                    capabilities_models=(
                        payload.get("capabilities_models")
                        if isinstance(payload.get("capabilities_models"), list)
                        else None
                    ),
                    configured_models=(
                        payload.get("configured_models") if isinstance(payload.get("configured_models"), list) else None
                    ),
                    calibrating=(
                        bool(payload.get("calibrating")) if isinstance(payload.get("calibrating"), bool) else None
                    ),
                )
                _capture_logosnode_provider_snapshot(ticket.provider_id, runtime)
            elif msg_type == "event":
                event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
                await _logosnode_registry.append_event(
                    provider_id=ticket.provider_id,
                    event=event,
                    replay=bool(payload.get("replay", False)),
                )
                if event.get("event") == "calibration_probe_log":
                    try:
                        await asyncio.to_thread(_capture_calibration_probe_log, ticket.provider_id, event)
                    except Exception:
                        logger.debug(
                            "Failed to persist calibration probe log for provider %s",
                            _resolve_provider_name(ticket.provider_id),
                            exc_info=True,
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
        current = _logosnode_registry.peek_runtime_snapshot(ticket.provider_id)
        _cancel_benchmarks_for_changed_session(
            ticket.provider_id,
            str(current["session_id"]) if current else None,
        )


@router.post("/logosdb/providers/logosnode/status", tags=["logosnode"])
async def logosnode_status(data: LogosNodeStatusRequest):
    _require_root_access(data.logos_key)
    try:
        return await _logosnode_registry.get_runtime_snapshot(data.provider_id)
    except LogosNodeOfflineError as exc:
        return JSONResponse(status_code=503, content={"error": str(exc)})


@router.post("/logosdb/providers/logosnode/devices", tags=["logosnode"])
async def logosnode_devices(data: LogosNodeStatusRequest):
    _require_root_access(data.logos_key)
    try:
        return {"devices": await _logosnode_registry.get_devices(data.provider_id)}
    except LogosNodeOfflineError as exc:
        return JSONResponse(status_code=503, content={"error": str(exc)})


@router.post("/logosdb/providers/logosnode/lanes", tags=["logosnode"])
async def logosnode_lanes(data: LogosNodeStatusRequest):
    _require_root_access(data.logos_key)
    try:
        return {"lanes": await _logosnode_registry.get_lanes(data.provider_id)}
    except LogosNodeOfflineError as exc:
        return JSONResponse(status_code=503, content={"error": str(exc)})


@router.post("/logosdb/providers/logosnode/lanes/apply", tags=["logosnode"])
async def logosnode_apply_lanes(data: LogosNodeApplyLanesRequest):
    _require_root_access(data.logos_key)
    return await _dispatch_logosnode_command(
        provider_id=data.provider_id,
        action="apply_lanes",
        params={"lanes": data.lanes},
    )


@router.post("/logosdb/providers/logosnode/lanes/sleep", tags=["logosnode"])
async def logosnode_sleep_lane(data: LogosNodeSleepLaneRequest):
    _require_root_access(data.logos_key)
    return await _dispatch_logosnode_command(
        provider_id=data.provider_id,
        action="sleep_lane",
        params={"lane_id": data.lane_id, "level": data.level, "mode": data.mode},
    )


@router.post("/logosdb/providers/logosnode/lanes/wake", tags=["logosnode"])
async def logosnode_wake_lane(data: LogosNodeWakeLaneRequest):
    _require_root_access(data.logos_key)
    return await _dispatch_logosnode_command(
        provider_id=data.provider_id,
        action="wake_lane",
        params={"lane_id": data.lane_id},
    )


@router.post("/logosdb/providers/logosnode/lanes/delete", tags=["logosnode"])
async def logosnode_delete_lane(data: LogosNodeDeleteLaneRequest):
    _require_root_access(data.logos_key)
    return await _dispatch_logosnode_command(
        provider_id=data.provider_id,
        action="delete_lane",
        params={"lane_id": data.lane_id},
    )


@router.post("/logosdb/providers/logosnode/lanes/reconfigure", tags=["logosnode"])
async def logosnode_reconfigure_lane(data: LogosNodeReconfigureLaneRequest):
    _require_root_access(data.logos_key)
    return await _dispatch_logosnode_command(
        provider_id=data.provider_id,
        action="reconfigure_lane",
        params={"lane_id": data.lane_id, "updates": data.updates},
    )


@router.post("/logosdb/providers/logosnode/calibrate_uncalibrated", tags=["logosnode"])
async def logosnode_calibrate_uncalibrated(data: LogosNodeStatusRequest):
    """Kick off a worker-driven calibration session immediately.

    The worker picks which uncalibrated models to run and walks them one at
    a time, emitting ``calibration_*`` events as each completes. The server
    no longer chooses models or polls status — the response just confirms
    the session was started and reports which models the worker will see
    as uncalibrated right now.
    """
    _require_root_access(data.logos_key)
    snap = _logosnode_registry.peek_runtime_snapshot(data.provider_id)
    if snap is None:
        return JSONResponse(status_code=503, content={"error": "Worker not connected"})
    if not snap.get("first_status_received"):
        return JSONResponse(
            status_code=503,
            content={"error": "Worker has not sent its first status yet"},
        )
    models = _find_uncalibrated_models_on_provider(data.provider_id)
    if not models:
        return {
            "message": "No uncalibrated models on this worker",
            "count": 0,
            "models": [],
        }
    sleep_level = (
        _main._calibration_orchestrator._config.sleep_level if _main._calibration_orchestrator is not None else 1
    )
    pname = _resolve_provider_name(data.provider_id)
    try:
        await _logosnode_registry.send_command(
            data.provider_id,
            "start_calibration_session",
            params={"sleep_level": sleep_level},
            timeout_seconds=30,
        )
    except LogosNodeOfflineError as exc:
        logger.warning("Admin calibrate-uncalibrated: provider=%s offline: %s", pname, exc)
        return JSONResponse(status_code=503, content={"error": "Worker not connected"})
    except LogosNodeCommandError as exc:
        logger.warning(
            "Admin calibrate-uncalibrated: start_calibration_session refused on provider=%s: %s",
            pname,
            exc,
        )
        return JSONResponse(status_code=409, content={"error": str(exc)})
    logger.info(
        "Admin calibrate-uncalibrated: session started on provider=%s (%d candidate model(s))",
        pname,
        len(models),
    )
    return {
        "message": f"Calibration session started on {pname} ({len(models)} candidate model(s))",
        "count": len(models),
        "models": models,
    }
