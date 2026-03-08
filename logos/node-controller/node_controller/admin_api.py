"""
Admin API endpoints for authenticated operators.

Provides Ollama container lifecycle management (start/stop/restart/reconfigure/
destroy), model operations (pull/delete/unload/preload), and a health check.

Service instances are stored in ``app.state`` during lifespan and accessed
via ``request.app.state``.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

import docker.errors

from node_controller.auth import verify_api_key
from node_controller.config import apply_reconfigure, get_config
from node_controller.models import (
    ActionResponse,
    ContainerState,
    HealthResponse,
    ModelActionRequest,
    ModelCreateRequest,
    ModelInfoResponse,
    ReconfigureRequest,
)

router = APIRouter(tags=["admin"])


# ------------------------------------------------------------------
# Health (public — no auth for Docker health checks)
# ------------------------------------------------------------------


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Public health check for Docker / load balancer probes",
)
async def health(request: Request) -> HealthResponse:
    cfg = get_config()
    manager = request.app.state.ollama_manager
    gpu_collector = request.app.state.gpu_collector

    container = await manager.status(cfg.ollama.container_name)
    gpu_snap = await gpu_collector.get_snapshot()
    return HealthResponse(
        status="ok",
        ollama_running=container.state == ContainerState.RUNNING,
        gpu_available=gpu_snap.nvidia_smi_available,
    )


# ------------------------------------------------------------------
# Ollama container lifecycle
# ------------------------------------------------------------------


@router.post(
    "/admin/ollama/start",
    response_model=ActionResponse,
    summary="Start the Ollama container",
    dependencies=[Depends(verify_api_key)],
)
async def start_ollama(request: Request) -> ActionResponse:
    cfg = get_config()
    manager = request.app.state.ollama_manager
    try:
        cs = await manager.start(cfg.ollama.container_name)
        return ActionResponse(
            success=True,
            message=f"Container started (state={cs.state.value})",
            details=cs.model_dump(mode="json"),
        )
    except ValueError:
        # Container doesn't exist — create it
        try:
            cs = await manager.create(cfg.ollama)
            return ActionResponse(
                success=True,
                message=f"Container created and started (state={cs.state.value})",
                details=cs.model_dump(mode="json"),
            )
        except docker.errors.APIError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Docker error creating Ollama container: {exc.explanation or str(exc)}",
            )
    except docker.errors.APIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Docker error starting Ollama container: {exc.explanation or str(exc)}",
        )


@router.post(
    "/admin/ollama/stop",
    response_model=ActionResponse,
    summary="Gracefully stop the Ollama container",
    dependencies=[Depends(verify_api_key)],
)
async def stop_ollama(request: Request) -> ActionResponse:
    cfg = get_config()
    manager = request.app.state.ollama_manager
    try:
        cs = await manager.stop(cfg.ollama.container_name)
        return ActionResponse(
            success=True,
            message="Container stopped",
            details=cs.model_dump(mode="json"),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except docker.errors.APIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Docker error: {exc.explanation or str(exc)}",
        )


@router.post(
    "/admin/ollama/restart",
    response_model=ActionResponse,
    summary="Restart the Ollama container without config change",
    dependencies=[Depends(verify_api_key)],
)
async def restart_ollama(request: Request) -> ActionResponse:
    cfg = get_config()
    manager = request.app.state.ollama_manager
    try:
        cs = await manager.restart(cfg.ollama.container_name)
        return ActionResponse(
            success=True,
            message="Container restarted",
            details=cs.model_dump(mode="json"),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except docker.errors.APIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Docker error: {exc.explanation or str(exc)}",
        )


@router.post(
    "/admin/ollama/reconfigure",
    response_model=ActionResponse,
    summary="Update Ollama config and recreate the container if needed",
    dependencies=[Depends(verify_api_key)],
)
async def reconfigure_ollama(request: Request, req: ReconfigureRequest) -> ActionResponse:
    """
    Apply partial config updates.  Only provided (non-None) fields are
    changed.  If any runtime-affecting fields changed, the container is
    destroyed and recreated with the new settings.
    """
    updates = req.model_dump(exclude_none=True)
    if not updates:
        return ActionResponse(success=True, message="No changes requested")

    try:
        new_config, needs_restart, changed = apply_reconfigure(updates)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    # Nothing actually changed — all submitted values match current config
    if not changed:
        return ActionResponse(
            success=True,
            message="No changes detected — all values already match current config",
            details={
                "changed_fields": [],
                "restarted": False,
                "submitted_fields": list(updates.keys()),
            },
        )

    manager = request.app.state.ollama_manager
    status_poller = request.app.state.status_poller

    if needs_restart:
        try:
            cs = await manager.recreate(new_config)
        except docker.errors.APIError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Docker error recreating container: {exc.explanation or str(exc)}",
            )
        status_poller.update_config(new_config)
        return ActionResponse(
            success=True,
            message="Configuration updated — container recreated",
            details={
                "container": cs.model_dump(mode="json"),
                "changed_fields": changed,
                "restarted": True,
            },
        )
    else:
        # Non-restart fields (e.g. preload_models) — just save
        status_poller.update_config(new_config)
        return ActionResponse(
            success=True,
            message="Configuration updated (no restart required)",
            details={
                "changed_fields": changed,
                "restarted": False,
            },
        )


@router.post(
    "/admin/ollama/destroy",
    response_model=ActionResponse,
    summary="Force-remove the Ollama container entirely",
    dependencies=[Depends(verify_api_key)],
)
async def destroy_ollama(request: Request) -> ActionResponse:
    cfg = get_config()
    manager = request.app.state.ollama_manager
    await manager.destroy(cfg.ollama.container_name)
    return ActionResponse(success=True, message="Container destroyed")


# ------------------------------------------------------------------
# Model operations
# ------------------------------------------------------------------


@router.post(
    "/admin/models/pull",
    response_model=ActionResponse,
    summary="Pull (download) a model",
    dependencies=[Depends(verify_api_key)],
)
async def pull_model(request: Request, req: ModelActionRequest) -> ActionResponse:
    cfg = get_config()
    manager = request.app.state.ollama_manager
    ok = await manager.pull_model(cfg.ollama, req.model)
    if ok:
        return ActionResponse(success=True, message=f"Model '{req.model}' pulled")
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"Failed to pull model '{req.model}'",
    )


@router.post(
    "/admin/models/delete",
    response_model=ActionResponse,
    summary="Delete a model from disk",
    dependencies=[Depends(verify_api_key)],
)
async def delete_model(request: Request, req: ModelActionRequest) -> ActionResponse:
    cfg = get_config()
    manager = request.app.state.ollama_manager
    ok = await manager.delete_model(cfg.ollama, req.model)
    if ok:
        return ActionResponse(success=True, message=f"Model '{req.model}' deleted")
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"Failed to delete model '{req.model}'",
    )


@router.post(
    "/admin/models/unload",
    response_model=ActionResponse,
    summary="Unload a model from VRAM (set keep_alive=0)",
    dependencies=[Depends(verify_api_key)],
)
async def unload_model(request: Request, req: ModelActionRequest) -> ActionResponse:
    cfg = get_config()
    manager = request.app.state.ollama_manager
    ok = await manager.unload_model(cfg.ollama, req.model)
    if ok:
        return ActionResponse(success=True, message=f"Model '{req.model}' unloaded")
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"Failed to unload model '{req.model}'",
    )


@router.post(
    "/admin/models/preload",
    response_model=ActionResponse,
    summary="Preload a model into VRAM",
    dependencies=[Depends(verify_api_key)],
)
async def preload_model(request: Request, req: ModelActionRequest) -> ActionResponse:
    cfg = get_config()
    manager = request.app.state.ollama_manager
    ok = await manager.preload_model(cfg.ollama, req.model)
    if ok:
        return ActionResponse(success=True, message=f"Model '{req.model}' preloaded")
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"Failed to preload model '{req.model}'",
    )


# ------------------------------------------------------------------
# Model customization — create variants, inspect, copy
# ------------------------------------------------------------------


@router.post(
    "/admin/models/create",
    response_model=ActionResponse,
    summary="Create a model variant from a Modelfile (custom num_ctx, system prompt, etc.)",
    dependencies=[Depends(verify_api_key)],
)
async def create_model(request: Request, req: ModelCreateRequest) -> ActionResponse:
    """
    Create a model variant using Ollama's Modelfile format.

    This is the primary mechanism for per-model customization without\
    restarting the container.  Common uses:

    - **Custom context length**: ``PARAMETER num_ctx 8192``
    - **Custom temperature**: ``PARAMETER temperature 0.3``
    - **System prompt**: ``SYSTEM You are a helpful coding assistant.``
    - **LoRA adapters**: ``ADAPTER /path/to/adapter``
    """
    cfg = get_config()
    manager = request.app.state.ollama_manager
    ok = await manager.create_model(cfg.ollama, req.name, req.modelfile)
    if ok:
        return ActionResponse(
            success=True,
            message=f"Model '{req.name}' created from Modelfile",
        )
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"Failed to create model '{req.name}'",
    )


@router.post(
    "/admin/models/show",
    response_model=ModelInfoResponse,
    summary="Show detailed model information (Modelfile, parameters, template)",
    dependencies=[Depends(verify_api_key)],
)
async def show_model(request: Request, req: ModelActionRequest) -> ModelInfoResponse:
    cfg = get_config()
    manager = request.app.state.ollama_manager
    info = await manager.show_model(cfg.ollama, req.model)
    if info is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model '{req.model}' not found or unreachable",
        )
    return ModelInfoResponse(
        name=req.model,
        modelfile=info.get("modelfile", ""),
        parameters=info.get("parameters", ""),
        template=info.get("template", ""),
        details=info.get("details", {}),
        model_info=info.get("model_info", {}),
    )


class ModelCopyRequest(ModelActionRequest):
    """Copy a model under a new name."""
    destination: str


@router.post(
    "/admin/models/copy",
    response_model=ActionResponse,
    summary="Copy/alias a model under a new name (instant, no disk copy)",
    dependencies=[Depends(verify_api_key)],
)
async def copy_model(request: Request, req: ModelCopyRequest) -> ActionResponse:
    cfg = get_config()
    manager = request.app.state.ollama_manager
    ok = await manager.copy_model(cfg.ollama, req.model, req.destination)
    if ok:
        return ActionResponse(
            success=True,
            message=f"Model '{req.model}' copied to '{req.destination}'",
        )
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"Failed to copy model '{req.model}' to '{req.destination}'",
    )


@router.post(
    "/admin/models/pull/stream",
    summary="Pull a model with streaming progress (SSE)",
    dependencies=[Depends(verify_api_key)],
)
async def pull_model_stream(request: Request, req: ModelActionRequest) -> StreamingResponse:
    """Stream pull progress as newline-delimited JSON (NDJSON).

    Each line is a JSON object like:
        {"status": "pulling abc123", "completed": 1234567, "total": 5000000}
    """
    cfg = get_config()
    manager = request.app.state.ollama_manager

    async def _stream():
        async for chunk in manager.pull_model_streaming(cfg.ollama, req.model):
            yield json.dumps(chunk) + "\n"

    return StreamingResponse(
        _stream(),
        media_type="application/x-ndjson",
    )
