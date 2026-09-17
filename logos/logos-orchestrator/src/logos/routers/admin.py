"""Admin endpoints under /logosdb.

The user-facing admin surface (provider management, VRAM dashboards, ...)
lives in the Java webservice, which verifies Keycloak tokens and talks to the
database or the internal API directly. What remains here are endpoints that
exist for *internal services on the cluster network*: they are gated on the
shared ``LOGOS_INTERNAL_SECRET`` like the ``/internal/*`` routes, never on a
plain user API key.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import logos.main as _main
from logos.routers.internal import _require_internal_secret

router = APIRouter()


@router.get("/logosdb/scheduler_state", tags=["admin"])
async def scheduler_state(request: Request):
    """
    In-memory scheduler and LogosWorkerNode capacity state.

    Internal only: the payload carries live queue depth, lane and prefix-
    affinity internals that no end user needs. The consumer is the agent
    runner, which polls it with the shared internal secret (the same
    credential the /internal/* routes accept), so a holder of any Logos API
    key can no longer read cluster state.
    """
    _require_internal_secret(request, disabled_detail="Scheduler state endpoint disabled")

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
