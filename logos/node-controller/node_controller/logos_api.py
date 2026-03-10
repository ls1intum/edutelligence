"""
Logos-facing status API endpoints.

These are the endpoints Logos polls to get node status, GPU metrics, loaded
models, and the current Ollama config.  All require authentication.

Logos sends inference requests DIRECTLY to the Ollama process's port —
these endpoints are for management data only.

Service instances (manager, gpu_collector, status_poller) are stored in
``app.state`` during lifespan and accessed via ``request.app.state``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request

from node_controller.auth import verify_api_key
from node_controller.config import get_config
from node_controller.models import AvailableModel, GpuSnapshot, LaneStatus, LoadedModel, NodeStatus, OllamaConfig, OllamaStatus

router = APIRouter(tags=["status"])


@router.get(
    "/status",
    response_model=NodeStatus,
    summary="Full node status — the primary endpoint Logos should poll",
    dependencies=[Depends(verify_api_key)],
)
async def get_status(request: Request) -> NodeStatus:
    """
    Combined snapshot: process state, loaded models, GPU metrics, config.

    This is the **single endpoint** Logos needs to poll instead of hitting
    Ollama's /api/ps directly.  It gives Logos real GPU metrics, the actual
    num_parallel setting, loaded models, and available VRAM.

    When running in multi-lane mode, the ``lanes`` field contains per-lane
    runtime state for routing and orchestration:
    - stable identifiers (``lane_id``/``lane_uid``),
    - backend + model config details (including full vLLM params),
    - routing URL/endpoint for direct inference,
    - VRAM usage estimates and sleep state.

    For the full list of downloaded (available) models, use ``/models/available``.
    """
    cfg = get_config()
    manager = request.app.state.ollama_manager
    status_poller = request.app.state.status_poller
    gpu_collector = request.app.state.gpu_collector
    lane_manager = request.app.state.lane_manager

    process_status = manager.status()
    ollama_status = await status_poller.get_status()
    gpu_snapshot = await gpu_collector.get_snapshot()

    # Collect lane statuses if any lanes are running
    lane_statuses: list[LaneStatus] = []
    if lane_manager.is_multi_lane:
        lane_statuses = await lane_manager.get_all_statuses()

    return NodeStatus(
        timestamp=datetime.now(timezone.utc),
        process=process_status,
        ollama_reachable=ollama_status.reachable,
        ollama_version=ollama_status.version,
        loaded_models=ollama_status.loaded_models,
        gpu=gpu_snapshot,
        config=cfg.ollama,
        lanes=lane_statuses,
    )


@router.get(
    "/gpu",
    response_model=GpuSnapshot,
    summary="GPU metrics only (utilization, temp, power, VRAM)",
    dependencies=[Depends(verify_api_key)],
)
async def get_gpu(request: Request) -> GpuSnapshot:
    return await request.app.state.gpu_collector.get_snapshot()


@router.get(
    "/models/loaded",
    response_model=list[LoadedModel],
    summary="Models currently loaded in VRAM (mirrors Ollama /api/ps)",
    dependencies=[Depends(verify_api_key)],
)
async def get_loaded_models(request: Request) -> list[LoadedModel]:
    status = await request.app.state.status_poller.get_status()
    return status.loaded_models


@router.get(
    "/models/available",
    response_model=list[AvailableModel],
    summary="All downloaded models on disk (mirrors Ollama /api/tags)",
    dependencies=[Depends(verify_api_key)],
)
async def get_available_models(request: Request) -> list[AvailableModel]:
    status = await request.app.state.status_poller.get_status()
    return status.available_models


@router.get(
    "/config",
    response_model=OllamaConfig,
    summary="Current Ollama runtime configuration",
    dependencies=[Depends(verify_api_key)],
)
async def get_ollama_config() -> OllamaConfig:
    return get_config().ollama


@router.get(
    "/lanes",
    response_model=list[LaneStatus],
    summary="Per-lane status — model, port, backend, num_parallel (0 for vLLM), VRAM usage",
    dependencies=[Depends(verify_api_key)],
)
async def get_lanes(request: Request) -> list[LaneStatus]:
    """
    Returns the status of all active model lanes.

    Each lane has its own Ollama process on a dedicated port.  Logos
    should route inference requests to ``http://host:{lane.port}``
    for the lane's model.
    """
    lane_manager = request.app.state.lane_manager
    return await lane_manager.get_all_statuses()
