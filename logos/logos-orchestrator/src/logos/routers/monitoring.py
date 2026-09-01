"""Monitoring endpoints: liveness probe and Prometheus metrics."""

import hmac
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from logos.dbutils.dbmanager import DBManager
from logos.logosnode_snapshot import _logosnode_snapshot_is_connected
from logos.main import _PROMETHEUS_API_KEY, _logosnode_registry
from logos.monitoring.prometheus_metrics import metrics_response as _prometheus_metrics_response

logger = logging.getLogger("LogosLogger")

router = APIRouter()


@router.get("/health", tags=["monitoring"])
async def health():
    """Report overall health plus a breakdown of what is serveable.

    Serving local inference is the core function of the orchestrator, so the
    overall ``status`` is only UP when there is a live (non-stale heartbeat)
    local worker that declares at least one capable model. When every local
    provider is offline (or none expose a capable model) we return 503/DOWN so
    external monitors surface the degradation instead of seeing a misleading UP.

    The body always breaks the state down per backend so callers can tell what
    exactly is down: ``local_models`` (logosnode workers) and ``cloud_models``
    (Azure/cloud deployments). Cloud may still be serveable even while local is
    down, which the ``detail`` message makes explicit.

    This endpoint stays a lean liveness signal: it is public (its own Traefik
    router on the secure entrypoint, and liveness probes call it), so it must
    not carry the model catalogue. The per-model view applications need lives
    on the secret-gated /internal/model_health endpoint instead.
    """
    local_ok = False
    cloud_ok = False
    try:
        with DBManager() as db:
            inventory = db.list_local_providers()
            deployments = db.get_all_deployments()
        worker_ids: set[int] = set()
        for provider in inventory:
            provider_id = int(provider.get("provider_id") or 0)
            if provider_id <= 0:
                continue
            worker_ids.add(provider_id)
            snapshot = _logosnode_registry.peek_runtime_snapshot(provider_id)
            if not _logosnode_snapshot_is_connected(snapshot):
                continue
            # Local is serveable if an online worker declares at least one capable model.
            if snapshot.get("capabilities_models"):
                local_ok = True
        # Cloud is serveable if any deployment lives outside the local provider
        # inventory — by type alone this would miscount legacy local worker
        # types (ollama, node, ...) as cloud.
        cloud_ok = any(int(d.get("provider_id") or 0) not in worker_ids for d in deployments)
    except Exception:
        logger.exception("Health check failed to evaluate provider state")
        local_ok = False
        cloud_ok = False

    payload = {
        "status": "UP" if local_ok else "DOWN",
        "local_models": "UP" if local_ok else "DOWN",
        "cloud_models": "UP" if cloud_ok else "DOWN",
    }
    if not local_ok:
        payload["detail"] = "No local provider with a capable model is online." + (
            " Cloud models may still be served." if cloud_ok else " No cloud models are configured."
        )
    return JSONResponse(status_code=200 if local_ok else 503, content=payload)


@router.get("/metrics", tags=["monitoring"])
async def prometheus_metrics(request: Request):
    """Prometheus metrics endpoint. Requires PROMETHEUS_API_KEY env var to be set.
    Pass the key via `Authorization: Bearer <key>` header."""
    if not _PROMETHEUS_API_KEY:
        raise HTTPException(
            status_code=403,
            detail="Metrics endpoint disabled (PROMETHEUS_API_KEY not configured)",
        )
    auth = request.headers.get("authorization", "")
    token = auth.removeprefix("Bearer ").strip() if auth.lower().startswith("bearer ") else auth.strip()
    if not hmac.compare_digest(token.encode("utf-8"), _PROMETHEUS_API_KEY.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid or missing metrics API key")
    body, content_type = _prometheus_metrics_response()
    from starlette.responses import Response

    return Response(content=body, media_type=content_type)
