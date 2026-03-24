"""FastAPI application entry point for LogosWorkerNode."""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from logos_worker_node.config import load_config, get_config_path
from logos_worker_node.gpu import GpuMetricsCollector
from logos_worker_node.lane_manager import LaneManager
from logos_worker_node.logos_bridge import LogosBridgeClient
from logos_worker_node.model_profiles import ModelProfileRegistry
from logos_worker_node.runtime import SERVICE_VERSION

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("logos_worker_node")

_LANE_MANAGER_SHUTDOWN_TIMEOUT = 90

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        cfg = load_config()
    except Exception:
        logger.exception("Failed to load configuration")
        sys.exit(1)

    gpu_collector = GpuMetricsCollector(poll_interval=cfg.worker.gpu_poll_interval)
    await gpu_collector.start()

    model_profiles = ModelProfileRegistry(config_path=get_config_path())

    lane_manager = LaneManager(
        global_config=cfg.engines.ollama,
        lane_port_start=cfg.worker.lane_port_start,
        lane_port_end=cfg.worker.lane_port_end,
        nvidia_smi_available=lambda: gpu_collector.available,
        model_profiles=model_profiles,
        gpu_device_count=lambda: gpu_collector.device_count,
        per_gpu_vram_mb=lambda: gpu_collector.per_gpu_vram_mb,
        gpu_snapshot=gpu_collector.get_snapshot,
    )

    if cfg.lanes:
        logger.info("Applying %d lane(s) from config", len(cfg.lanes))
        try:
            result = await lane_manager.apply_lanes(cfg.lanes)
            if result.errors:
                raise RuntimeError("; ".join(result.errors))
        except Exception:
            logger.exception("Failed to apply lanes from config")
            await lane_manager.close()
            await gpu_collector.stop()
            raise
    else:
        caps = cfg.logos.capabilities_models if cfg.logos else []
        logger.info(
            "\033[1m\033[36m══ ZERO-LANE MODE ══\033[0m "
            "Waiting for server commands. Capabilities: %s",
            caps or "(none)",
        )
        if caps:
            model_profiles.seed_capabilities(caps, engine="vllm")
            for cap_model in caps:
                p = model_profiles.get_profile(cap_model)
                if p:
                    logger.info(
                        "  \033[32m✓\033[0m %s: engine=%s base_residency=%.0fMB "
                        "kv_per_token=%s max_ctx=%s disk=%.1fGB",
                        cap_model, p.engine,
                        p.base_residency_mb or 0,
                        p.kv_per_token_bytes,
                        p.max_context_length,
                        (p.disk_size_bytes or 0) / (1024**3),
                    )

    app.state.config = cfg
    app.state.gpu_collector = gpu_collector
    app.state.lane_manager = lane_manager
    app.state.model_profiles = model_profiles
    logos_bridge = LogosBridgeClient(app, cfg.logos)
    app.state.logos_bridge = logos_bridge
    await logos_bridge.start()

    logger.info("LogosWorkerNode started on port %d", cfg.worker.port)
    yield

    logger.info("Shutting down LogosWorkerNode")
    try:
        await logos_bridge.stop()
    except Exception:
        logger.warning("Error stopping Logos bridge", exc_info=True)
    try:
        await asyncio.wait_for(lane_manager.destroy_all(), timeout=_LANE_MANAGER_SHUTDOWN_TIMEOUT)
    except asyncio.TimeoutError:
        logger.error(
            "Timed out destroying lanes after %ss; continuing shutdown with best-effort cleanup",
            _LANE_MANAGER_SHUTDOWN_TIMEOUT,
        )
    except Exception:
        logger.warning("Error destroying lanes", exc_info=True)
    await lane_manager.close()
    await gpu_collector.stop()



def create_app() -> FastAPI:
    app = FastAPI(
        title="LogosWorkerNode",
        description="Lane-based local inference worker for Logos.",
        version=SERVICE_VERSION,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from logos_worker_node.admin_api import router as admin_router

    app.include_router(admin_router)

    @app.get("/", tags=["root"])
    async def root() -> dict[str, str]:
        return {
            "service": "LogosWorkerNode",
            "version": SERVICE_VERSION,
            "docs": "/docs",
        }

    return app


app = create_app()


def main() -> None:
    cfg = load_config()
    kwargs: dict[str, object] = {
        "app": "logos_worker_node.main:app",
        "host": "0.0.0.0",
        "port": cfg.worker.port,
        "log_level": "info",
    }
    if cfg.worker.tls_enabled:
        kwargs["ssl_certfile"] = cfg.worker.tls_cert_path
        kwargs["ssl_keyfile"] = cfg.worker.tls_key_path
    uvicorn.run(**kwargs)


if __name__ == "__main__":
    main()
