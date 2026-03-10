"""
Admin API endpoints for authenticated operators.

Provides Ollama process lifecycle management (start/stop/restart/reconfigure/
destroy), model operations (pull/delete/unload/preload), lane management,
and a public health check.

Service instances are stored in ``app.state`` during lifespan and accessed
via ``request.app.state``.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from node_controller.auth import verify_api_key
from node_controller.config import apply_reconfigure, get_config, save_lanes_config
from node_controller.models import (
    ActionResponse,
    HealthResponse,
    LaneApplyResult,
    LaneEvent,
    LaneReconfigureRequest,
    LaneSetRequest,
    LaneSleepRequest,
    LaneStatus,
    ModelActionRequest,
    ModelCreateRequest,
    ModelInfoResponse,
    ProcessState,
    ReconfigureRequest,
)

router = APIRouter(tags=["admin"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Public health check for load balancer probes",
)
async def health(request: Request) -> HealthResponse:
    manager = request.app.state.ollama_manager
    gpu_collector = request.app.state.gpu_collector

    process_status = manager.status()
    gpu_snap = await gpu_collector.get_snapshot()
    return HealthResponse(
        status="ok",
        ollama_running=process_status.state == ProcessState.RUNNING,
        gpu_available=gpu_snap.nvidia_smi_available,
    )


@router.post(
    "/admin/ollama/start",
    response_model=ActionResponse,
    summary="Start (spawn) the Ollama process",
    dependencies=[Depends(verify_api_key)],
)
async def start_ollama(request: Request) -> ActionResponse:
    cfg = get_config()
    manager = request.app.state.ollama_manager
    try:
        ps = await manager.spawn(cfg.ollama)
        return ActionResponse(
            success=True,
            message=f"Ollama process started (state={ps.state.value})",
            details=ps.model_dump(mode="json"),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to spawn Ollama process: {exc}",
        )


@router.post(
    "/admin/ollama/stop",
    response_model=ActionResponse,
    summary="Gracefully stop the Ollama process",
    dependencies=[Depends(verify_api_key)],
)
async def stop_ollama(request: Request) -> ActionResponse:
    manager = request.app.state.ollama_manager
    ps = await manager.stop()
    return ActionResponse(
        success=True,
        message=f"Ollama process stopped (state={ps.state.value})",
        details=ps.model_dump(mode="json"),
    )


@router.post(
    "/admin/ollama/restart",
    response_model=ActionResponse,
    summary="Restart the Ollama process without config change",
    dependencies=[Depends(verify_api_key)],
)
async def restart_ollama(request: Request) -> ActionResponse:
    manager = request.app.state.ollama_manager
    try:
        ps = await manager.restart()
        return ActionResponse(
            success=True,
            message=f"Ollama process restarted (state={ps.state.value})",
            details=ps.model_dump(mode="json"),
        )
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to restart Ollama process: {exc}",
        )


@router.post(
    "/admin/ollama/reconfigure",
    response_model=ActionResponse,
    summary="Update Ollama config and restart the process if needed",
    dependencies=[Depends(verify_api_key)],
)
async def reconfigure_ollama(request: Request, req: ReconfigureRequest) -> ActionResponse:
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
            ps = await manager.reconfigure(new_config)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to reconfigure Ollama process: {exc}",
            )
        status_poller.update_config(new_config)
        return ActionResponse(
            success=True,
            message="Configuration updated — process restarted",
            details={
                "process": ps.model_dump(mode="json"),
                "changed_fields": changed,
                "restarted": True,
            },
        )

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
    summary="Kill the Ollama process and clear state",
    dependencies=[Depends(verify_api_key)],
)
async def destroy_ollama(request: Request) -> ActionResponse:
    manager = request.app.state.ollama_manager
    await manager.destroy()
    return ActionResponse(success=True, message="Ollama process destroyed")


@router.post(
    "/admin/models/pull",
    response_model=ActionResponse,
    summary="Pull (download) a model",
    dependencies=[Depends(verify_api_key)],
)
async def pull_model(request: Request, req: ModelActionRequest) -> ActionResponse:
    manager = request.app.state.ollama_manager
    ok = await manager.pull_model(req.model)
    if ok:
        return ActionResponse(success=True, message=f"Model '{req.model}' pulled")
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"Failed to pull model '{req.model}'",
    )


@router.post(
    "/admin/models/pull/stream",
    summary="Pull model with streaming progress (NDJSON)",
    dependencies=[Depends(verify_api_key)],
)
async def pull_model_stream(request: Request, req: ModelActionRequest) -> StreamingResponse:
    manager = request.app.state.ollama_manager

    async def _stream():
        async for chunk in manager.pull_model_streaming(req.model):
            yield json.dumps(chunk) + "\n"

    return StreamingResponse(_stream(), media_type="application/x-ndjson")


@router.post(
    "/admin/models/delete",
    response_model=ActionResponse,
    summary="Delete a model from disk",
    dependencies=[Depends(verify_api_key)],
)
async def delete_model(request: Request, req: ModelActionRequest) -> ActionResponse:
    manager = request.app.state.ollama_manager
    ok = await manager.delete_model(req.model)
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
    manager = request.app.state.ollama_manager
    ok = await manager.unload_model(req.model)
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
    manager = request.app.state.ollama_manager
    ok = await manager.preload_model(req.model)
    if ok:
        return ActionResponse(success=True, message=f"Model '{req.model}' preloaded")
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"Failed to preload model '{req.model}'",
    )


@router.post(
    "/admin/models/create",
    response_model=ActionResponse,
    summary="Create a model variant from a Modelfile",
    dependencies=[Depends(verify_api_key)],
)
async def create_model(request: Request, req: ModelCreateRequest) -> ActionResponse:
    manager = request.app.state.ollama_manager
    ok = await manager.create_model(req.name, req.modelfile)
    if ok:
        return ActionResponse(success=True, message=f"Model '{req.name}' created from Modelfile")
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"Failed to create model '{req.name}'",
    )


@router.post(
    "/admin/models/show",
    response_model=ModelInfoResponse,
    summary="Show detailed model information",
    dependencies=[Depends(verify_api_key)],
)
async def show_model(request: Request, req: ModelActionRequest) -> ModelInfoResponse:
    manager = request.app.state.ollama_manager
    info = await manager.show_model(req.model)
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


@router.post(
    "/admin/lanes/apply",
    response_model=LaneApplyResult,
    summary="Declarative: set desired lane configuration (diff + execute)",
    dependencies=[Depends(verify_api_key)],
)
async def apply_lanes(request: Request, req: LaneSetRequest) -> LaneApplyResult:
    lane_manager = request.app.state.lane_manager
    result = await lane_manager.apply_lanes(req.lanes)

    if result.success:
        save_lanes_config(req.lanes)

    return result


@router.get(
    "/admin/lanes/templates",
    response_model=dict[str, Any],
    summary="Get copy-paste lane templates for Ollama, vLLM, and mixed setups",
    dependencies=[Depends(verify_api_key)],
)
async def get_lane_templates() -> dict[str, Any]:
    """Return practical lane configuration templates for operators."""
    return {
        "notes": [
            "Use POST /admin/lanes/apply with one of these payloads.",
            "Lane IDs are derived from model names; duplicate models are rejected.",
            "For vLLM lanes, num_parallel is ignored (continuous batching).",
            "vLLM sleep control is available at POST /admin/lanes/{lane_id}/sleep and /wake when enable_sleep_mode=true.",
        ],
        "templates": {
            "single_ollama_lane": {
                "lanes": [
                    {
                        "model": "qwen2.5-coder:32b",
                        "backend": "ollama",
                        "num_parallel": 8,
                        "context_length": 4096,
                        "keep_alive": "10m",
                        "kv_cache_type": "q8_0",
                        "flash_attention": True,
                        "gpu_devices": "0,1",
                    }
                ]
            },
            "single_vllm_lane": {
                "lanes": [
                    {
                        "model": "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
                        "backend": "vllm",
                        "context_length": 4096,
                        "flash_attention": True,
                        "gpu_devices": "0,1",
                        "vllm": {
                            "vllm_binary": "vllm",
                            "tensor_parallel_size": 2,
                            "max_model_len": 4096,
                            "dtype": "float16",
                            "quantization": "",
                            "gpu_memory_utilization": 0.70,
                            "enforce_eager": True,
                            "enable_prefix_caching": True,
                            "disable_custom_all_reduce": False,
                            "disable_nccl_p2p": False,
                            "enable_sleep_mode": False,
                            "server_dev_mode": False,
                            "extra_args": [],
                        },
                    }
                ]
            },
            "mixed_lanes": {
                "lanes": [
                    {
                        "model": "qwen2.5-coder:32b",
                        "backend": "ollama",
                        "num_parallel": 8,
                        "context_length": 4096,
                        "keep_alive": "10m",
                        "kv_cache_type": "q8_0",
                        "flash_attention": True,
                        "gpu_devices": "0",
                    },
                    {
                        "model": "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
                        "backend": "vllm",
                        "context_length": 4096,
                        "flash_attention": True,
                        "gpu_devices": "1",
                        "vllm": {
                            "tensor_parallel_size": 1,
                            "gpu_memory_utilization": 0.70,
                            "enforce_eager": True,
                            "enable_prefix_caching": True,
                            "extra_args": [],
                        },
                    },
                ]
            },
        },
    }


@router.get(
    "/admin/lanes",
    response_model=list[LaneStatus],
    summary="Get status of all active lanes",
    dependencies=[Depends(verify_api_key)],
)
async def get_lanes(request: Request) -> list[LaneStatus]:
    lane_manager = request.app.state.lane_manager
    return await lane_manager.get_all_statuses()


@router.get(
    "/admin/lanes/events",
    response_model=list[LaneEvent],
    summary="Recent lane transition events",
    dependencies=[Depends(verify_api_key)],
)
async def get_lane_events(request: Request, limit: int = 100) -> list[LaneEvent]:
    lane_manager = request.app.state.lane_manager
    events = lane_manager.event_log
    if limit > 0:
        events = events[-limit:]
    return events


@router.get(
    "/admin/lanes/{lane_id}",
    response_model=LaneStatus,
    summary="Get status of a specific lane",
    dependencies=[Depends(verify_api_key)],
)
async def get_lane(request: Request, lane_id: str) -> LaneStatus:
    lane_manager = request.app.state.lane_manager
    try:
        return await lane_manager.get_lane_status(lane_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Lane '{lane_id}' not found")


@router.post(
    "/admin/lanes/{lane_id}/reconfigure",
    response_model=LaneStatus,
    summary="Reconfigure a single lane (partial update)",
    dependencies=[Depends(verify_api_key)],
)
async def reconfigure_lane(request: Request, lane_id: str, req: LaneReconfigureRequest) -> LaneStatus:
    lane_manager = request.app.state.lane_manager
    updates = req.model_dump(exclude_none=True)
    if not updates:
        try:
            return await lane_manager.get_lane_status(lane_id)
        except KeyError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Lane '{lane_id}' not found")
    try:
        return await lane_manager.reconfigure_lane(lane_id, updates)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Lane '{lane_id}' not found")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.post(
    "/admin/lanes/{lane_id}/sleep",
    response_model=LaneStatus,
    summary="Put a vLLM lane into sleep mode",
    dependencies=[Depends(verify_api_key)],
)
async def sleep_lane(request: Request, lane_id: str, req: LaneSleepRequest) -> LaneStatus:
    lane_manager = request.app.state.lane_manager
    try:
        return await lane_manager.sleep_lane(lane_id, level=req.level, mode=req.mode)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Lane '{lane_id}' not found")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.post(
    "/admin/lanes/{lane_id}/wake",
    response_model=LaneStatus,
    summary="Wake a sleeping vLLM lane",
    dependencies=[Depends(verify_api_key)],
)
async def wake_lane(request: Request, lane_id: str) -> LaneStatus:
    lane_manager = request.app.state.lane_manager
    try:
        return await lane_manager.wake_lane(lane_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Lane '{lane_id}' not found")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.delete(
    "/admin/lanes/{lane_id}",
    response_model=ActionResponse,
    summary="Remove a lane",
    dependencies=[Depends(verify_api_key)],
)
async def delete_lane(request: Request, lane_id: str) -> ActionResponse:
    lane_manager = request.app.state.lane_manager
    try:
        await lane_manager.remove_lane(lane_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Lane '{lane_id}' not found")
    return ActionResponse(success=True, message=f"Lane '{lane_id}' removed")
