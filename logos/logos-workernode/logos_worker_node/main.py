"""FastAPI application entry point for LogosWorkerNode."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from logos_worker_node.config import load_config, get_state_dir
from logos_worker_node.gpu import GpuMetricsCollector
from logos_worker_node.lane_manager import LaneManager
from logos_worker_node.logos_bridge import LogosBridgeClient
from logos_worker_node.model_profiles import ModelProfileRegistry
from logos_worker_node.model_cache import create_model_cache
from logos_worker_node.runtime import SERVICE_VERSION
from logos_worker_node.calibration import auto_calibrate_models

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("logos_worker_node")

_LANE_MANAGER_SHUTDOWN_TIMEOUT = 90


async def _auto_calibrate_if_needed(
    cfg: "AppConfig",
    model_profiles: ModelProfileRegistry,
    state_dir: "Path",
    model_cache: Any | None = None,
) -> None:
    """Check for uncalibrated capabilities models and calibrate them on startup."""
    if os.getenv("LOGOS_SKIP_AUTO_CALIBRATION", "").strip().lower() in ("1", "true", "yes"):
        logger.info("Auto-calibration disabled via LOGOS_SKIP_AUTO_CALIBRATION")
        return

    caps = cfg.logos.capabilities_models if cfg.logos else []
    if not caps:
        return

    uncalibrated = []
    for model_name in caps:
        profile = model_profiles.get_profile(model_name)
        reason = None
        if profile is None:
            reason = "no profile"
        elif profile.base_residency_mb is None:
            reason = "base_residency_mb is null"
        elif profile.sleeping_residual_mb is None:
            reason = "sleeping_residual_mb is null"
        elif (
            profile.residency_source == "calibrated"
            and profile.loaded_vram_mb is not None
            and abs(profile.base_residency_mb - profile.loaded_vram_mb) > 1.0
        ):
            # Old-format calibrated profile: base_residency was stored as
            # weights-only. New format stores full loaded VRAM. Force recalibration.
            # Note: "measured" profiles intentionally differ (base=weights-only,
            # loaded=weights+KV) and must NOT be flagged as stale.
            reason = f"stale format (base={profile.base_residency_mb:.0f} != loaded={profile.loaded_vram_mb:.0f})"
        if reason:
            logger.info("  %s needs calibration: %s", model_name, reason)
            uncalibrated.append(model_name)

    if not uncalibrated:
        logger.info(
            "All %d capabilities models already calibrated \u2014 skipping calibration",
            len(caps),
        )
        return

    logger.info(
        "%d of %d capabilities models need calibration: %s. Starting auto-calibration...",
        len(uncalibrated), len(caps), uncalibrated,
    )

    # Resolve config.yml path (same logic as config.py)
    config_path_str = os.environ.get("LOGOS_WORKER_NODE_CONFIG", "").strip()
    if config_path_str:
        config_path = Path(config_path_str)
    else:
        for candidate in [Path("/app/config.yml"), Path("config.yml")]:
            if candidate.resolve().is_file():
                config_path = candidate
                break
        else:
            config_path = Path("config.yml")

    t0 = time.perf_counter()

    # Run synchronous calibration in a thread to avoid blocking the event loop
    nccl_p2p = cfg.engines.vllm.nccl_p2p_available if cfg.engines else False
    _mc = model_cache if (model_cache is not None and getattr(model_cache, "enabled", False)) else None
    results = await asyncio.to_thread(
        auto_calibrate_models,
        uncalibrated,
        config_path,
        state_dir,
        nccl_p2p_available=nccl_p2p,
        model_cache=_mc,
    )

    elapsed = time.perf_counter() - t0

    ok = [r for r in results.values() if r.success]
    fail = [r for r in results.values() if not r.success]

    for r in ok:
        logger.info(
            "Calibrated %s \u2014 base_residency=%.0f MB \u2014 done in calibration batch",
            r.model, r.base_residency_mb,
        )

    if fail:
        for r in fail:
            logger.warning(
                "Calibration failed for %s: %s (model will have no placement data)",
                r.model, r.error,
            )

    logger.info(
        "Auto-calibration complete (%d/%d succeeded) in %.1fs. Proceeding to normal startup.",
        len(ok), len(ok) + len(fail), elapsed,
    )

    # Reload persisted profiles into the registry so newly calibrated
    # values are available for lane placement
    if ok:
        model_profiles._load_persisted()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        cfg = load_config()
    except Exception:
        logger.exception("Failed to load configuration")
        sys.exit(1)

    gpu_collector = GpuMetricsCollector(poll_interval=cfg.worker.gpu_poll_interval)
    await gpu_collector.start()

    # Pre-warm FlashInfer JIT kernels (single-process, sequential) so that
    # subsequent vLLM launches — including TP>1 — find cached .so files and
    # skip JIT, avoiding the multi-process compilation race that crashes GPUs.
    try:
        from logos_worker_node.flashinfer_warmup import warmup as flashinfer_warmup
        cache_dir = os.path.join(cfg.engines.ollama.models_path, ".cache", "flashinfer")
        capability_models = list(cfg.logos.capabilities_models) if cfg.logos else []
        warmup_ok = flashinfer_warmup(cache_dir, model_names=capability_models)
        if not warmup_ok:
            forced_backend = (os.environ.get("LOGOS_VLLM_AUTO_ATTENTION_BACKEND") or "").strip()
            if not forced_backend:
                os.environ["LOGOS_VLLM_AUTO_ATTENTION_BACKEND"] = "TRITON_ATTN"
                logger.warning(
                    "FlashInfer pre-warmup failed; forcing TRITON_ATTN for subsequent vLLM launches in this worker"
                )
            else:
                logger.warning(
                    "FlashInfer pre-warmup failed; keeping configured attention backend override %s",
                    forced_backend,
                )
    except Exception:
        logger.warning("FlashInfer pre-warmup failed; vLLM will JIT-compile on first launch", exc_info=True)

    model_profiles = ModelProfileRegistry(
        state_dir=get_state_dir(),
        model_profile_overrides=cfg.model_profile_overrides,
    )

    # ── tmpfs RAM cache (created before calibration so models can be loaded
    # from RAM during VRAM measurement, then evicted to free space) ──────────
    hf_home = os.environ.get("HF_HOME", os.path.join(cfg.engines.ollama.models_path, ".hf_cache"))
    model_cache = create_model_cache(
        tmpfs_path=os.environ.get("LOGOS_TMPFS_CACHE_PATH", "").strip() or None,
        hf_home=hf_home,
    )

    await _auto_calibrate_if_needed(cfg, model_profiles, get_state_dir(), model_cache=model_cache)

    if model_cache.enabled:
        caps = list(cfg.logos.capabilities_models) if cfg.logos else []
        if caps:
            # Priority: models with calibration profiles first, then smallest first
            def _sort_key(m: str) -> tuple[int, int]:
                p = model_profiles.get_profile(m)
                has_profile = int(p is not None and (p.base_residency_mb or 0) > 0)
                size = model_cache.model_size_bytes(m)
                return (-has_profile, size)

            # Only pre-populate RAM cache for models with a valid calibration profile.
            # Uncalibrated models (base_residency_mb absent/0) will be excluded from
            # capabilities anyway, so caching them wastes precious tmpfs space.
            def _has_valid_profile(m: str) -> bool:
                p = model_profiles.get_profile(m)
                return p is not None and (p.base_residency_mb or 0) > 0

            caps_to_cache = sorted([m for m in caps if _has_valid_profile(m)], key=_sort_key)
            caps_skipped = [m for m in caps if not _has_valid_profile(m)]
            if caps_skipped:
                logger.info(
                    "Skipping RAM cache for %d uncalibrated model(s) (no profile data — "
                    "will not be served): %s",
                    len(caps_skipped), caps_skipped,
                )
            if caps_to_cache:
                logger.info(
                    "Pre-populating RAM cache with %d calibrated model(s): %s",
                    len(caps_to_cache), caps_to_cache,
                )
                effective_paths = await model_cache.cache_models_by_priority(caps_to_cache)
                for m, p in effective_paths.items():
                    if p == str(model_cache._cache_hub.parent):
                        logger.info("  %s → tmpfs RAM cache", m)
                    else:
                        logger.info("  %s → source filesystem (RAM cache full or model not found)", m)
            else:
                logger.info("No calibrated models to pre-populate into RAM cache")

    lane_manager = LaneManager(
        global_config=cfg.engines.ollama,
        vllm_engine_config=cfg.engines.vllm,
        lane_port_start=cfg.worker.lane_port_start,
        lane_port_end=cfg.worker.lane_port_end,
        nvidia_smi_available=lambda: gpu_collector.available,
        model_profiles=model_profiles,
        gpu_device_count=lambda: gpu_collector.device_count,
        per_gpu_vram_mb=lambda: gpu_collector.per_gpu_vram_mb,
        gpu_snapshot=gpu_collector.get_snapshot,
        gpu_force_poll=gpu_collector.force_poll,
        max_lanes=cfg.worker.max_lanes,
        model_cache=model_cache,
    )

    # Validate capabilities models at startup (warnings only)
    if cfg.logos and cfg.logos.capabilities_models:
        lane_manager.validate_capabilities(cfg.logos.capabilities_models)

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
            # Merge inline overrides from capabilities_models entries before seeding
            if cfg.logos and cfg.logos.capabilities_overrides:
                model_profiles.add_overrides(cfg.logos.capabilities_overrides)
            model_profiles.seed_capabilities(caps, engine="vllm")
            ready_caps: list[str] = []
            for cap_model in caps:
                p = model_profiles.get_profile(cap_model)
                if p:
                    src = p.residency_source or "unknown"
                    has_profile = (p.base_residency_mb or 0) > 0
                    if has_profile:
                        src_icon = {
                            "calibrated": "\033[32m●\033[0m",  # green  — calibrated
                            "measured": "\033[32m●\033[0m",    # green  — observed
                            "override": "\033[36m●\033[0m",    # cyan   — manual
                        }.get(src, "\033[33m●\033[0m")          # yellow — other
                        label = src.upper()
                        ready_caps.append(cap_model)
                    else:
                        src_icon = "\033[31m●\033[0m"           # red    — no data
                        label = "UNCALIBRATED"
                    logger.info(
                        "  %s %s [%s]: base_residency=%.0f MB | "
                        "disk=%.1f GB | kv_per_token=%s B | max_ctx=%s | engine=%s",
                        src_icon, cap_model, label,
                        p.base_residency_mb or 0,
                        (p.disk_size_bytes or 0) / (1024**3),
                        p.kv_per_token_bytes,
                        p.max_context_length,
                        p.engine,
                    )

            # Only advertise models with actual profile data to the server
            if len(ready_caps) < len(caps):
                skipped = set(caps) - set(ready_caps)
                logger.warning(
                    "Excluding %d uncalibrated model(s) from capabilities: %s",
                    len(skipped), sorted(skipped),
                )
                cfg.logos.capabilities_models = ready_caps

    app.state.config = cfg
    app.state.gpu_collector = gpu_collector
    app.state.lane_manager = lane_manager
    app.state.model_profiles = model_profiles
    app.state.model_cache = model_cache
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
