"""Tests for the node-level health sensors (GPU + storage)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from logos_worker_node import node_health


def test_evaluate_node_health_returns_healthy_when_all_sensors_pass(tmp_path: Path, monkeypatch):
    """No GPU configured (no nvidia-smi) + a fresh tmp dir for HF cache
    is the dev-machine default. Must report healthy."""
    monkeypatch.setattr(
        node_health,
        "_STORAGE_PATHS_TO_PROBE",
        (tmp_path,),
    )
    with patch.object(
        subprocess,
        "check_output",
        side_effect=FileNotFoundError("nvidia-smi"),
    ):
        status = node_health.evaluate_node_health()

    assert status.healthy is True
    assert status.reason_code is None
    assert status.sensors["gpu"]["state"] == "ok"
    assert status.sensors["storage"]["state"] == "ok"


# CSV columns: index, mem.total, mem.used, mem.free, power.draw, fan.speed, temp.gpu
_HEALTHY_GPU_ROW = "{idx}, 81920, 12345, 70000, 150.5, 35, 55"


def test_evaluate_node_health_flags_gpu_error_field():
    """nvidia-smi reports [Error] for a memory field — must classify
    as gpu-error and overall healthy=False."""
    csv_output = (
        f"{_HEALTHY_GPU_ROW.format(idx=0)}\n"
        "1, [Error], [Error], [Error], [Error], [Error], [Error]\n"
        f"{_HEALTHY_GPU_ROW.format(idx=2)}\n"
    )
    with patch.object(subprocess, "check_output", return_value=csv_output):
        result = node_health._check_gpu()

    assert result.state == "gpu-error"
    assert "GPU1" in result.detail


def test_evaluate_node_health_flags_gpu_na_field():
    csv_output = "0, N/A, N/A, N/A, N/A, N/A, N/A\n" + _HEALTHY_GPU_ROW.format(idx=1) + "\n"
    with patch.object(subprocess, "check_output", return_value=csv_output):
        result = node_health._check_gpu()
    # 'N/A' alone (no 'Error' substring) triggers gpu-na, not gpu-error.
    assert result.state == "gpu-na"
    assert "GPU0" in result.detail


def test_evaluate_node_health_clean_gpu_csv_is_ok():
    csv_output = "\n".join(_HEALTHY_GPU_ROW.format(idx=i) for i in (0, 1)) + "\n"
    with patch.object(subprocess, "check_output", return_value=csv_output):
        result = node_health._check_gpu()
    assert result.state == "ok"


def test_evaluate_node_health_flags_err_token_on_power():
    """hochbruegge 2026-06-05: memory was readable, but Pwr/Fan flipped
    to 'ERR!'. CUDA context allocation then started returning
    cudaErrorDevicesUnavailable. Must classify as gpu-error so the
    watchdog kicks in."""
    csv_output = (
        f"{_HEALTHY_GPU_ROW.format(idx=0)}\n"
        # mem fields readable, but power.draw and fan.speed are ERR!
        "1, 81920, 12345, 70000, ERR!, ERR!, 40\n"
    )
    with patch.object(subprocess, "check_output", return_value=csv_output):
        result = node_health._check_gpu()
    assert result.state == "gpu-error"
    assert "GPU1.power" in result.detail or "GPU1.fan" in result.detail


def test_evaluate_node_health_na_on_telemetry_only_is_ok():
    """Some headless / fanless cards legitimately report [N/A] for fan
    speed or power draw. Don't flag the node as unhealthy on that
    alone — only memory N/A or any ERR!/Error token counts."""
    csv_output = (
        # mem readable, fan=[N/A] (passively cooled), power readable
        "0, 81920, 12345, 70000, 150.5, [N/A], 55\n"
    )
    with patch.object(subprocess, "check_output", return_value=csv_output):
        result = node_health._check_gpu()
    assert result.state == "ok"


def test_evaluate_node_health_storage_eio(tmp_path: Path, monkeypatch):
    """Regression for deioma 2026-06-04: HF cache directory returns EIO
    on listdir → must classify as filesystem-eio."""
    target = tmp_path / "hf_cache"
    target.mkdir()
    monkeypatch.setattr(node_health, "_STORAGE_PATHS_TO_PROBE", (target,))

    def _raise_eio(_path):
        raise OSError(5, "Input/output error", str(target))

    with patch("os.listdir", side_effect=_raise_eio):
        result = node_health._check_storage()
    assert result.state == "filesystem-eio"
    assert "EIO" in result.detail


def test_evaluate_node_health_storage_readonly(tmp_path: Path, monkeypatch):
    target = tmp_path / "hf_cache"
    target.mkdir()
    monkeypatch.setattr(node_health, "_STORAGE_PATHS_TO_PROBE", (target,))

    def _raise_erofs(_path):
        raise OSError(30, "Read-only file system", str(target))

    with patch("os.listdir", side_effect=_raise_erofs):
        result = node_health._check_storage()
    assert result.state == "filesystem-readonly"


def test_evaluate_node_health_storage_missing_path_is_ok(tmp_path: Path, monkeypatch):
    """A worker without any HF cache path configured is healthy — not unhealthy."""
    monkeypatch.setattr(
        node_health,
        "_STORAGE_PATHS_TO_PROBE",
        (tmp_path / "definitely-does-not-exist",),
    )
    result = node_health._check_storage()
    assert result.state == "ok"
    assert "no HF cache path configured" in result.detail


def test_evaluate_node_health_aggregates_first_failing_sensor(tmp_path: Path, monkeypatch):
    """When multiple sensors fail, NodeHealthStatus.reason_code reflects
    the first one (deterministic — GPU is registered before storage)."""
    target = tmp_path / "hf_cache"
    target.mkdir()
    monkeypatch.setattr(node_health, "_STORAGE_PATHS_TO_PROBE", (target,))

    def _eio(_path):
        raise OSError(5, "Input/output error")

    csv_output = "0, [Error], [Error], [Error], [Error], [Error], [Error]\n"
    with patch.object(subprocess, "check_output", return_value=csv_output), patch("os.listdir", side_effect=_eio):
        status = node_health.evaluate_node_health()

    assert status.healthy is False
    # GPU is the first sensor in _SENSORS, so its reason wins.
    assert status.reason_code == "gpu-error"
    assert status.sensors["gpu"]["state"] == "gpu-error"
    assert status.sensors["storage"]["state"] == "filesystem-eio"


def test_evaluate_node_health_handles_nvidia_smi_timeout():
    with patch.object(
        subprocess,
        "check_output",
        side_effect=subprocess.TimeoutExpired(cmd=["nvidia-smi"], timeout=10),
    ):
        result = node_health._check_gpu()
    assert result.state == "gpu-query-timeout"


def test_evaluate_node_health_sensor_exception_is_caught(tmp_path: Path, monkeypatch):
    """A sensor that throws unexpectedly must not crash the heartbeat —
    it gets surfaced as 'sensor-error' and the node is flagged unhealthy."""
    monkeypatch.setattr(node_health, "_STORAGE_PATHS_TO_PROBE", (tmp_path,))

    def _boom() -> node_health.SensorResult:
        raise RuntimeError("synthetic")

    monkeypatch.setattr(node_health, "_SENSORS", (("synthetic", _boom),))
    status = node_health.evaluate_node_health()
    assert status.healthy is False
    assert status.sensors["synthetic"]["state"] == "sensor-error"
    assert "synthetic" in status.sensors["synthetic"]["detail"]
