"""Tests for the Metal (Apple Silicon) calibration probe.

No real vLLM/mlx process is ever spawned here — spawn, readiness, warmup
and memory reads are all mocked, matching the style of the CUDA
calibration tests in test_calibration.py.
"""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from logos_worker_node.calibration_metal import _build_metal_calibration_cmd, calibrate_model_metal

# ═══════════════════════════════════════════════════════════════════════
# _build_metal_calibration_cmd
# ═══════════════════════════════════════════════════════════════════════


def test_build_cmd_basic_flags():
    cmd = _build_metal_calibration_cmd({"model": "org/model"}, "vllm", "127.0.0.1", 11499)
    assert cmd[:3] == ["vllm", "serve", "org/model"]
    assert "--host" in cmd and "127.0.0.1" in cmd
    assert "--port" in cmd and "11499" in cmd
    assert "--max-model-len" in cmd and "auto" in cmd
    # No CUDA-only or KV-sweep flags — they do not exist on vllm-metal.
    assert "--kv-cache-memory-bytes" not in cmd
    assert "--tensor-parallel-size" not in cmd
    assert "--enable-sleep-mode" not in cmd


def test_build_cmd_omits_gpu_memory_utilization_by_default():
    """No explicit fraction unless the plan pins one — lets vllm-metal
    self-size against VLLM_METAL_MEMORY_FRACTION / the real working set."""
    cmd = _build_metal_calibration_cmd({"model": "org/model"}, "vllm", "127.0.0.1", 11499)
    assert "--gpu-memory-utilization" not in cmd


def test_build_cmd_forwards_explicit_gpu_memory_utilization():
    cmd = _build_metal_calibration_cmd(
        {"model": "org/model", "gpu_memory_utilization": 0.85},
        "vllm",
        "127.0.0.1",
        11499,
    )
    idx = cmd.index("--gpu-memory-utilization")
    assert cmd[idx + 1] == "0.85"


def test_build_cmd_forwards_quantization_and_enforce_eager():
    cmd = _build_metal_calibration_cmd(
        {"model": "org/model", "quantization": "awq", "enforce_eager": True},
        "vllm",
        "127.0.0.1",
        11499,
    )
    assert "--quantization" in cmd and "awq" in cmd
    assert "--enforce-eager" in cmd


def test_build_cmd_forwards_extra_args():
    cmd = _build_metal_calibration_cmd(
        {"model": "org/model", "extra_args": ["--trust-remote-code"]},
        "vllm",
        "127.0.0.1",
        11499,
    )
    assert "--trust-remote-code" in cmd


# ═══════════════════════════════════════════════════════════════════════
# calibrate_model_metal
# ═══════════════════════════════════════════════════════════════════════


def _patch_metal_infra(*, host_memory_sequence, wait_ready_side_effect=None, warmup_ok=True):
    mock_proc = MagicMock()
    mock_proc.pid = 4242
    mock_proc.poll.return_value = None
    patches = {
        "spawn": patch(
            "logos_worker_node.calibration_metal._spawn_vllm_metal",
            return_value=mock_proc,
        ),
        "wait_ready": patch(
            "logos_worker_node.calibration_metal.wait_ready",
            side_effect=wait_ready_side_effect,
        ),
        "warmup": patch(
            "logos_worker_node.calibration_metal.warmup_inference",
            return_value=warmup_ok,
        ),
        "stop": patch("logos_worker_node.calibration_metal.stop_vllm"),
        "sleep": patch("logos_worker_node.calibration_metal.time.sleep"),
        "read_mem": patch(
            "logos_worker_node.calibration_metal.read_host_memory_mb",
            side_effect=host_memory_sequence,
        ),
    }
    return patches, mock_proc


def _run(plan, patches):
    managers = {k: p.__enter__() for k, p in patches.items()}
    try:
        result = calibrate_model_metal(
            plan,
            vllm_binary="vllm",
            port=11499,
            log_dir=Path("/tmp/test-metal-calibration-logs"),
            ready_timeout_s=60.0,
        )
    finally:
        for p in patches.values():
            p.__exit__(None, None, None)
    return result, managers


def test_success_measures_delta_between_baseline_and_loaded():
    # (total, used, available) tuples: baseline then post-load.
    patches, mock_proc = _patch_metal_infra(
        host_memory_sequence=[
            (32768.0, 4000.0, 28768.0),
            (32768.0, 11500.0, 21268.0),
        ],
    )
    result, mocks = _run({"model": "org/model"}, patches)

    assert result.success
    assert result.base_residency_mb == pytest.approx(7500.0)
    assert result.loaded_vram_mb == pytest.approx(7500.0)
    assert result.tensor_parallel_size == 1
    assert result.min_kv_cache_mb == 0.0
    assert result.max_kv_cache_mb == 0.0
    mocks["stop"].assert_called_once()


def test_forces_tp1_even_if_plan_configured_tp_greater_than_one(caplog):
    patches, _ = _patch_metal_infra(
        host_memory_sequence=[
            (32768.0, 4000.0, 28768.0),
            (32768.0, 9000.0, 23768.0),
        ],
    )
    result, _mocks = _run({"model": "org/model", "tensor_parallel_size": 2}, patches)

    assert result.success
    assert result.tensor_parallel_size == 1


def test_fails_cleanly_when_baseline_memory_read_fails():
    patches, _ = _patch_metal_infra(host_memory_sequence=[None])
    result, mocks = _run({"model": "org/model"}, patches)

    assert not result.success
    assert "vm_stat" in result.error or "host-memory" in result.error
    mocks["spawn"].assert_not_called()


def test_fails_when_wait_ready_raises():
    patches, _ = _patch_metal_infra(
        host_memory_sequence=[(32768.0, 4000.0, 28768.0)],
        wait_ready_side_effect=RuntimeError("vLLM exited (code=1)"),
    )
    result, mocks = _run({"model": "org/model"}, patches)

    assert not result.success
    assert "exited" in result.error
    mocks["stop"].assert_called_once()


def test_cancelled_before_spawn_short_circuits():
    cancel_event = threading.Event()
    cancel_event.set()
    patches, _ = _patch_metal_infra(host_memory_sequence=[(32768.0, 4000.0, 28768.0)])
    managers = {k: p.__enter__() for k, p in patches.items()}
    try:
        result = calibrate_model_metal(
            {"model": "org/model"},
            vllm_binary="vllm",
            port=11499,
            log_dir=Path("/tmp/test-metal-calibration-logs"),
            ready_timeout_s=60.0,
            cancel_event=cancel_event,
        )
    finally:
        for p in patches.values():
            p.__exit__(None, None, None)

    assert not result.success
    assert result.error == "cancelled"
    managers["spawn"].assert_not_called()


def test_warmup_failure_does_not_fail_calibration():
    """A warmup that never serves still yields a load-only measurement —
    matches the CUDA path's own tolerance for a failed warmup."""
    patches, _ = _patch_metal_infra(
        host_memory_sequence=[
            (32768.0, 4000.0, 28768.0),
            (32768.0, 9500.0, 23268.0),
        ],
        warmup_ok=False,
    )
    result, _mocks = _run({"model": "org/model"}, patches)

    assert result.success
    assert result.base_residency_mb == pytest.approx(5500.0)
