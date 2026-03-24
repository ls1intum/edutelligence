"""Authenticated local admin API for LogosWorkerNode."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from starlette.responses import Response

from logos_worker_node.auth import verify_api_key
from logos_worker_node.config import save_lanes_config
from logos_worker_node.models import (
    ActionResponse,
    HealthResponse,
    LaneApplyResult,
    LaneEvent,
    LaneReconfigureRequest,
    LaneSetRequest,
    LaneSleepRequest,
    LaneStatus,
    WorkerRuntimeStatus,
)
from logos_worker_node.prometheus_metrics import metrics_response as _prometheus_metrics_response
from logos_worker_node.runtime import build_runtime_status

router = APIRouter(tags=["admin"])


@router.get("/metrics", tags=["monitoring"], summary="Prometheus metrics")
async def prometheus_metrics(request: Request) -> Response:
    """Prometheus metrics endpoint."""
    from logos_worker_node.prometheus_metrics import update_from_runtime
    await update_from_runtime(request.app)
    body, content_type = _prometheus_metrics_response()
    return Response(content=body, media_type=content_type)


@router.get("/health", response_model=HealthResponse, summary="Public health check")
async def health(request: Request) -> HealthResponse:
    runtime = await build_runtime_status(request.app)
    return HealthResponse(
        connected_to_logos=runtime.transport.connected,
        lane_count=runtime.capacity.lane_count,
        gpu_available=runtime.devices.mode != "none",
    )


@router.get(
    "/admin/runtime",
    response_model=WorkerRuntimeStatus,
    summary="Current worker runtime snapshot",
    dependencies=[Depends(verify_api_key)],
)
async def get_runtime(request: Request) -> WorkerRuntimeStatus:
    return await build_runtime_status(request.app)


@router.post(
    "/admin/lanes/apply",
    response_model=LaneApplyResult,
    summary="Apply the desired lane set declaratively",
    dependencies=[Depends(verify_api_key)],
)
async def apply_lanes(request: Request, req: LaneSetRequest) -> LaneApplyResult:
    lane_manager = request.app.state.lane_manager
    try:
        result = await lane_manager.apply_lanes(req.lanes)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if result.success:
        request.app.state.config.lanes = req.lanes
        save_lanes_config(req.lanes)
    return result


@router.get(
    "/admin/lanes",
    response_model=list[LaneStatus],
    summary="List all active lanes",
    dependencies=[Depends(verify_api_key)],
)
async def get_lanes(request: Request) -> list[LaneStatus]:
    return await request.app.state.lane_manager.get_all_statuses()


@router.get(
    "/admin/lanes/events",
    response_model=list[LaneEvent],
    summary="Recent lane transition events",
    dependencies=[Depends(verify_api_key)],
)
async def get_lane_events(request: Request, limit: int = 100) -> list[LaneEvent]:
    events = request.app.state.lane_manager.event_log
    if limit <= 0:
        return []
    return events[-min(limit, len(events)):]


@router.get(
    "/admin/lanes/{lane_id}",
    response_model=LaneStatus,
    summary="Get a single lane",
    dependencies=[Depends(verify_api_key)],
)
async def get_lane(request: Request, lane_id: str) -> LaneStatus:
    try:
        return await request.app.state.lane_manager.get_lane_status(lane_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch(
    "/admin/lanes/{lane_id}",
    response_model=LaneStatus,
    summary="Reconfigure a single lane",
    dependencies=[Depends(verify_api_key)],
)
async def patch_lane(request: Request, lane_id: str, req: LaneReconfigureRequest) -> LaneStatus:
    updates = req.model_dump(exclude_none=True)
    try:
        lane = await request.app.state.lane_manager.reconfigure_lane(lane_id, updates)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    cfg = request.app.state.config
    cfg.lanes = [
        lane.lane_config if lane.lane_id == lane_id and lane.lane_config is not None else existing
        for existing in cfg.lanes
    ]
    save_lanes_config(cfg.lanes)
    return lane


@router.post(
    "/admin/lanes/{lane_id}/sleep",
    response_model=LaneStatus,
    summary="Sleep a vLLM lane",
    dependencies=[Depends(verify_api_key)],
)
async def sleep_lane(request: Request, lane_id: str, req: LaneSleepRequest) -> LaneStatus:
    try:
        return await request.app.state.lane_manager.sleep_lane(lane_id, req.level, req.mode)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post(
    "/admin/lanes/{lane_id}/wake",
    response_model=LaneStatus,
    summary="Wake a vLLM lane",
    dependencies=[Depends(verify_api_key)],
)
async def wake_lane(request: Request, lane_id: str) -> LaneStatus:
    try:
        return await request.app.state.lane_manager.wake_lane(lane_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.delete(
    "/admin/lanes/{lane_id}",
    response_model=ActionResponse,
    summary="Delete a lane",
    dependencies=[Depends(verify_api_key)],
)
async def delete_lane(request: Request, lane_id: str) -> ActionResponse:
    try:
        await request.app.state.lane_manager.remove_lane(lane_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    cfg = request.app.state.config
    cfg.lanes = [lane for lane in cfg.lanes if (lane.lane_id or lane.model).replace("/", "_").replace(":", "_") != lane_id]
    save_lanes_config(cfg.lanes)
    return ActionResponse(success=True, message=f"Lane '{lane_id}' deleted")
