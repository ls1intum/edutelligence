"""Tests for run-all orchestration helpers in benchmark_anontool.py:

- workernode start must NOT pull images (no registry creds for root on the GPU
  nodes — a pull just fails and falls back to the local image).
- the calibration maintenance window is disabled/restored via ANONTOOL_CALIB_ENABLED
  by recreating only the orchestrator.
"""

import asyncio
import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Import the benchmark script by path (it's a standalone module, no package).
_BM_PATH = Path(__file__).resolve().parent.parent / "benchmark_anontool.py"
_spec = importlib.util.spec_from_file_location("benchmark_anontool_under_test", _BM_PATH)
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
        bm._start_workernode_via_ssh(
            ["gpu1.example"], "anontool-server", None, "/opt/anontool-workernode", use_sudo=True
        )
    assert calls, "subprocess.run was not called"
    joined = " ".join(_flatten(c) for c in calls)
    assert "docker compose up -d" in joined
    assert "docker compose pull" not in joined


def test_set_calibration_window_disable_local():
    calls, fake = _capture_subprocess()
    with patch.object(bm.subprocess, "run", side_effect=fake):
        bm._set_calibration_window_enabled("/opt/anontool", enabled=False, use_sudo=True)
    cmd = calls[-1]
    assert cmd[0] == "bash" and cmd[1] == "-c"
    script = cmd[2]
    assert "ANONTOOL_CALIB_ENABLED=false" in script
    assert "--no-deps" in script and "--force-recreate anontool-orchestrator" in script
    assert "/opt/anontool/.env" in script


def test_set_calibration_window_enable_via_relay():
    calls, fake = _capture_subprocess()
    with patch.object(bm.subprocess, "run", side_effect=fake):
        bm._set_calibration_window_enabled(
            "/opt/anontool",
            enabled=True,
            use_sudo=True,
            relay_host="anontool-test",
            relay_user="me",
            ssh_key="/k",
        )
    cmd = calls[-1]
    assert cmd[0] == "ssh"
    assert "me@anontool-test" in cmd and "/k" in cmd
    remote = cmd[-1]
    assert "ANONTOOL_CALIB_ENABLED=true" in remote
    assert "--force-recreate anontool-orchestrator" in remote


def test_manage_calibration_window_flag_default_and_off():
    parser = bm._build_parser()
    on = parser.parse_args(["--run-all-scenarios", "--workload", "x.csv"])
    assert on.manage_calibration_window is True
    off = parser.parse_args(["--run-all-scenarios", "--workload", "x.csv", "--no-manage-calibration-window"])
    assert off.manage_calibration_window is False


# ── Ensure-calibration (non-reset path) ──────────────────────────────────────
# Without a full reset the run must still finish any model the worker never
# calibrated, instead of firing requests at it. These guard that gap.


def test_profile_is_calibrated_distinguishes_stub_from_complete():
    # The interrupted-calibration stub: residency 'cached', measurements None.
    stub = {
        "residency_source": "cached",
        "base_residency_mb": None,
        "sleeping_residual_mb": None,
        "sleep_l1_transient_host_ram_mb": None,
        "last_measured_epoch": 0.0,
    }
    assert bm._profile_is_calibrated(stub) is False

    full = {
        "base_residency_mb": 100.0,
        "sleeping_residual_mb": 50.0,
        "sleep_l1_transient_host_ram_mb": 10.0,
        "min_kv_cache_mb": 1024.0,
        "max_kv_cache_mb": 4096.0,
    }
    assert bm._profile_is_calibrated(full) is True

    # Unsupported is terminal (done); a collapsed KV envelope re-calibrates.
    assert bm._profile_is_calibrated({"calibration_unsupported": True}) is True
    collapsed = {
        "base_residency_mb": 1.0,
        "sleeping_residual_mb": 1.0,
        "sleep_l1_transient_host_ram_mb": 1.0,
        "min_kv_cache_mb": 2048.0,
        "max_kv_cache_mb": 2048.0,
    }
    assert bm._profile_is_calibrated(collapsed) is False

    # Legacy calibrated profile the worker would still recalibrate — the
    # benchmark must mirror the worker, not skip it (else it fires failing
    # requests). Missing kv_cache_to_max_model_len_pairs:
    legacy_no_pairs = {
        "residency_source": "calibrated",
        "base_residency_mb": 100.0,
        "sleeping_residual_mb": 50.0,
        "sleep_l1_transient_host_ram_mb": 10.0,
        "min_kv_cache_mb": 1024.0,
        "max_kv_cache_mb": 4096.0,
        "kv_cache_to_max_model_len_pairs": None,
    }
    assert bm._profile_is_calibrated(legacy_no_pairs) is False
    # Same but WITH the curve → calibrated.
    assert (
        bm._profile_is_calibrated({**legacy_no_pairs, "kv_cache_to_max_model_len_pairs": [{"kv": 1, "mml": 1}]}) is True
    )
    # Old weights-only format (loaded sits a full kv_budget above base):
    stale = {
        "residency_source": "calibrated",
        "base_residency_mb": 1000.0,
        "sleeping_residual_mb": 50.0,
        "sleep_l1_transient_host_ram_mb": 10.0,
        "min_kv_cache_mb": 1024.0,
        "max_kv_cache_mb": 4096.0,
        "kv_cache_to_max_model_len_pairs": [{"kv": 1, "mml": 1}],
        "loaded_vram_mb": 5000.0,
        "kv_budget_mb": 4000.0,
    }
    assert bm._profile_is_calibrated(stale) is False


def test_ensure_calibration_noop_when_all_calibrated():
    with (
        patch.object(bm, "_start_workernode_via_ssh") as start,
        patch.object(bm, "_stop_workernode_via_ssh") as stop,
        patch.object(bm, "_reset_profile_entries_via_ssh") as reset,
        patch.object(bm, "_calibration_status_for_host", return_value=({"m1", "m2"}, [])),
        patch.object(bm, "_set_anontool_sleep_mode_via_ssh") as sleep_set,
        patch.object(bm, "_trigger_calibration_via_rest", new=AsyncMock(return_value=True)) as trig,
        patch.object(bm, "_wait_for_calibration_complete_via_ssh", new=AsyncMock(return_value=True)) as wait,
    ):
        ok = asyncio.run(
            bm._ensure_calibration_complete_all_nodes(
                ["h1"], "u", None, "/opt/wn", ["m1", "m2"], 10.0, "https://x", "k", [3], 9443, True
            )
        )
    assert ok is True
    # Nothing pending → no node churn, no reset, no trigger, no wait.
    start.assert_not_called()
    stop.assert_not_called()
    reset.assert_not_called()
    sleep_set.assert_not_called()
    trig.assert_not_awaited()
    wait.assert_not_awaited()


def test_ensure_calibration_resets_incomplete_then_triggers_with_sleep_on():
    order: list = []
    with (
        patch.object(bm, "_calibration_status_for_host", return_value=(set(), ["m1"])),
        patch.object(bm, "_stop_workernode_via_ssh", side_effect=lambda *a, **k: order.append("stop")),
        patch.object(
            bm, "_reset_profile_entries_via_ssh", side_effect=lambda *a, **k: order.append("reset") or ["m1"]
        ) as reset,
        patch.object(
            bm, "_set_anontool_sleep_mode_via_ssh", side_effect=lambda *a, **k: order.append("sleep")
        ) as sleep_set,
        patch.object(bm, "_start_workernode_via_ssh", side_effect=lambda *a, **k: order.append("start")),
        patch.object(bm, "_trigger_calibration_via_rest", new=AsyncMock(return_value=True)) as trig,
        patch.object(bm, "_wait_for_calibration_complete_via_ssh", new=AsyncMock(return_value=True)) as wait,
    ):
        ok = asyncio.run(
            bm._ensure_calibration_complete_all_nodes(
                ["h1"], "u", None, "/opt/wn", ["m1"], 10.0, "https://x", "k", [3], 9443, True
            )
        )
    assert ok is True
    reset.assert_called_once()  # incomplete entry dropped so worker re-picks it
    sleep_set.assert_called_once()
    trig.assert_awaited_once()
    wait.assert_awaited_once()
    # Critical ordering: stop + reset + enable sleep all BEFORE (re)starting nodes.
    assert order.index("stop") < order.index("start")
    assert order.index("reset") < order.index("start")
    assert order.index("sleep") < order.index("start")


def test_ensure_calibration_fails_without_provider_ids():
    # Pending models but no provider IDs → cannot trigger, must not hang/pass.
    with (
        patch.object(bm, "_stop_workernode_via_ssh") as stop,
        patch.object(bm, "_reset_profile_entries_via_ssh") as reset,
        patch.object(bm, "_calibration_status_for_host", return_value=(set(), ["m1"])),
        patch.object(bm, "_trigger_calibration_via_rest", new=AsyncMock(return_value=True)) as trig,
        patch.object(bm, "_wait_for_calibration_complete_via_ssh", new=AsyncMock(return_value=True)) as wait,
    ):
        ok = asyncio.run(
            bm._ensure_calibration_complete_all_nodes(
                ["h1"], "u", None, "/opt/wn", ["m1"], 10.0, "https://x", "k", [], 9443, True
            )
        )
    assert ok is False
    # Bail before touching the nodes.
    stop.assert_not_called()
    reset.assert_not_called()
    trig.assert_not_awaited()
    wait.assert_not_awaited()
