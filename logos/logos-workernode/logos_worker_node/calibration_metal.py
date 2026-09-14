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
    CalibrationResult,
    _reset_calibration_log,
    stop_vllm,
    wait_ready,
    warmup_inference,
)
from logos_worker_node.metal import read_host_memory_mb

logger = logging.getLogger(__name__)

_READY_POLL_SETTLE_S = 2.0  # let the allocator settle before the final read


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
    extra_args = plan.get("extra_args") or []
    cmd.extend(str(a) for a in extra_args)
    return cmd


def _spawn_vllm_metal(
    cmd: list[str],
    log_path: Path,
    *,
    hf_home: str | None = None,
) -> subprocess.Popen[str]:
    """Spawn the Metal calibration probe process.

    No CUDA_VISIBLE_DEVICES / NCCL env — those do not exist on this
    backend (see MetalVllmProcessHandle._build_process_env).
    """
    env = os.environ.copy()
    if hf_home:
        env["HF_HOME"] = hf_home

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


def calibrate_model_metal(
    plan: dict[str, Any],
    *,
    vllm_binary: str,
    port: int,
    log_dir: Path,
    ready_timeout_s: float,
    cancel_event: threading.Event | None = None,
) -> CalibrationResult:
    """Single-point calibration for a model served on the Metal backend.

    No TP escalation, no KV sweep, no sleep/wake — see the module
    docstring for why each is either impossible or unneeded here.
    """
    model = plan["model"]
    _reset_calibration_log(log_dir, model)
    host = "127.0.0.1"
    base_url = f"http://{host}:{port}"
    log_path = log_dir / f"{model.replace('/', '__')}.log"

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

    baseline = read_host_memory_mb()
    if baseline is None:
        result.error = "metal host-memory read failed (vm_stat/hw.memsize unavailable)"
        logger.warning("  ERROR: %s", result.error)
        return result
    _total_mb, baseline_used_mb, _avail_mb = baseline
    logger.info("        baseline used = %.0f MB", baseline_used_mb)

    cmd = _build_metal_calibration_cmd(plan, vllm_binary, host, port)
    result.probe_command = " ".join(cmd)
    proc = _spawn_vllm_metal(cmd, log_path)

    try:
        wait_ready(base_url, ready_timeout_s, proc, cancel_event=cancel_event)

        if cancel_event is not None and cancel_event.is_set():
            result.error = "cancelled"
            return result

        served = warmup_inference(base_url, model)
        if not served:
            logger.warning("  %s: warmup request did not complete — measuring load-only footprint", model)

        time.sleep(_READY_POLL_SETTLE_S)
        loaded = read_host_memory_mb()
        if loaded is None:
            result.error = "metal host-memory read failed after load"
            logger.warning("  ERROR: %s", result.error)
            return result
        _total_mb, loaded_used_mb, _avail_mb = loaded

        base_residency_mb = max(loaded_used_mb - baseline_used_mb, 0.0)
        logger.info(
            "  Results: base_residency_mb = %.0f MB (measured delta, weights + KV)",
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
