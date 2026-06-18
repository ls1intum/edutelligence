"""Tests for run-all orchestration helpers in benchmark_logos.py:

- workernode start must NOT pull images (no registry creds for root on the GPU
  nodes — a pull just fails and falls back to the local image).
- the calibration maintenance window is disabled/restored via LOGOS_CALIB_ENABLED
  by recreating only the orchestrator.
"""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Import the benchmark script by path (it's a standalone module, no package).
_BM_PATH = Path(__file__).resolve().parent.parent / "benchmark_logos.py"
_spec = importlib.util.spec_from_file_location("benchmark_logos_under_test", _BM_PATH)
bm = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = bm
_spec.loader.exec_module(bm)


def _capture_subprocess():
    """Return (calls, fake_run) where fake_run records argv and returns rc=0."""
    calls: list = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        result = MagicMock()
        result.returncode = 0
        return result

    return calls, fake_run


def _flatten(cmd) -> str:
    items = cmd if isinstance(cmd, (list, tuple)) else [cmd]
    return " ".join(str(x) for x in items)


def test_start_workernode_does_not_pull():
    calls, fake = _capture_subprocess()
    with patch.object(bm.subprocess, "run", side_effect=fake):
        bm._start_workernode_via_ssh(["gpu1.example"], "logos-server", None, "/opt/logos-workernode", use_sudo=True)
    assert calls, "subprocess.run was not called"
    joined = " ".join(_flatten(c) for c in calls)
    assert "docker compose up -d" in joined
    assert "docker compose pull" not in joined


def test_set_calibration_window_disable_local():
    calls, fake = _capture_subprocess()
    with patch.object(bm.subprocess, "run", side_effect=fake):
        bm._set_calibration_window_enabled("/opt/logos", enabled=False, use_sudo=True)
    cmd = calls[-1]
    assert cmd[0] == "bash" and cmd[1] == "-c"
    script = cmd[2]
    assert "LOGOS_CALIB_ENABLED=false" in script
    assert "--no-deps" in script and "--force-recreate logos-orchestrator" in script
    assert "/opt/logos/.env" in script


def test_set_calibration_window_enable_via_relay():
    calls, fake = _capture_subprocess()
    with patch.object(bm.subprocess, "run", side_effect=fake):
        bm._set_calibration_window_enabled(
            "/opt/logos",
            enabled=True,
            use_sudo=True,
            relay_host="logos-test",
            relay_user="me",
            ssh_key="/k",
        )
    cmd = calls[-1]
    assert cmd[0] == "ssh"
    assert "me@logos-test" in cmd and "/k" in cmd
    remote = cmd[-1]
    assert "LOGOS_CALIB_ENABLED=true" in remote
    assert "--force-recreate logos-orchestrator" in remote


def test_manage_calibration_window_flag_default_and_off():
    parser = bm._build_parser()
    on = parser.parse_args(["--run-all-scenarios", "--workload", "x.csv"])
    assert on.manage_calibration_window is True
    off = parser.parse_args(["--run-all-scenarios", "--workload", "x.csv", "--no-manage-calibration-window"])
    assert off.manage_calibration_window is False
