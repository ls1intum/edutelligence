"""Secret-gated /internal/* endpoints, called by the Spring webservice."""

import asyncio
import datetime
import hmac
import json
import logging
import secrets
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse

import logos.main as _main
from logos.auth import AuthContext
from logos.benchmarks.guidellm_runner import BENCHMARK_JOB_HEADER
from logos.benchmarks.guidellm_runner import DATASET as BENCHMARK_DATASET
from logos.benchmarks.guidellm_runner import (
    benchmark_affinity_headers,
    credential_transport_is_secure,
    extract_serving_configuration,
    internal_benchmark_target,
    resolve_benchmark_target,
    run_benchmark_job,
)
from logos.dbutils.dbmanager import DBManager
from logos.dbutils.dbrequest import (
    InternalAddLaneRequest,
    InternalBenchmarkRequest,
    InternalCalibrateRequest,
    InternalDeleteLaneRequest,
    InternalLaneLoadStatusRequest,
    InternalSleepLaneRequest,
    InternalWakeLaneRequest,
    RefreshPipelineRequest,
)
from logos.dbutils.types import Deployment
from logos.logosnode_registry import LogosNodeCommandError, LogosNodeOfflineError
from logos.logosnode_snapshot import _logosnode_snapshot_is_connected
from logos.main import (
    _INTERNAL_SECRET,
    _background_tasks,
    _benchmark_admission_lock,
    _benchmark_provider_affinity,
    _benchmark_sessions_by_job,
    _benchmark_tasks,
    _benchmark_tasks_by_job,
    _cancel_benchmark_job,
    _dispatch_logosnode_command,
    _execute_cancelling_on_disconnect,
    _filter_logosnode_deployments,
    _find_uncalibrated_models_on_provider,
    _forget_benchmark_task,
    _live_streams,
    _normalize_provider_type,
    _resolve_provider_name,
    _served_context_window_stats,
    refresh_pipeline_runtime_state,
)

logger = logging.getLogger("LogosLogger")

router = APIRouter()

_HEALTH_STATUS_RANK: Dict[str, int] = {"DOWN": 0, "DEGRADED": 1, "UP": 2}


def _model_deployment_status(
    deployment: Dict[str, Any], provider_id: int, worker_ids: set[int], snapshots: Dict[int, Dict[str, Any]]
) -> str:
    """Serveability of one model deployment for the per-model health breakdown.

    Deployments outside the local provider inventory are cloud — UP whenever
    configured, because Logos does not probe cloud providers (matching the
    overall /health behaviour). Worker-backed
    deployments are UP when the worker is online, the model is calibrated, and
    a lane is loaded/running or sleeping (a wake is fast). A model that only
    needs a cold load, or that lives on a worker reporting an unhealthy node,
    is DEGRADED; a missing/stale worker or missing calibration is DOWN.
    """
    if provider_id not in worker_ids:
        return "UP"
    snapshot = snapshots.get(provider_id)
    if snapshot is None:
        return "DOWN"
    model_name = str(deployment.get("model_name") or "")
    if model_name not in (snapshot.get("capabilities_models") or []):
        return "DOWN"
    runtime = snapshot.get("runtime") if isinstance(snapshot.get("runtime"), dict) else {}
    node_health = runtime.get("node_health")
    if isinstance(node_health, dict) and node_health.get("healthy") is False:
        return "DEGRADED"
    states = {
        str(lane.get("runtime_state") or "").strip()
        for lane in (runtime.get("lanes") or [])
        if isinstance(lane, dict) and str(lane.get("model") or "").strip() == model_name
    }
    if states & {"loaded", "running", "sleeping"}:
        return "UP"
    # No loaded/running/sleeping lane: a full cold load is needed first.
    return "DEGRADED"


@router.get("/internal/model_health", tags=["admin"])
async def internal_model_health(request: Request):
    """Current per-model health, for the Spring webservice.

    Lane state, worker connection state, and node health exist only in the
    orchestrator's worker registry, so the webservice's get_model_health
    endpoint (API-key authenticated, permission filtered) is served from this
    payload. It is secret-gated rather than part of /health because /health is
    public: the full model catalogue must not be readable without a credential.

    Status codes mirror /health — 503 while every local worker is down, whose
    body still carries the breakdown (cloud models may be serveable) — and the
    entries expose only model names and statuses, best across deployments
    (see :func:`_model_deployment_status`).
    """
    _require_internal_secret(request, disabled_detail="Internal model health endpoint disabled")

    local_ok = False
    model_status: Dict[str, str] = {}
    try:
        with DBManager() as db:
            inventory = db.list_local_providers()
            deployments = db.get_all_deployments_with_names()
        worker_ids: set[int] = set()
        snapshots: Dict[int, Dict[str, Any]] = {}
        for provider in inventory:
            provider_id = int(provider.get("provider_id") or 0)
            if provider_id <= 0:
                continue
            worker_ids.add(provider_id)
            snapshot = _main._logosnode_registry.peek_runtime_snapshot(provider_id)
            if not _logosnode_snapshot_is_connected(snapshot):
                continue
            snapshots[provider_id] = snapshot
            if snapshot.get("capabilities_models"):
                local_ok = True
        for deployment in deployments:
            model_name = str(deployment.get("model_name") or "").strip()
            if not model_name:
                continue
            status = _model_deployment_status(
                deployment, int(deployment.get("provider_id") or 0), worker_ids, snapshots
            )
            current = model_status.get(model_name)
            if current is None or _HEALTH_STATUS_RANK[status] > _HEALTH_STATUS_RANK[current]:
                model_status[model_name] = status
    except Exception:
        logger.exception("Model health check failed to evaluate provider state")
        local_ok = False
        model_status = {}

    return JSONResponse(
        status_code=200 if local_ok else 503,
        content={"models": [{"name": name, "status": model_status[name]} for name in sorted(model_status)]},
    )


@router.post("/internal/refresh_pipeline", tags=["admin"])
async def internal_refresh_pipeline(data: RefreshPipelineRequest, request: Request):
    _require_internal_secret(request, disabled_detail="Internal refresh endpoint disabled")
    if not _main._pipeline or not _main._logosnode_facade or not _main._azure_facade:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")
    logger.info(
        "Pipeline refresh requested by Spring (rebuildClassifier=%s, syncCloudModels=%s)",
        data.rebuild_classifier,
        data.sync_cloud_models,
    )
    await refresh_pipeline_runtime_state(rebuild_model_classifier=data.rebuild_classifier)
    if data.sync_cloud_models and _main._cloud_model_sync is not None:
        # Scheduled, not awaited: the pass contacts every cloud upstream in
        # turn and the webservice is blocked on this response, so one
        # unreachable provider would stall a provider edit for a full request
        # timeout. The pass refreshes runtime state itself once it finds
        # something, so nothing is lost by returning first.
        _main._cloud_model_sync.request_refresh()
    return {"status": "ok"}


@router.get("/internal/provider_status", tags=["admin"])
async def internal_provider_status(request: Request):
    """Connection state of every local provider, for the Spring webservice.

    The webservice serves the statistics VRAM payload from persisted snapshots
    only; live connection state (online/offline) exists solely in the
    orchestrator's worker registry, so it is exposed here for enrichment.
    """
    _require_internal_secret(request, disabled_detail="Internal provider status endpoint disabled")

    with DBManager() as db:
        inventory = db.list_local_providers()

    providers = []
    for provider in inventory:
        provider_id = int(provider.get("provider_id") or 0)
        if provider_id <= 0:
            continue
        runtime_snapshot = _main._logosnode_registry.peek_runtime_snapshot(provider_id)
        connected = _logosnode_snapshot_is_connected(runtime_snapshot)
        last_heartbeat = runtime_snapshot.get("last_heartbeat") if runtime_snapshot else None
        if isinstance(last_heartbeat, datetime.datetime):
            last_heartbeat = last_heartbeat.isoformat()
        providers.append(
            {
                "provider_id": provider_id,
                "name": provider.get("name"),
                "provider_type": provider.get("provider_type"),
                "connected": connected,
                "connection_state": "online" if connected else "offline",
                "last_heartbeat": last_heartbeat if isinstance(last_heartbeat, str) else None,
                "calibrating": _main._logosnode_registry.is_calibrating(provider_id),
            }
        )
    return {"providers": providers}


@router.get("/internal/model_context_windows", tags=["admin"])
async def internal_model_context_windows(request: Request):
    """Served context window per model name, for the Spring webservice.

    The effective window lives only in the worker runtime snapshots held by
    the orchestrator's registry; the webservice enriches its model listings
    (e.g. the AI-tools setup page) from this map.

    ``windows`` keeps its original shape — model name -> smallest currently
    served window — so an older webservice keeps working. ``stats`` adds the
    ``best`` and ``native`` numbers next to it; see
    :func:`_served_context_window_stats`.
    """
    _require_internal_secret(request)

    stats = _served_context_window_stats()
    return {
        "windows": {model: entry["current_min"] for model, entry in stats.items() if "current_min" in entry},
        "stats": stats,
    }


def _require_internal_secret(request: Request, disabled_detail: str = "Internal endpoint disabled") -> None:
    """Authenticate an /internal/* call: the shared secret, no user context.

    Endpoints that historically reported their own name in the 403 (secret
    not configured) pass it through ``disabled_detail`` so the client-visible
    answer is unchanged.
    """
    if not _INTERNAL_SECRET:
        raise HTTPException(status_code=403, detail=disabled_detail)
    auth_header = request.headers.get("authorization", "")
    token = (
        auth_header.removeprefix("Bearer ").strip()
        if auth_header.lower().startswith("bearer ")
        else auth_header.strip()
    )
    if not hmac.compare_digest(token.encode("utf-8"), _INTERNAL_SECRET.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid or missing internal secret")


@router.get("/internal/live_streams", tags=["admin"])
async def internal_live_streams(request: Request):
    """Token counts of the requests streaming right now, for the statistics page.

    A finished request's usage is in the database; one still running is only
    here, in the process the chunks pass through. Without this the request feed
    shows a row with no numbers for the whole minute a long generation takes,
    and then the totals appear at once when it ends.

    Cheap by construction: a dict of the in-flight requests, no database work,
    and the webservice already polls on the cadence it pushes the feed at.
    """
    _require_internal_secret(request)
    return {"streams": _live_streams.snapshot()}


# How often the live-stream SSE connection checks for a changed snapshot. The
# push is event-driven in effect — a token delta bumps the registry's version
# and the very next check sends it — but the check itself is a short poll so
# the endpoint stays a plain generator instead of event plumbing.
_LIVE_STREAMS_SSE_TICK_S = 0.2


@router.get("/internal/live_streams/stream", tags=["admin"])
async def internal_live_streams_stream(request: Request):
    """The live view as an SSE stream: the current snapshot, then one event
    per change.

    The statistics page's token counts used to move at the webservice's poll
    interval; this lets the webservice forward a change the moment it happens
    and push it to its websocket clients in real time. The payload is the
    same shape as ``/internal/live_streams`` so both clients parse one way.
    """
    _require_internal_secret(request)

    async def events():
        version = -1
        while True:
            current = _live_streams.version
            if current != version:
                version = current
                yield f"data: {json.dumps({'streams': _live_streams.snapshot()})}\n\n"
            else:
                # A comment line: keeps idle (but healthy) connections from
                # being reaped by anything in the middle.
                yield ": ping\n\n"
            await asyncio.sleep(_LIVE_STREAMS_SSE_TICK_S)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/internal/calibration_probe_logs", tags=["admin"])
def internal_calibration_probe_logs(model_name: str, request: Request):
    """Every node's most recent calibration probe log for one model.

    Backs the webservice's model-error-report page (Complete Logs tab) —
    it resolves a model id to a model name, then asks here for what every
    provider that has calibrated it reported.
    """
    _require_internal_secret(request)

    with DBManager() as db:
        rows = db.get_calibration_probe_logs_by_model(model_name)
    return JSONResponse(status_code=200, content=jsonable_encoder({"logs": rows}))


@router.get("/internal/calibration_probe_logs/fetch", tags=["admin"])
async def internal_fetch_calibration_log(provider_id: int, model_name: str, request: Request):
    """On-demand fetch of a model's full calibration log from the worker.

    Backs the Download-full-logs button: successful runs skip storing
    log_text, so this re-reads the on-disk log live. Pure file read, no
    GPU impact; needs the worker online and not yet recalibrated since.
    """
    _require_internal_secret(request)

    try:
        result = await _main._logosnode_registry.send_command(
            provider_id,
            "get_calibration_log",
            params={"model_name": model_name},
            timeout_seconds=20,
        )
    except LogosNodeOfflineError as exc:
        return JSONResponse(status_code=503, content={"error": str(exc) or "Worker not connected"})
    except LogosNodeCommandError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})

    return JSONResponse(status_code=200, content=jsonable_encoder({"log_text": result.get("log_text", "")}))


@router.get("/internal/compatibility_precheck", tags=["admin"])
async def internal_compatibility_precheck(model_name: str, request: Request, provider_id: int | None = None):
    """On-demand HF compatibility check for one model, across one or all
    connected logosnode workers.

    Unlike calibration itself, this is safe to call any time — including
    during the day, with live traffic on the nodes — because the worker-side
    check (run_compatibility_precheck) never touches vLLM or lanes: it's
    only an HF metadata fetch plus a read-only nvidia-smi query. Omitting
    provider_id fans out across every connected worker, answering "would
    this model run on ANY node" rather than requiring the caller to already
    know which one to ask.
    """
    _require_internal_secret(request)

    provider_ids = [provider_id] if provider_id is not None else _main._logosnode_registry.active_provider_ids()
    if not provider_ids:
        return JSONResponse(status_code=200, content={"model": model_name, "results": []})

    async def _check_one(pid: int) -> dict[str, Any]:
        pname = _resolve_provider_name(pid)
        try:
            result = await _main._logosnode_registry.send_command(
                pid, "run_compatibility_precheck", params={"model": model_name}, timeout_seconds=30
            )
            # A worker reply with "result": null bypasses send_command's
            # dict type hint (a present null isn't its .get() default) and
            # would otherwise raise **result below, outside this try —
            # taking every other provider's result down with it.
            if not isinstance(result, dict):
                return {
                    "provider_id": pid,
                    "provider_name": pname,
                    "ok": False,
                    "error": f"Worker returned an unexpected response type: {type(result).__name__}",
                }
            return {"provider_id": pid, "provider_name": pname, **result}
        except LogosNodeOfflineError:
            return {"provider_id": pid, "provider_name": pname, "ok": False, "error": "Worker not connected"}
        except LogosNodeCommandError as exc:
            return {"provider_id": pid, "provider_name": pname, "ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            # An unexpected failure for one provider must not lose the
            # results already gathered for every other one — see below.
            logger.exception("[Precheck] unexpected failure checking provider %s for %s", pid, model_name)
            return {"provider_id": pid, "provider_name": pname, "ok": False, "error": f"Unexpected error: {exc}"}

    results = await asyncio.gather(*(_check_one(pid) for pid in provider_ids))
    return JSONResponse(status_code=200, content=jsonable_encoder({"model": model_name, "results": list(results)}))


@router.post("/internal/model_benchmarks/run", tags=["admin"])
async def internal_run_model_benchmark(data: InternalBenchmarkRequest, request: Request):
    """Queue a fixed GSM8K GuideLLM run for one exact provider-model pair."""
    _require_internal_secret(request)

    # One orchestrator process owns benchmark execution. Serialize the short
    # check-and-create section in memory so simultaneous starts cannot both
    # admit a benchmark for the same provider.
    with _benchmark_admission_lock, DBManager() as db:
        target = db.get_model_provider_benchmark_target(data.model_provider_id)
        if target is None:
            raise HTTPException(status_code=404, detail="Provider-model pair not found")
        provider_id = int(target["provider_id"])
        provider_type = _normalize_provider_type(str(target.get("provider_type") or ""))
        endpoint = str(target.get("target") or "").strip()
        if provider_type != "logosnode" and not endpoint.startswith(("http://", "https://")):
            raise HTTPException(status_code=409, detail="Provider-model pair has no valid endpoint")
        api_key = str(target.get("api_key") or "").strip()
        if provider_type != "logosnode" and api_key and not credential_transport_is_secure(endpoint):
            raise HTTPException(
                status_code=409,
                detail="Provider credentials require HTTPS (plain HTTP is allowed only on loopback)",
            )

        active = db.find_active_model_benchmark_job(provider_id)
        if active is not None:
            return JSONResponse(
                status_code=409,
                content=jsonable_encoder(
                    {
                        "error": f"A benchmark is already running on {target['provider_name']}",
                        "job_id": active["id"],
                        "status": active["status"],
                    }
                ),
            )
        runtime_snapshot = _main._logosnode_registry.peek_runtime_snapshot(provider_id)
        if provider_type == "logosnode":
            if runtime_snapshot is None or not _logosnode_snapshot_is_connected(runtime_snapshot):
                raise HTTPException(status_code=503, detail=f"Provider {target['provider_name']} is offline")
            if not runtime_snapshot.get("first_status_received"):
                raise HTTPException(status_code=503, detail="Provider has not sent its first status yet")

        model_name = str(target["model_name"])
        serving_configuration = extract_serving_configuration(runtime_snapshot, model_name)
        job_payload = {
            "model_provider_id": data.model_provider_id,
            "provider_id": provider_id,
            "provider_name": target["provider_name"],
            "model_id": target["model_id"],
            "model_name": model_name,
            "dataset": BENCHMARK_DATASET,
            "subset": "main",
            "split": "test",
            "samples": data.samples,
            "max_output_tokens": data.max_output_tokens,
            "provider_session_id": runtime_snapshot.get("session_id") if runtime_snapshot else None,
        }
        job_id = db.create_job_record(
            payload=job_payload,
            api_key_id=None,
            team_id=None,
            user_id=None,
            environment="model-provider-benchmark",
        )

    is_internal_worker_benchmark = provider_type == "logosnode"
    benchmark_target = (
        internal_benchmark_target(job_id) if is_internal_worker_benchmark else resolve_benchmark_target(endpoint)
    )
    request_headers = (
        benchmark_affinity_headers(
            secret=_INTERNAL_SECRET,
            job_id=job_id,
            provider_id=provider_id,
            model=model_name,
        )
        if is_internal_worker_benchmark
        else None
    )
    worker_preparer = (
        (lambda: _main._capacity_planner.prepare_benchmark_lane(provider_id, model_name))
        if request_headers is not None and _main._capacity_planner is not None
        else None
    )

    task = asyncio.create_task(
        run_benchmark_job(
            job_id=job_id,
            model_provider_id=data.model_provider_id,
            target=benchmark_target,
            model=model_name,
            api_key=None if is_internal_worker_benchmark else api_key or None,
            samples=data.samples,
            max_output_tokens=data.max_output_tokens,
            serving_configuration=serving_configuration,
            serving_configuration_getter=lambda: extract_serving_configuration(
                _main._logosnode_registry.peek_runtime_snapshot(provider_id), model_name
            ),
            request_headers=request_headers,
            worker_preparer=worker_preparer,
            worker_session_is_current=(
                (
                    lambda: (_main._logosnode_registry.peek_runtime_snapshot(provider_id) or {}).get("session_id")
                    == job_payload["provider_session_id"]
                )
                if is_internal_worker_benchmark
                else None
            ),
        )
    )
    _background_tasks.add(task)
    _benchmark_tasks.add(task)
    _benchmark_tasks_by_job[job_id] = task
    if is_internal_worker_benchmark:
        _benchmark_sessions_by_job[job_id] = (provider_id, str(job_payload["provider_session_id"]))
    task.add_done_callback(lambda done, jid=job_id: _forget_benchmark_task(jid, done))
    return JSONResponse(
        status_code=202,
        content={
            "job_id": job_id,
            "status": "pending",
            "provider_id": provider_id,
            "provider_name": target["provider_name"],
            "model_provider_id": data.model_provider_id,
            "model_name": model_name,
        },
    )


@router.post("/internal/model_benchmarks/jobs/{job_id}/cancel", tags=["admin"])
async def internal_cancel_model_benchmark(job_id: int, request: Request):
    """Cancel one active benchmark and release its lease."""
    _require_internal_secret(request)
    if not _cancel_benchmark_job(job_id, "Benchmark cancelled by administrator"):
        raise HTTPException(status_code=404, detail="Active benchmark job not found")
    return {"job_id": job_id, "status": "failed"}


@router.post("/internal/model_benchmarks/jobs/{job_id}/v1/{path:path}", tags=["admin"])
async def internal_model_benchmark_completion(job_id: int, path: str, request: Request):
    """Execute one signed benchmark request without a user API key."""
    if path.strip("/") != "chat/completions":
        raise HTTPException(status_code=404, detail="Unsupported benchmark operation")

    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON payload must be an object")

    headers = dict(request.headers)
    header_job_id = headers.get(BENCHMARK_JOB_HEADER)
    if header_job_id != str(job_id):
        raise HTTPException(status_code=401, detail="Invalid benchmark worker affinity")

    with DBManager() as db:
        job = db.get_job(job_id)
        payload = job.get("request_payload") if job else None
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=401, detail="Invalid benchmark worker affinity") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=401, detail="Invalid benchmark worker affinity")
        try:
            model_provider_id = int(payload["model_provider_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=401, detail="Invalid benchmark worker affinity") from exc
        target = db.get_model_provider_benchmark_target(model_provider_id)

    if target is None or _normalize_provider_type(str(target.get("provider_type") or "")) != "logosnode":
        raise HTTPException(status_code=404, detail="Benchmark worker deployment no longer exists")

    raw_deployments: list[Deployment] = [
        {
            "model_id": int(target["model_id"]),
            "provider_id": int(target["provider_id"]),
            "type": "logosnode",
            "privacy_level": target.get("privacy_level"),
            "cloud_provider_type": target.get("cloud_provider_type"),
            "base_url": target.get("base_url"),
        }
    ]
    required_provider_id = _benchmark_provider_affinity(headers, body, raw_deployments)
    deployments = await _filter_logosnode_deployments(raw_deployments, payload=body)
    if not deployments:
        raise HTTPException(status_code=503, detail="Selected benchmark worker is not serving the model")

    # This context is created only after the active job's HMAC and exact
    # provider-model pair have been validated above. It intentionally has no
    # user/team limits or billing identity: benchmarks are Logos-internal work.
    auth = AuthContext(
        key_value="",
        api_key_id=-job_id,
        api_key_name="internal-model-benchmark",
        key_type="internal",
        team_id=None,
        user_id=None,
        environment="model-provider-benchmark",
        log_level="FULL",
        settings={},
        default_priority=1,
    )
    request_id = secrets.token_urlsafe(16)
    with DBManager() as db:
        log_result, _ = db.log_usage(
            api_key_id=None,
            team_id=None,
            user_id=None,
            environment=auth.environment,
            log_level=auth.log_level,
            request_id=request_id,
        )
    log_id = int(log_result["log-id"])
    return await _execute_cancelling_on_disconnect(
        request,
        deployments=deployments,
        body=body,
        headers=headers,
        auth=auth,
        path=f"v1/{path.strip('/')}",
        log_id=log_id,
        request_id=request_id,
        required_provider_id=required_provider_id,
    )


@router.post("/internal/logosnode/calibrate_uncalibrated", tags=["admin"])
async def internal_logosnode_calibrate_uncalibrated(data: InternalCalibrateRequest, request: Request):
    """Calibrate uncalibrated models on a worker, called by Spring after JWT validation."""
    _require_internal_secret(request)
    snap = _main._logosnode_registry.peek_runtime_snapshot(data.provider_id)
    if snap is None:
        return JSONResponse(status_code=503, content={"error": "Worker not connected"})
    if not snap.get("first_status_received"):
        return JSONResponse(
            status_code=503,
            content={"error": "Worker has not sent its first status yet"},
        )
    models = _find_uncalibrated_models_on_provider(data.provider_id)
    if not models:
        return {"message": "No uncalibrated models on this worker", "count": 0, "models": []}
    sleep_level = (
        _main._calibration_orchestrator._config.sleep_level if _main._calibration_orchestrator is not None else 1
    )
    pname = _resolve_provider_name(data.provider_id)
    try:
        await _main._logosnode_registry.send_command(
            data.provider_id,
            "start_calibration_session",
            params={"sleep_level": sleep_level},
            timeout_seconds=30,
        )
    except LogosNodeOfflineError as exc:
        logger.warning("Internal calibrate-uncalibrated: provider=%s offline: %s", pname, exc)
        return JSONResponse(status_code=503, content={"error": "Worker not connected"})
    except LogosNodeCommandError as exc:
        logger.warning(
            "Internal calibrate-uncalibrated: start_calibration_session refused on provider=%s: %s", pname, exc
        )
        return JSONResponse(status_code=409, content={"error": str(exc)})
    logger.info(
        "Internal calibrate-uncalibrated: session started on provider=%s (%d candidate model(s))", pname, len(models)
    )
    return {
        "message": f"Calibration session started on {pname} ({len(models)} candidate model(s))",
        "count": len(models),
        "models": models,
    }


@router.post("/internal/logosnode/lanes/delete", tags=["admin"])
async def internal_logosnode_delete_lane(data: InternalDeleteLaneRequest, request: Request):
    """Unload a lane on a worker, called by Spring after JWT validation."""
    _require_internal_secret(request)
    return await _dispatch_logosnode_command(
        provider_id=data.provider_id,
        action="delete_lane",
        params={"lane_id": data.lane_id},
    )


@router.post("/internal/logosnode/lanes/add", tags=["admin"])
async def internal_logosnode_add_lane(data: InternalAddLaneRequest, request: Request):
    """Manually load a single lane on a worker, called by Spring after JWT validation."""
    _require_internal_secret(request)

    model = str(data.lane.get("model") or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="lane.model is required")

    if _main._capacity_planner is None:
        raise HTTPException(status_code=503, detail="Capacity planner not ready")

    # Answer a refusal synchronously — a background task has nobody to report to.
    rejection = _main._capacity_planner.manual_load_rejection_reason(data.provider_id, model)
    if rejection is not None:
        raise HTTPException(status_code=409, detail=rejection)

    # Admit before answering 202: the check-and-claim is atomic on the event
    # loop, so a second click for the same model — or a load the planner is
    # already bringing up — meets the marker now and gets a 409 the operator
    # reads, instead of a 202 whose background task no-ops later and whose
    # outcome the operator's poll would have to wait on. A refused click must
    # not touch the recorded outcome either: it would reset a previous
    # attempt's terminal state with no task left to settle it.
    admission_rejection = _main._capacity_planner.manual_load_admission_rejection(data.provider_id, model)
    if admission_rejection is not None:
        raise HTTPException(status_code=409, detail=admission_rejection)

    # Record "running" BEFORE answering, not only once the background task
    # gets to it: the UI starts polling load_status as soon as it sees the 202,
    # and a gap between the two would let it read the previous attempt's
    # "failed" entry and show a stale failure for the fresh click.
    _main._capacity_planner.record_manual_load_outcome(data.provider_id, model, "running")

    # Loading a model takes minutes (the planner budgets 1800 s for the command),
    # far beyond any caller's HTTP read timeout, and holding a servlet thread
    # open that long per load is its own problem. So kick it off and return: the
    # lane appears in the lane-status stream the statistics page already
    # subscribes to, which is where the operator watches it come up.
    task = asyncio.create_task(_main._capacity_planner.load_lane_manually(data.provider_id, model))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    # 202, not 200: the lane is not loaded when this returns, only scheduled.
    return JSONResponse(
        status_code=202,
        content={"status": "accepted", "model": model, "provider_id": data.provider_id},
    )


@router.post("/internal/logosnode/lanes/load_status", tags=["admin"])
async def internal_logosnode_lane_load_status(data: InternalLaneLoadStatusRequest, request: Request):
    """Outcome of the most recent manual load of a model, for the statistics UI.

    The "Load lane" endpoint answers 202 and runs the load in the background,
    where a refusal (no VRAM, worker rejection, ...) is currently only a log
    line. The UI polls this endpoint while its "Loading …" note is up and
    turns the note into the recorded error once the attempt is over.

    ``status`` is ``"running" | "succeeded" | "failed" | "unknown"`` — unknown
    means no manual load of this model is known to the planner (never clicked
    here, the entry expired, or the orchestrator restarted in between), which
    the UI must not render as a failure.
    """
    _require_internal_secret(request)

    model = str(data.model or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="model is required")
    if _main._capacity_planner is None:
        raise HTTPException(status_code=503, detail="Capacity planner not ready")

    # One shape for every answer — unknown included, with nulls — so the UI
    # can read the fields without checking the status first.
    outcome = _main._capacity_planner.get_manual_load_outcome(data.provider_id, model) or {}
    return {
        "status": outcome.get("status", "unknown"),
        "model": model,
        "provider_id": data.provider_id,
        "lane_id": outcome.get("lane_id"),
        "reason": outcome.get("reason"),
        "updated_at": outcome.get("updated_at"),
    }


@router.post("/internal/logosnode/lanes/sleep", tags=["admin"])
async def internal_logosnode_sleep_lane(data: InternalSleepLaneRequest, request: Request):
    """Sleep a lane on a worker, called by Spring after JWT validation.

    Level 1 keeps the weights resident in host memory, so the lane wakes in
    seconds; level 2 would release them and pay for a full reload on the next
    wake — a choice most operators cannot make well, so the button does not
    offer it and neither does this endpoint.

    In-flight requests are not refused: mode="wait" makes the worker drain
    them first and only sleep once the lane is idle (a request admitted
    between drain and sleep makes the worker skip the sleep and stay awake).
    The command therefore takes as long as the drain — the dispatch budget
    must cover it, which is why sleep_lane gets the same 120 s as the
    planner's own sleep commands.
    """
    _require_internal_secret(request)

    snap = _main._logosnode_registry.peek_runtime_snapshot(data.provider_id)
    if snap is None:
        return JSONResponse(status_code=503, content={"error": "Worker not connected"})
    if not snap.get("first_status_received"):
        return JSONResponse(
            status_code=503,
            content={"error": "Worker has not sent its first status yet"},
        )
    lanes = (snap.get("runtime") or {}).get("lanes") or []
    lane = next(
        (item for item in lanes if isinstance(item, dict) and str(item.get("lane_id", "")) == data.lane_id),
        None,
    )
    if lane is None:
        return JSONResponse(status_code=404, content={"error": f"Lane '{data.lane_id}' not found on this worker"})
    # "unsupported" is the worker's resolved answer for "cannot sleep this
    # lane": enable_sleep_mode off for its model (per-model override or the
    # node-wide kill switch) or a non-vLLM lane. Dispatching would burn the
    # command budget to fail on the worker, so refuse synchronously with the
    # reason the panel can display.
    if str(lane.get("sleep_state", "")).strip().lower() == "unsupported":
        raise HTTPException(
            status_code=409,
            detail="Lane does not support sleep mode; its model is configured without enable_sleep_mode.",
        )
    return await _dispatch_logosnode_command(
        provider_id=data.provider_id,
        action="sleep_lane",
        params={"lane_id": data.lane_id, "level": 1, "mode": "wait"},
    )


@router.post("/internal/logosnode/lanes/wake", tags=["admin"])
async def internal_logosnode_wake_lane(data: InternalWakeLaneRequest, request: Request):
    """Wake a sleeping lane on a worker, called by Spring after JWT validation."""
    _require_internal_secret(request)
    return await _dispatch_logosnode_command(
        provider_id=data.provider_id,
        action="wake_lane",
        params={"lane_id": data.lane_id},
    )
