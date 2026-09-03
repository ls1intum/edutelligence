"""The agent runner's HTTP surface.

Reached from the UI through Traefik at /api/agent/*. Every route except the
health check requires a Keycloak token carrying the operator role.
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import stat
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse

from . import capacity, controls, db, docker_engine, github, model_policy, triggers
from .auth import Principal, require_agent_operator
from .config import settings
from .schemas import (
    CapacityState,
    ControlState,
    ControlUpdate,
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
    # A token that belongs to somebody else would put agent commits and pull
    # requests under their name, which no later check can undo — so it stops
    # the service here.
    for note in await github.verify_identities():
        logger.info("github identity: %s", note)
    # The local-only model policy does not stop startup: the UI has to come
    # up to *show* the reason, and admission is gated on it anyway.
    policy = await model_policy.refresh()
    if not policy.ok:
        logger.error("no session will start until the model policy is satisfied: %s", policy.detail)
    if settings.session_github_token and settings.session_github_token == settings.github_token:
        logger.warning(
            "session containers get the runner's own GitHub token: it can dispatch "
            "workflows and edit workflow files. Issue a second token of the same "
            "account without 'workflow' scope as LOGOS_AGENT_SESSION_GITHUB_TOKEN to "
            "keep that out of the agent's reach."
        )
    await manager.start()
    triggers.poller.on_queued = manager.scheduler_pass
    await triggers.poller.start()
    logger.info(
        "agent runner ready: max %s parallel sessions, start below %.0f%% load, " "pause above %.0f%%",
        settings.max_parallel_sessions,
        settings.start_below_load * 100,
        settings.pause_above_load * 100,
    )
    try:
        yield
    finally:
        await triggers.poller.stop()
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
    control = await controls.current()
    may_start, reason = capacity.start_decision(
        reading, running=running, paused=paused, max_parallel=control.max_parallel
    )
    blocked = control.admission_block()
    if blocked:
        may_start, reason = False, blocked
    # The local-only model policy gates admission as hard as load does, so
    # the page that explains why nothing starts has to show it too — an
    # operator staring at an idle platform should not have to read the logs
    # to learn that the agent key was granted a cloud provider.
    policy = await model_policy.refresh()
    if not policy.ok:
        may_start, reason = False, policy.detail
    return CapacityState(
        models_local_only=policy.ok,
        models_detail=policy.detail,
        load=round(reading.load, 4),
        total_slots=reading.total_slots,
        busy_slots=reading.busy_slots,
        sessions_running=running,
        sessions_queued=counts.get(SessionStatus.QUEUED.value, 0),
        sessions_paused=paused,
        max_parallel=control.max_parallel,
        may_start=may_start,
        reason=reason,
    )


def _control_state(state: controls.Controls) -> ControlState:
    return ControlState(
        mode=state.mode,
        mode_reason=state.mode_reason,
        paused=state.paused,
        admits_new_sessions=not state.admission_block(),
        max_parallel=state.max_parallel,
        max_parallel_override=state.max_parallel_override,
        max_parallel_configured=settings.max_parallel_sessions,
        updated_by=state.updated_by,
    )


@app.get("/controls", response_model=ControlState, tags=["capacity"])
async def get_controls(_: Principal = Depends(require_agent_operator)) -> ControlState:
    """The kill switch and the ceiling, as they stand."""
    return _control_state(await controls.current())


@app.post("/controls", response_model=ControlState, tags=["capacity"])
async def update_controls(body: ControlUpdate, principal: Principal = Depends(require_agent_operator)) -> ControlState:
    """Stop the runner, drain it, or change how much of the platform it uses.

    `draining` starts nothing new and lets what is running finish;
    `paused` hands everything back on the next scheduler pass. Neither
    cancels anything, so going back to `running` resumes the work mid-task.
    """
    state = await controls.current()
    if body.mode is not None:
        state = await controls.set_mode(mode=body.mode, reason=body.reason, by=principal.username)
        logger.info(
            "%s set the agent runner to %s%s",
            principal.username,
            body.mode,
            f": {body.reason}" if body.reason else "",
        )
    if body.clear_max_parallel or body.max_parallel is not None:
        limit = None if body.clear_max_parallel else body.max_parallel
        state = await controls.set_max_parallel(limit=limit, by=principal.username)
        logger.info("%s set the parallel ceiling to %s", principal.username, limit if limit is not None else "default")
    # A pause takes effect on the next pass anyway; running one now means the
    # operator sees it happen instead of waiting a tick for it.
    asyncio.create_task(manager.scheduler_pass())
    return _control_state(state)


@app.get("/models", tags=["capacity"])
async def get_models(_: Principal = Depends(require_agent_operator)) -> dict[str, object]:
    """The models a session may be driven by, and the default among them.

    Only locally served ones are ever listed: this is the same policy that
    gates admission, so what the form offers is exactly what will be
    accepted.
    """
    policy = await model_policy.refresh()
    return {
        "models": list(policy.offered),
        "default": policy.default_model,
        "local_only": policy.ok,
        "detail": policy.detail,
    }


@app.get("/triggers", tags=["capacity"])
async def get_triggers(_: Principal = Depends(require_agent_operator)) -> dict[str, object]:
    """Whether the runner reacts to the repository, and what it has done."""
    control = await controls.current()
    status = triggers.poller.status(control.max_parallel)
    status["active_sessions"] = await triggers.active_trigger_sessions()
    return status


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
    # Refuse a model that is not served locally at the point where a person
    # asks for it, rather than accepting the session and failing it later:
    # agent work must never bill a cloud provider, and the operator finds out
    # in the form they submitted.
    policy = await model_policy.refresh()
    if not policy.allows(body.model):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=policy.refusal(body.model))

    try:
        session_id = await db.create_session(
            workspace_id=body.workspace_id,
            task=body.task,
            model=body.model,
            created_by=principal.username,
            open_pull_request=body.open_pull_request,
            deploy_to_dev=body.deploy_to_dev,
            screenshot_paths=body.screenshot_paths,
        )
    except ValueError as exc:
        # The workspace was deleted between the 404 check above and the
        # insert: fail the create instead of accepting a session whose
        # workspace no longer exists.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
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


def _serve_session_file(target: Path) -> Response | None:
    """Open one of a session's own files without following links, or None.

    The session that wrote the file ran unprivileged: it can leave a
    symlink named like a file, and a check-then-serve sequence leaves a
    window in which a still-running session can swap the file for a link
    before the read. Opening with ``O_NOFOLLOW`` and verifying the opened
    descriptor closes both: whatever name the link had, the open fails,
    and the regular-file check happens on the descriptor, not on the name.
    """
    try:
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
    except OSError:
        os.close(fd)
        return None
    if not stat.S_ISREG(info.st_mode):
        os.close(fd)
        return None
    file = os.fdopen(fd, "rb")

    def stream() -> Iterator[bytes]:
        # The response object must be what actually reads the descriptor:
        # a plain Response sends its (empty) body and never touches
        # body_iterator, which would advertise the file's length and then
        # ship zero bytes. Owning the file here is what guarantees the
        # descriptor is closed exactly once, when the stream ends.
        try:
            while chunk := file.read(65536):
                yield chunk
        finally:
            file.close()

    return StreamingResponse(
        stream(),
        status_code=200,
        media_type=mimetypes.guess_type(target.name)[0] or "application/octet-stream",
        headers={"Content-Length": str(info.st_size)},
    )


@app.get("/sessions/{session_id}/screenshots/{name}", tags=["sessions"])
async def get_screenshot(session_id: int, name: str, _: Principal = Depends(require_agent_operator)) -> Response:
    # Reject traversal before touching the filesystem: `name` comes straight
    # from a URL, and the artefact root holds every session's output.
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid name")
    # The trusted root is the artefact directory as the runner knows it —
    # never the resolved screenshots path: the session that wrote it ran
    # unprivileged and could turn `screenshots` itself into a link into
    # anywhere the runner can read (its own /proc/self included), and a
    # link resolved into its own root would pass any containment check
    # built on it.
    base = artifact_dir(session_id) / "screenshots"
    target = base / name
    if base.is_symlink() or target.is_symlink() or not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Screenshot not found")
    if not target.resolve().is_relative_to(base.resolve()):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Screenshot not found")
    response = _serve_session_file(target)
    if response is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Screenshot not found")
    return response


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
