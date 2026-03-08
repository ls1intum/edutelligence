"""
Node Controller — FastAPI application entry point.

Wires all components together: config, Docker manager, GPU collector,
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
from node_controller.ollama_manager import OllamaManager
from node_controller.ollama_status import OllamaStatusPoller

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
      2. Connect to Docker daemon
      3. Create/start the Ollama container (if configured)
      4. Start GPU metrics collector
      5. Start Ollama status poller
      6. Store all service instances in app.state

    Shutdown order: reverse (stop poller, stop GPU, close Docker).
    """

    # ---- 1. Config ----
    try:
        cfg = load_config()
    except Exception:
        logger.exception("Failed to load configuration")
        sys.exit(1)

    logger.info(
        "Config loaded — controller port=%d, Ollama image=%s, num_parallel=%d",
        cfg.controller.port,
        cfg.ollama.image,
        cfg.ollama.num_parallel,
    )

    # ---- 2. Docker ----
    manager = OllamaManager(
        network_name=cfg.docker.network_name,
        volume_name=cfg.docker.volume_name,
        models_host_path=cfg.docker.models_host_path,
    )
    try:
        await manager.init()
    except Exception:
        logger.exception("Failed to connect to Docker daemon")
        sys.exit(1)

    # ---- 3. Ollama container ----
    try:
        container_status = await manager.status(cfg.ollama.container_name)
        if container_status.state.value in ("not_found", "stopped"):
            logger.info("Creating/starting Ollama container…")
            await manager.create(cfg.ollama)
        elif container_status.state.value == "running":
            logger.info("Ollama container already running (id=%s)", container_status.container_id)
        else:
            logger.warning(
                "Ollama container in unexpected state '%s' — recreating",
                container_status.state.value,
            )
            await manager.recreate(cfg.ollama)
    except Exception:
        logger.exception("Failed to ensure Ollama container — continuing without it")

    # ---- 4. GPU collector ----
    gpu_collector = GpuMetricsCollector(poll_interval=cfg.controller.gpu_poll_interval)
    await gpu_collector.start()

    # ---- 5. Ollama status poller ----
    status_poller = OllamaStatusPoller(poll_interval=cfg.controller.ollama_poll_interval)
    await status_poller.start(cfg.ollama)

    # ---- 6. Store in app.state for route handlers ----
    app.state.ollama_manager = manager
    app.state.gpu_collector = gpu_collector
    app.state.status_poller = status_poller

    logger.info("Node Controller started — all systems ready")

    yield

    # ---- Shutdown ----
    logger.info("Shutting down…")
    await status_poller.stop()
    await gpu_collector.stop()

    # Stop and remove the spawned Ollama container so it doesn't hold
    # the Docker network open after the controller exits.
    try:
        await manager.destroy(cfg.ollama.container_name)
    except Exception:
        logger.warning("Could not remove Ollama container during shutdown", exc_info=True)

    await manager.close()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    app = FastAPI(
        title="Node Controller",
        description=(
            "Manages a single Ollama Docker container on a GPU node. "
            "Exposes nvidia-smi metrics, Ollama status, and admin controls to Logos."
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

    # Import and include routers (they are populated during lifespan)
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

    host = "0.0.0.0"
    port = cfg.controller.port

    ssl_kwargs = {}
    if cfg.controller.tls_enabled:
        from pathlib import Path

        cert = Path(cfg.controller.tls_cert_path)
        key = Path(cfg.controller.tls_key_path)
        if cert.exists() and key.exists():
            ssl_kwargs["ssl_certfile"] = str(cert)
            ssl_kwargs["ssl_keyfile"] = str(key)
            logger.info("TLS enabled (cert=%s)", cert)
        else:
            logger.warning("TLS enabled but cert/key not found — falling back to HTTP")

    logger.info("Starting Node Controller on %s:%d", host, port)
    uvicorn.run(
        "node_controller.main:app",
        host=host,
        port=port,
        log_level="info",
        **ssl_kwargs,
    )


if __name__ == "__main__":
    main()
