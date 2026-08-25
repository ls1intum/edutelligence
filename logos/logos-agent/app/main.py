"""The agent runner's HTTP surface.

Reached from the UI through Traefik at /api/agent/*. Every route except the
health check requires a Keycloak token carrying the operator role.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse, Response, StreamingResponse

from . import capacity, db, docker_engine, github
from .auth import Principal, require_agent_operator
from .config import settings
from .schemas import (
    CapacityState,
    SessionCreate,
    SessionEvent,
    SessionStatus,
    SessionSummary,
    Workspace,
    WorkspaceCreate,
)
from .sessions import artifact_dir, manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("logos.agent")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.auth_disabled and not settings.dev_mode:
        raise RuntimeError(
            "LOGOS_AGENT_AUTH_DISABLED is set without LOGOS_AGENT_DEV_MODE. "
            "Refusing to start an unauthenticated agent runner."
        )
    if settings.pause_above_load <= settings.start_below_load:
        raise RuntimeError(
            "LOGOS_AGENT_PAUSE_ABOVE_LOAD must exceed LOGOS_AGENT_START_BELOW_LOAD, "
            "otherwise sessions start and pause in a loop."
        )
    await manager.start()
    logger.info(
        "agent runner ready: max %s parallel sessions, start below %.0f%% load, " "pause above %.0f%%",
        settings.max_parallel_sessions,
        settings.start_below_load * 100,
        settings.pause_above_load * 100,
    )
    try:
        yield
    finally:
        await manager.stop()


app = FastAPI(
    title="Logos Agent Runner",
    description=(
        "Runs coding agents in isolated containers on capacity Logos is not "
        "otherwise using. Sessions act on the dev environment only."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


# --- health ---------------------------------------------------------------


@app.get("/health", tags=["monitoring"])
async def health() -> dict[str, object]:
    database_ok = await db.ping()
    docker_ok = await docker_engine.ping()
    healthy = database_ok and docker_ok
    return {
        "status": "ok" if healthy else "degraded",
        "database": database_ok,
        "docker": docker_ok,
    }


# --- capacity -------------------------------------------------------------


@app.get("/capacity", response_model=CapacityState, tags=["capacity"])
async def get_capacity(_: Principal = Depends(require_agent_operator)) -> CapacityState:
    reading = await capacity.read_load()
    counts = await db.count_sessions_by_status()
    running = counts.get(SessionStatus.RUNNING.value, 0)
    paused = counts.get(SessionStatus.PAUSED.value, 0)
    may_start, reason = capacity.start_decision(reading, running=running, paused=paused)
    return CapacityState(
        load=round(reading.load, 4),
        total_slots=reading.total_slots,
        busy_slots=reading.busy_slots,
        sessions_running=running,
        sessions_queued=counts.get(SessionStatus.QUEUED.value, 0),
        sessions_paused=paused,
        max_parallel=settings.max_parallel_sessions,
        may_start=may_start,
        reason=reason,
    )


# --- workspaces -----------------------------------------------------------


@app.get("/workspaces", response_model=list[Workspace], tags=["workspaces"])
async def list_workspaces(_: Principal = Depends(require_agent_operator)) -> list[Workspace]:
    return [Workspace(**row) for row in await db.list_workspaces()]


@app.post(
    "/workspaces",
    response_model=Workspace,
    status_code=status.HTTP_201_CREATED,
    tags=["workspaces"],
)
async def create_workspace(body: WorkspaceCreate, principal: Principal = Depends(require_agent_operator)) -> Workspace:
    try:
        row = await db.create_workspace(body.name, body.base_branch, principal.username)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    await docker_engine.ensure_volume(row["volume_name"], labels={"logos.agent.workspace": row["name"]})
    return Workspace(**row, active_sessions=0)


@app.delete(
    "/workspaces/{workspace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    # 204 must carry no body, so the route returns a bare Response. Annotating
    # it `-> None` instead makes FastAPI derive a response model and refuse to
    # start the application.
    response_class=Response,
    tags=["workspaces"],
)
async def delete_workspace(workspace_id: int, _: Principal = Depends(require_agent_operator)) -> Response:
    workspace = await db.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    try:
        await db.delete_workspace(workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    await docker_engine.remove_volume(workspace["volume_name"], force=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- sessions -------------------------------------------------------------


@app.get("/sessions", response_model=list[SessionSummary], tags=["sessions"])
async def list_sessions(
    session_status: str | None = Query(default=None, alias="status"),
    workspace_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    _: Principal = Depends(require_agent_operator),
) -> list[SessionSummary]:
    rows = await db.list_sessions(status=session_status, workspace_id=workspace_id, limit=limit)
    return [SessionSummary(**_summary_fields(row)) for row in rows]


@app.post(
    "/sessions",
    response_model=SessionSummary,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["sessions"],
)
async def create_session(body: SessionCreate, principal: Principal = Depends(require_agent_operator)) -> SessionSummary:
    workspace = await db.get_workspace(body.workspace_id)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    if body.deploy_to_dev and not settings.deploy_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Deploys are disabled on this runner (LOGOS_AGENT_DEPLOY_ENABLED)",
        )
    if not settings.agent_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LOGOS_AGENT_API_KEY is not configured; sessions have no way to reach a model",
        )

    session_id = await db.create_session(
        workspace_id=body.workspace_id,
        task=body.task,
        model=body.model,
        created_by=principal.username,
        open_pull_request=body.open_pull_request,
        deploy_to_dev=body.deploy_to_dev,
        screenshot_paths=body.screenshot_paths,
    )
    # Admission is the scheduler's job, but running a pass now means a session
    # created while the platform is idle starts in a second rather than at the
    # next tick.
    asyncio.create_task(manager.scheduler_pass())

    row = await db.get_session(session_id)
    assert row is not None
    return SessionSummary(**_summary_fields(row))


@app.get("/sessions/{session_id}", response_model=SessionSummary, tags=["sessions"])
async def get_session(session_id: int, _: Principal = Depends(require_agent_operator)) -> SessionSummary:
    row = await db.get_session(session_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return SessionSummary(**_summary_fields(row))


@app.post("/sessions/{session_id}/cancel", tags=["sessions"])
async def cancel_session(session_id: int, _: Principal = Depends(require_agent_operator)) -> dict[str, object]:
    row = await db.get_session(session_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    cancelled = await manager.cancel(session_id)
    if not cancelled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session is {row['status']} and cannot be cancelled",
        )
    return {"cancelled": True}


@app.get("/sessions/{session_id}/events", response_model=list[SessionEvent], tags=["sessions"])
async def list_events(
    session_id: int,
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
    _: Principal = Depends(require_agent_operator),
) -> list[SessionEvent]:
    if await db.get_session(session_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return [SessionEvent(**row) for row in await db.list_events(session_id, after_id=after_id, limit=limit)]


@app.get("/sessions/{session_id}/stream", tags=["sessions"])
async def stream_events(
    session_id: int,
    after_id: int = Query(default=0, ge=0),
    _: Principal = Depends(require_agent_operator),
) -> StreamingResponse:
    """Server-sent events: the session's event log as it is written.

    Polling the database rather than tailing the container directly means a
    reconnecting browser resumes exactly where it left off, and several viewers
    can watch the same session without multiplying load on the daemon.
    """
    if await db.get_session(session_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    async def generate():
        cursor = after_id
        idle_ticks = 0
        while True:
            events = await db.list_events(session_id, after_id=cursor, limit=200)
            for event in events:
                cursor = event["id"]
                payload = {
                    "id": event["id"],
                    "ts": event["ts"].isoformat(),
                    "kind": event["kind"],
                    "payload": event["payload"],
                }
                yield f"data: {json.dumps(payload)}\n\n"
            if events:
                idle_ticks = 0
            else:
                idle_ticks += 1
                # Keep the connection alive through proxies during quiet spells.
                yield ": keep-alive\n\n"

            session = await db.get_session(session_id)
            if session and session["status"] in (
                SessionStatus.SUCCEEDED,
                SessionStatus.FAILED,
                SessionStatus.CANCELLED,
            ):
                # Drain whatever landed after the terminal transition, then end
                # the stream so the browser stops reconnecting.
                remaining = await db.list_events(session_id, after_id=cursor, limit=200)
                for event in remaining:
                    payload = {
                        "id": event["id"],
                        "ts": event["ts"].isoformat(),
                        "kind": event["kind"],
                        "payload": event["payload"],
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                yield "event: end\ndata: {}\n\n"
                return
            if idle_ticks > 600:  # ~20 minutes of nothing; let the client reconnect
                return
            await asyncio.sleep(2.0)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/sessions/{session_id}/screenshots/{name}", tags=["sessions"])
async def get_screenshot(session_id: int, name: str, _: Principal = Depends(require_agent_operator)) -> FileResponse:
    # Reject traversal before touching the filesystem: `name` comes straight
    # from a URL, and the artefact root holds every session's output.
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid name")
    path = (artifact_dir(session_id) / "screenshots" / name).resolve()
    root = (artifact_dir(session_id) / "screenshots").resolve()
    if not str(path).startswith(str(root)) or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Screenshot not found")
    return FileResponse(path)


@app.get("/sessions/{session_id}/pull-request", tags=["sessions"])
async def session_pull_request(session_id: int, _: Principal = Depends(require_agent_operator)) -> dict[str, object]:
    row = await db.get_session(session_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if not row.get("pr_url"):
        return {"pull_request": None}
    return {"pull_request": await github.pull_request_state(str(row["pr_url"]))}


def _summary_fields(row: dict) -> dict:
    """Project a database row onto the response model's fields."""
    keys = set(SessionSummary.model_fields)
    return {k: v for k, v in row.items() if k in keys}
