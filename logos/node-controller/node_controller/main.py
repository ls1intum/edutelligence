"""
Node Controller — FastAPI application entry point.

Wires all components together: config, Ollama process manager, GPU collector,
Ollama status poller, and API routers.  Manages the async lifespan
(startup/shutdown) of all background services.

Service instances are stored in ``app.state`` so that route handlers in
logos_api.py and admin_api.py can access them via ``request.app.state``.
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from node_controller.config import get_config, load_config
from node_controller.gpu import GpuMetricsCollector
from node_controller.lane_manager import LaneManager
from node_controller.ollama_manager import OllamaManager
from node_controller.ollama_status import OllamaStatusPoller
from node_controller.vram_budget import VramBudgetManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("node_controller")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Startup / shutdown lifecycle for the controller.

    Startup order:
      1. Load config
      2. Initialise Ollama process manager
      3. Spawn the Ollama process
      4. Start GPU metrics collector
      5. Start Ollama status poller
      6. Store all service instances in app.state

    Shutdown order: reverse (stop poller, stop GPU, kill Ollama process).
    """

    # ---- 1. Config ----
    try:
        cfg = load_config()
    except Exception:
        logger.exception("Failed to load configuration")
        sys.exit(1)

    logger.info(
        "Config loaded — controller port=%d, Ollama port=%d, num_parallel=%d",
        cfg.controller.port,
        cfg.ollama.port,
        cfg.ollama.num_parallel,
    )

    # ---- 2. Ollama process manager (legacy single-process mode) ----
    manager = OllamaManager()
    await manager.init()

    # ---- 3. Spawn Ollama process ----
    try:
        process_status = await manager.spawn(cfg.ollama)
        logger.info("Ollama process status: %s (pid=%s)", process_status.state.value, process_status.pid)
    except Exception:
        logger.exception("Failed to spawn Ollama process — continuing without it")

    # ---- 4. GPU collector ----
    gpu_collector = GpuMetricsCollector(poll_interval=cfg.controller.gpu_poll_interval)
    await gpu_collector.start()

    # ---- 5. Ollama status poller (for legacy single-process mode) ----
    status_poller = OllamaStatusPoller(poll_interval=cfg.controller.ollama_poll_interval)
    await status_poller.start(cfg.ollama)

    # ---- 6. Lane manager (multi-process mode) ----
    lane_manager = LaneManager(
        global_config=cfg.ollama,
        lane_port_start=cfg.controller.lane_port_start,
        lane_port_end=cfg.controller.lane_port_end,
        reserved_ports={cfg.ollama.port},
    )

    # Auto-apply lanes from config if present
    if cfg.lanes:
        logger.info("Applying %d lane(s) from config...", len(cfg.lanes))
        try:
            result = await lane_manager.apply_lanes(cfg.lanes)
            for action in result.actions:
                logger.info("  Lane '%s': %s (%s)", action.lane_id, action.action, action.details)
            if result.errors:
                for err in result.errors:
                    logger.error("  Lane error: %s", err)
        except Exception:
            logger.exception("Failed to apply lanes from config — continuing without lanes")

    # ---- 7. VRAM budget manager ----
    vram_budget = VramBudgetManager(gpu_collector)

    # ---- 8. Store in app.state for route handlers ----
    app.state.ollama_manager = manager
    app.state.gpu_collector = gpu_collector
    app.state.status_poller = status_poller
    app.state.lane_manager = lane_manager
    app.state.vram_budget = vram_budget

    logger.info("Node Controller started — all systems ready")

    yield

    # ---- Shutdown ----
    logger.info("Shutting down…")
    await status_poller.stop()
    await gpu_collector.stop()

    # Shutdown lanes
    try:
        await lane_manager.destroy_all()
    except Exception:
        logger.warning("Error shutting down lanes", exc_info=True)
    await lane_manager.close()

    try:
        await manager.destroy()
    except Exception:
        logger.warning("Could not stop Ollama process during shutdown", exc_info=True)

    await manager.close()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    app = FastAPI(
        title="Node Controller",
        description=(
            "Manages Ollama processes on a GPU node — single-process or multi-lane mode. "
            "Exposes nvidia-smi metrics, Ollama status, lane management, and admin controls to Logos."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from node_controller.admin_api import router as admin_router
    from node_controller.logos_api import router as logos_router

    app.include_router(logos_router)
    app.include_router(admin_router)

    @app.get("/", tags=["root"])
    async def root() -> dict:
        return {
            "service": "Node Controller",
            "version": "1.0.0",
            "docs": "/docs",
        }

    return app


app = create_app()


def main() -> None:
    """CLI entry point."""
    cfg = load_config()

    kwargs: dict = {
        "app": "node_controller.main:app",
        "host": "0.0.0.0",
        "port": cfg.controller.port,
        "log_level": "info",
    }

    if cfg.controller.tls_enabled:
        kwargs["ssl_certfile"] = cfg.controller.tls_cert_path
        kwargs["ssl_keyfile"] = cfg.controller.tls_key_path

    uvicorn.run(**kwargs)


if __name__ == "__main__":
    main()
