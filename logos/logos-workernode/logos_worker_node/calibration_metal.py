"""Calibration probe for the Metal backend (Apple Silicon).

No KV sweep: vllm-metal only has VLLM_METAL_MEMORY_FRACTION (weights+KV
together, no isolated KV flag). Measures one point: load, warm up, read
the memory delta. No TP (single GPU) or sleep (CUDA-only CuMemAllocator).
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from logos_worker_node.calibration import (
    _FATAL_PROBE_MODEL_KINDS,
    CalibrationResult,
    _reset_calibration_log,
    stop_vllm,
    wait_ready,
    warmup_inference,
)
from logos_worker_node.metal import probe_device_info, read_wired_memory_mb, resolve_metal_vllm_binary
from logos_worker_node.models import MetalConfig

logger = logging.getLogger(__name__)

_METAL_SETTLE_S = 2.0  # let the allocator settle before the final read

# Env vars a stale worker/CUDA environment could leak into the Metal
# subprocess — meaningless on this backend and confusing in a crash dump
# (mirrors MetalVllmProcessHandle._build_process_env).
_STALE_CUDA_ENV_KEYS = ("CUDA_VISIBLE_DEVICES", "CUDA_HOME", "LD_LIBRARY_PATH", "NCCL_P2P_DISABLE")


def _build_metal_calibration_cmd(
    plan: dict[str, Any],
    vllm_binary: str,
    host: str,
    port: int,
) -> list[str]:
    """Build a ``vllm serve`` command for a Metal calibration probe.

    Mirrors MetalVllmProcessHandle._build_cmd's flag set, off the plain
    plan dict the CUDA calibration path already uses (not a LaneConfig).
    """
    model = plan["model"]
    cmd = [
        vllm_binary,
        "serve",
        model,
        "--host",
        host,
        "--port",
        str(port),
        "--dtype",
        str(plan.get("dtype") or "auto"),
        "--max-model-len",
        "auto",
    ]
    quantization = plan.get("quantization")
    if quantization:
        cmd.extend(["--quantization", str(quantization)])
    # Deliberately NOT passed unless the operator pinned one: leaving this
    # out lets vllm-metal self-size against VLLM_METAL_MEMORY_FRACTION /
    # the real working set, matching what a production lane does when the
    # model has no explicit override either (metal_process.py:267-273).
    gpu_memory_utilization = plan.get("gpu_memory_utilization")
    if gpu_memory_utilization is not None:
        cmd.extend(["--gpu-memory-utilization", str(gpu_memory_utilization)])
    if plan.get("enforce_eager"):
        cmd.append("--enforce-eager")
    # Same reasoning as the CUDA calibration path (calibration.py): this
    # changes vLLM's KV-cache accounting, so probing without it measures
    # a different process than the production lane actually runs.
    if bool(plan.get("enable_prefix_caching", True)):
        cmd.append("--enable-prefix-caching")
    max_num_seqs = plan.get("max_num_seqs")
    if max_num_seqs:
        cmd.extend(["--max-num-seqs", str(int(max_num_seqs))])
    extra_args = plan.get("extra_args") or []
    cmd.extend(str(a) for a in extra_args)
    return cmd


def _build_metal_calibration_env(cmd: list[str], worker_metal_config: MetalConfig | None) -> dict[str, str]:
    """Environment for the Metal calibration probe.

    Mirrors MetalVllmProcessHandle._build_env / _build_process_env's Metal
    tuning knobs and stale-CUDA-var stripping — without them, a node-wide
    VLLM_METAL_MEMORY_FRACTION (or paged-attention / multimodal-mode)
    override that shapes every production lane's footprint would silently
    not apply to the probe, measuring a different process configuration.
    No HF_HOME override either: unlike the CUDA path, Metal calibration
    does not integrate with the tmpfs RAM model cache (out of scope, see
    module docstring), so it always loads from the plain HF cache.
    """
    env = os.environ.copy()
    for key in _STALE_CUDA_ENV_KEYS:
        env.pop(key, None)

    mc = worker_metal_config or MetalConfig()
    if mc.memory_fraction is not None:
        env["VLLM_METAL_MEMORY_FRACTION"] = str(mc.memory_fraction)
    if mc.use_paged_attention is not None:
        env["VLLM_METAL_USE_PAGED_ATTENTION"] = "1" if mc.use_paged_attention else "0"
    if mc.multimodal_mode:
        env["VLLM_METAL_MULTIMODAL_MODE"] = mc.multimodal_mode
    if mc.env_overrides:
        env.update(mc.env_overrides)

    # The resolved binary's own directory first, so vLLM resolves any
    # helper executable it shells out to from the vllm-metal venv rather
    # than whatever the worker's own environment happens to have on PATH.
    vllm_bin_dir = str(Path(cmd[0]).resolve().parent)
    current_path = env.get("PATH", "")
    env["PATH"] = vllm_bin_dir if not current_path else f"{vllm_bin_dir}{os.pathsep}{current_path}"
    return env


def _spawn_vllm_metal(
    cmd: list[str], log_path: Path, worker_metal_config: MetalConfig | None = None
) -> subprocess.Popen[str]:
    """Spawn the Metal calibration probe process."""
    env = _build_metal_calibration_env(cmd, worker_metal_config)

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("a", encoding="utf-8")
    try:
        _sep = "=" * 72
        log_file.write(
            f"\n{_sep}\n"
            f"  Metal calibration probe — {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"  Command: {' '.join(cmd)}\n"
            f"{_sep}\n\n"
        )
        log_file.flush()
        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
    finally:
        log_file.close()
    logger.info("  Spawned PID=%d  log=%s", proc.pid, log_path)
    logger.info("  Command: %s", " ".join(cmd))
    return proc


def _log_working_set_budget(model: str) -> None:
    """Log the GPU working-set ceiling for context, if the mlx probe answers.

    Informational only — never blocks or fails calibration if unreachable,
    it just tells an operator reading the log how close a measurement
    came to the working-set limit vllm-metal will actually enforce.
    """
    info = probe_device_info()
    if not info:
        return
    working_set = info.get("max_recommended_working_set_size")
    if not working_set:
        return
    logger.info(
        "  %s: GPU working-set budget = %.0f MB (%s)",
        model,
        float(working_set) / (1024.0 * 1024.0),
        info.get("device_name") or "Apple Silicon GPU",
    )


def calibrate_model_metal(
    plan: dict[str, Any],
    *,
    vllm_binary: str,
    port: int,
    log_dir: Path,
    ready_timeout_s: float,
    cancel_event: threading.Event | None = None,
    worker_metal_config: MetalConfig | None = None,
) -> CalibrationResult:
    """Single-point calibration for a model served on the Metal backend.

    No TP escalation, no KV sweep, no sleep/wake — see the module
    docstring for why each is either impossible or unneeded here.

    ``worker_metal_config`` is the node's ``engines.metal`` config — the
    same object production Metal lanes resolve their binary and
    ``VLLM_METAL_*`` environment from (``MetalVllmProcessHandle``). Without
    it the probe falls back to a bare ``vllm`` lookup, which fails outright
    (the worker's own venv deliberately excludes vllm/mlx) or, if it
    happens to resolve to something on PATH, measures a differently
    configured process than the lane it's meant to profile.
    """
    model = plan["model"]
    _reset_calibration_log(log_dir, model)
    host = "127.0.0.1"
    base_url = f"http://{host}:{port}"
    log_path = log_dir / f"{model.replace('/', '__')}.log"
    # "model_kind" is an operator override (engines.vllm.model_overrides);
    # "_detected_model_kind" is the HF-precheck's auto-classification
    # (logos_bridge.py) — both backend-independent.
    model_kind = str(plan.get("model_kind") or plan.get("_detected_model_kind") or "generative")

    if int(plan.get("tensor_parallel_size", 1)) > 1:
        logger.warning(
            "  %s configured with tensor_parallel_size>1, which the Metal "
            "backend does not support (single integrated GPU) — probing "
            "at tp=1 regardless",
            model,
        )

    result = CalibrationResult(
        model=model,
        tensor_parallel_size=1,
        gpu_devices="",
        kv_cache_sent_mb=0.0,
        success=False,
        enforce_eager=bool(plan.get("enforce_eager", False)),
    )

    if cancel_event is not None and cancel_event.is_set():
        result.error = "cancelled"
        return result

    _log_working_set_budget(model)

    baseline_used_mb = read_wired_memory_mb()
    if baseline_used_mb is None:
        result.error = "metal wired-memory read failed (vm_stat unavailable)"
        logger.warning("  ERROR: %s", result.error)
        return result
    logger.info("        baseline wired = %.0f MB", baseline_used_mb)

    resolved_binary = resolve_metal_vllm_binary(
        vllm_binary, worker_metal_config.vllm_binary if worker_metal_config else ""
    )
    if resolved_binary is None:
        result.error = (
            "vllm binary not found for Metal calibration — checked the "
            "configured/worker paths and the vllm-metal venv "
            "(LOGOS_METAL_VENV or ~/.venv-vllm-metal/bin/vllm)"
        )
        logger.warning("  ERROR: %s", result.error)
        return result

    cmd = _build_metal_calibration_cmd(plan, resolved_binary, host, port)
    result.probe_command = " ".join(cmd)
    proc = _spawn_vllm_metal(cmd, log_path, worker_metal_config)

    try:
        wait_ready(base_url, ready_timeout_s, proc, cancel_event=cancel_event)

        if cancel_event is not None and cancel_event.is_set():
            result.error = "cancelled"
            return result

        served = warmup_inference(base_url, model, model_kind=model_kind)
        if not served:
            if model_kind in _FATAL_PROBE_MODEL_KINDS:
                # A classified pooling/transcription model has a real,
                # working probe — a failure means the model itself
                # doesn't answer one request on its own endpoint, not a
                # missed /v1/completions mismatch. Must not persist a
                # footprint measured before the real request's lazy
                # allocations (e.g. an embedding model's pooling layer).
                result.error = (
                    f"functional probe failed ({model_kind}): {model} did not answer "
                    "one request on its own serving endpoint"
                )
                logger.warning("  ERROR: %s", result.error)
                return result
            logger.warning("  %s: warmup request did not complete — measuring load-only footprint", model)

        time.sleep(_METAL_SETTLE_S)
        loaded_used_mb = read_wired_memory_mb()
        if loaded_used_mb is None:
            result.error = "metal wired-memory read failed after load"
            logger.warning("  ERROR: %s", result.error)
            return result

        base_residency_mb = max(loaded_used_mb - baseline_used_mb, 0.0)
        logger.info(
            "  Results: base_residency_mb = %.0f MB (wired-memory delta, weights + KV)",
            base_residency_mb,
        )
        result.success = True
        result.loaded_vram_mb = base_residency_mb
        result.base_residency_mb = base_residency_mb
        result.calibrated_at = time.time()
        return result
    except (RuntimeError, TimeoutError) as exc:
        result.error = str(exc)
        logger.warning("  ERROR: %s", result.error)
        return result
    finally:
        stop_vllm(proc)
