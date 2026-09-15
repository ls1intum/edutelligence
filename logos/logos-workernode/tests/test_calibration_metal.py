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

from logos_worker_node.calibration_metal import (
    _build_metal_calibration_cmd,
    _build_metal_calibration_env,
    _log_working_set_budget,
    calibrate_model_metal,
)
from logos_worker_node.models import MetalConfig

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


def test_build_cmd_enables_prefix_caching_by_default():
    """Matches the CUDA calibration path's own default (calibration.py):
    this changes vLLM's KV-cache accounting, so probing without it
    measures a different process than the production lane runs."""
    cmd = _build_metal_calibration_cmd({"model": "org/model"}, "vllm", "127.0.0.1", 11499)
    assert "--enable-prefix-caching" in cmd


def test_build_cmd_respects_explicit_prefix_caching_disable():
    cmd = _build_metal_calibration_cmd(
        {"model": "org/model", "enable_prefix_caching": False}, "vllm", "127.0.0.1", 11499
    )
    assert "--enable-prefix-caching" not in cmd


def test_build_cmd_forwards_max_num_seqs():
    cmd = _build_metal_calibration_cmd({"model": "org/model", "max_num_seqs": 64}, "vllm", "127.0.0.1", 11499)
    idx = cmd.index("--max-num-seqs")
    assert cmd[idx + 1] == "64"


# ═══════════════════════════════════════════════════════════════════════
# _build_metal_calibration_env
# ═══════════════════════════════════════════════════════════════════════


def test_build_env_strips_stale_cuda_vars(monkeypatch):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,1")
    monkeypatch.setenv("NCCL_P2P_DISABLE", "1")
    env = _build_metal_calibration_env(["/fake/vllm-metal/bin/vllm"], None)
    assert "CUDA_VISIBLE_DEVICES" not in env
    assert "NCCL_P2P_DISABLE" not in env


def test_build_env_forwards_worker_metal_tuning_knobs():
    """A node-wide VLLM_METAL_MEMORY_FRACTION shapes every production
    lane's footprint — the probe measures a different process without it."""
    mc = MetalConfig(memory_fraction=0.7, use_paged_attention=False, multimodal_mode="text-only-compat")
    env = _build_metal_calibration_env(["/fake/vllm-metal/bin/vllm"], mc)
    assert env["VLLM_METAL_MEMORY_FRACTION"] == "0.7"
    assert env["VLLM_METAL_USE_PAGED_ATTENTION"] == "0"
    assert env["VLLM_METAL_MULTIMODAL_MODE"] == "text-only-compat"


def test_build_env_prepends_resolved_binary_dir_to_path():
    env = _build_metal_calibration_env(["/fake/vllm-metal/bin/vllm"], None)
    assert env["PATH"].split(":")[0] == "/fake/vllm-metal/bin"


# ═══════════════════════════════════════════════════════════════════════
# _log_working_set_budget
# ═══════════════════════════════════════════════════════════════════════


def test_log_working_set_budget_logs_when_probe_answers(caplog):
    info = {"max_recommended_working_set_size": 30_000_000_000, "device_name": "M3 Pro"}
    with patch("logos_worker_node.calibration_metal.probe_device_info", return_value=info):
        with caplog.at_level("INFO"):
            _log_working_set_budget("org/model")
    assert any("working-set budget" in r.message for r in caplog.records)


def test_log_working_set_budget_is_silent_when_probe_unavailable(caplog):
    with patch("logos_worker_node.calibration_metal.probe_device_info", return_value=None):
        with caplog.at_level("INFO"):
            _log_working_set_budget("org/model")  # must not raise
    assert not any("working-set budget" in r.message for r in caplog.records)


# ═══════════════════════════════════════════════════════════════════════
# calibrate_model_metal
# ═══════════════════════════════════════════════════════════════════════


def _patch_metal_infra(*, wired_memory_sequence, wait_ready_side_effect=None, warmup_ok=True):
    mock_proc = MagicMock()
    mock_proc.pid = 4242
    mock_proc.poll.return_value = None
    patches = {
        "resolve_binary": patch(
            "logos_worker_node.calibration_metal.resolve_metal_vllm_binary",
            return_value="/fake/vllm-metal/bin/vllm",
        ),
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
        "device_info": patch(
            "logos_worker_node.calibration_metal.probe_device_info",
            return_value=None,
        ),
        "read_mem": patch(
            "logos_worker_node.calibration_metal.read_wired_memory_mb",
            side_effect=wired_memory_sequence,
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


def test_success_measures_wired_delta_between_baseline_and_loaded():
    patches, mock_proc = _patch_metal_infra(wired_memory_sequence=[4000.0, 11500.0])
    result, mocks = _run({"model": "org/model"}, patches)

    assert result.success
    assert result.base_residency_mb == pytest.approx(7500.0)
    assert result.loaded_vram_mb == pytest.approx(7500.0)
    assert result.tensor_parallel_size == 1
    assert result.min_kv_cache_mb == 0.0
    assert result.max_kv_cache_mb == 0.0
    mocks["stop"].assert_called_once()


def test_forces_tp1_even_if_plan_configured_tp_greater_than_one(caplog):
    patches, _ = _patch_metal_infra(wired_memory_sequence=[4000.0, 9000.0])
    result, _mocks = _run({"model": "org/model", "tensor_parallel_size": 2}, patches)

    assert result.success
    assert result.tensor_parallel_size == 1


def test_fails_cleanly_when_baseline_memory_read_fails():
    patches, _ = _patch_metal_infra(wired_memory_sequence=[None])
    result, mocks = _run({"model": "org/model"}, patches)

    assert not result.success
    assert "vm_stat" in result.error or "wired-memory" in result.error
    mocks["spawn"].assert_not_called()


def test_fails_when_wait_ready_raises():
    patches, _ = _patch_metal_infra(
        wired_memory_sequence=[4000.0],
        wait_ready_side_effect=RuntimeError("vLLM exited (code=1)"),
    )
    result, mocks = _run({"model": "org/model"}, patches)

    assert not result.success
    assert "exited" in result.error
    mocks["stop"].assert_called_once()


def test_cancelled_before_spawn_short_circuits():
    cancel_event = threading.Event()
    cancel_event.set()
    patches, _ = _patch_metal_infra(wired_memory_sequence=[4000.0])
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
    """An unclassified/generative model's warmup that never serves still
    yields a load-only measurement; see
    test_pooling_warmup_failure_fails_calibration for the classes that
    have a real, gating probe instead."""
    patches, _ = _patch_metal_infra(wired_memory_sequence=[4000.0, 9500.0], warmup_ok=False)
    result, _mocks = _run({"model": "org/model"}, patches)

    assert result.success
    assert result.base_residency_mb == pytest.approx(5500.0)


def test_pooling_warmup_failure_fails_calibration():
    """A classified pooling/transcription model has a real probe — a
    failure means the model itself doesn't serve one request on its own
    endpoint, and must not persist a footprint measured before the real
    request's lazy allocations."""
    patches, mocks_ref = _patch_metal_infra(wired_memory_sequence=[4000.0], warmup_ok=False)
    result, mocks = _run({"model": "org/embedding-model", "model_kind": "pooling"}, patches)

    assert not result.success
    assert "pooling" in result.error
    mocks["warmup"].assert_called_once()
    assert mocks["warmup"].call_args.kwargs.get("model_kind") == "pooling"


def test_model_kind_defaults_to_generative_and_is_forwarded_to_warmup():
    patches, _ = _patch_metal_infra(wired_memory_sequence=[4000.0, 9000.0])
    _result, mocks = _run({"model": "org/model"}, patches)

    assert mocks["warmup"].call_args.kwargs.get("model_kind") == "generative"


def test_detected_model_kind_is_forwarded_to_warmup():
    """The HF-precheck's auto-classification (plan[_detected_model_kind])
    is used when no operator override (plan[model_kind]) is present."""
    patches, _ = _patch_metal_infra(wired_memory_sequence=[4000.0, 9000.0])
    _result, mocks = _run({"model": "org/model", "_detected_model_kind": "transcription"}, patches)

    assert mocks["warmup"].call_args.kwargs.get("model_kind") == "transcription"


def test_fails_cleanly_when_vllm_binary_cannot_be_resolved():
    """No vllm-metal venv, no worker override, no explicit path: must fail
    with a clear reason instead of a bare FileNotFoundError from Popen."""
    patches, _ = _patch_metal_infra(wired_memory_sequence=[4000.0])
    patches["resolve_binary"] = patch(
        "logos_worker_node.calibration_metal.resolve_metal_vllm_binary", return_value=None
    )
    result, mocks = _run({"model": "org/model"}, patches)

    assert not result.success
    assert "vllm binary not found" in result.error
    mocks["spawn"].assert_not_called()
