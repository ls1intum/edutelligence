"""Admin endpoints under /logosdb and /forward_host."""

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import logos.main as _main
from logos.auth import authenticate_api_key
from logos.dbutils.dbmanager import DBManager
from logos.dbutils.dbrequest import ConnectModelProviderRequest, UpdateProviderSdiConfigRequest
from logos.main import _build_live_local_provider_vram_payload, refresh_pipeline_runtime_state

router = APIRouter()


@router.post("/logosdb/update_provider_sdi_config", tags=["admin"])
async def update_provider_sdi_config(data: UpdateProviderSdiConfigRequest):
    with DBManager() as db:
        result = db.update_provider_sdi_config(**data.dict())
    await refresh_pipeline_runtime_state()
    return result


@router.post("/logosdb/connect_model_provider", tags=["admin"])
async def connect_model_provider(data: ConnectModelProviderRequest):
    with DBManager() as db:
        result = db.connect_model_provider(**data.dict())
    await refresh_pipeline_runtime_state()
    return result


@router.get("/logosdb/scheduler_state", tags=["admin"])
async def scheduler_state(request: Request):
    """
    Debug endpoint to inspect in-memory scheduler and LogosWorkerNode capacity state.
    """
    headers = dict(request.headers)
    authenticate_api_key(headers)

    if not _main._pipeline or not _main._logosnode_facade:
        return JSONResponse(content={"error": "Scheduler not initialized"}, status_code=503)

    payload = {
        "queue_total": _main._pipeline.scheduler.get_total_queue_depth(),
        "logosnode": _main._logosnode_facade.debug_state(),
    }
    prefix_router = getattr(_main._pipeline.scheduler, "_prefix_router", None)
    if prefix_router is not None:
        payload["prefix_affinity"] = prefix_router.debug_state()
    return JSONResponse(content=payload, status_code=200)


def _today_utc() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


@router.post("/logosdb/get_ollama_vram_stats", tags=["admin"])
async def get_ollama_vram_stats(request: Request):
    """
    Return live LogosWorkerNode provider VRAM usage for dashboards.

    Request body:
    {
        "day": "2025-01-05",                    # Optional, ignored for runtime-backed stats
        "bucket_seconds": 5,                    # Optional, ignored for compatibility
        "after_snapshot_id": 0                  # Optional, return only snapshots with
                                                # snapshot_id > this (incremental polling)
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
    auth = authenticate_api_key(headers)
    logos_key = auth.key_value

    day = _today_utc()
    after_snapshot_id = 0

    # Tolerate empty/no-body requests for compatibility with older clients.
    try:
        body = await request.json()
        if isinstance(body, dict):
            if isinstance(body.get("day"), str) and body.get("day", "").strip():
                day = body["day"].strip()
            # Honor the incremental cursor so per-second pollers can fetch only
            # new snapshots instead of re-receiving the whole day on every call.
            raw_cursor = body.get("after_snapshot_id")
            if raw_cursor is not None:
                try:
                    after_snapshot_id = max(0, int(raw_cursor))
                except (TypeError, ValueError):
                    after_snapshot_id = 0
    except json.JSONDecodeError:
        pass

    return JSONResponse(
        content=_build_live_local_provider_vram_payload(logos_key, day=day, after_snapshot_id=after_snapshot_id),
        status_code=200,
    )


@router.options("/logosdb/get_ollama_vram_stats", tags=["admin"])
async def get_ollama_vram_stats_options():
    """CORS preflight for get_ollama_vram_stats."""
    return JSONResponse(
        content={},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, logos_key",
        },
    )


@router.get("/forward_host", tags=["admin"])
async def forward_host(request: Request):
    forwarded = request.headers.get("X-Forwarded-Host") or request.headers.get("Forwarded")
    return JSONResponse(content={"host": forwarded})
