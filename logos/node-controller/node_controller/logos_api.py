"""
Logos-facing status API endpoints.

These are the endpoints Logos polls to get node status, GPU metrics, loaded
models, and the current Ollama config.  All require authentication.

Logos sends inference requests DIRECTLY to the Ollama container's published
port — these endpoints are for management data only.

Service instances (manager, gpu_collector, status_poller) are stored in
``app.state`` during lifespan and accessed via ``request.app.state``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request

from node_controller.auth import verify_api_key
from node_controller.config import get_config
from node_controller.models import GpuSnapshot, NodeStatus, OllamaConfig, OllamaStatus

router = APIRouter(tags=["status"])


@router.get(
    "/status",
    response_model=NodeStatus,
    summary="Full node status — the primary endpoint Logos should poll",
    dependencies=[Depends(verify_api_key)],
)
async def get_status(request: Request) -> NodeStatus:
    """
    Combined snapshot: container state, loaded models, GPU metrics, config.

    This is the **single endpoint** Logos needs to poll instead of hitting
    Ollama's /api/ps directly.  It gives Logos real GPU metrics, the actual
    num_parallel setting, loaded models, and available VRAM.
    """
    cfg = get_config()
    manager = request.app.state.ollama_manager
    status_poller = request.app.state.status_poller
    gpu_collector = request.app.state.gpu_collector

    container_status = await manager.status(cfg.ollama.container_name)
    ollama_status = await status_poller.get_status()
    gpu_snapshot = await gpu_collector.get_snapshot()

    return NodeStatus(
        timestamp=datetime.now(timezone.utc),
        container=container_status,
        ollama=ollama_status,
        gpu=gpu_snapshot,
        config=cfg.ollama,
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
    "/models",
    response_model=OllamaStatus,
    summary="Available + loaded models with VRAM breakdown",
    dependencies=[Depends(verify_api_key)],
)
async def get_models(request: Request) -> OllamaStatus:
    return await request.app.state.status_poller.get_status()


@router.get(
    "/config",
    response_model=OllamaConfig,
    summary="Current Ollama runtime configuration",
    dependencies=[Depends(verify_api_key)],
)
async def get_ollama_config() -> OllamaConfig:
    return get_config().ollama
