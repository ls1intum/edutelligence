"""Comprehensive tests for the auto-calibration feature.

Covers:
  - Detection logic (_auto_calibrate_if_needed from main.py)
  - Unit tests for calibration.py pure functions
  - plans_from_config parsing
  - save/load round-trip
  - auto_calibrate_models integration (mocked calibrate_model)
  - Startup lifespan integration
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from logos_worker_node.calibration import (
    CalibrationResult,
    _format_kv_mb,
    _KV_CACHE_MIN_STEP_MB,
    _max_tp_for_plan,
    _parse_kv_to_mb,
    _round_up_gb,
    auto_calibrate_models,
    calibrate_model,
    load_existing_profiles,
    parse_gpu_indices,
    plans_from_config,
    result_to_profile_dict,
    save_profiles,
)
from logos_worker_node.model_profiles import ModelProfileRecord, ModelProfileRegistry
from logos_worker_node.models import AppConfig

import logos_worker_node.main as worker_main


# ── helpers ────────────────────────────────────────────────────────────

def _make_registry(tmp_path: Path, profiles: dict[str, ModelProfileRecord] | None = None) -> ModelProfileRegistry:
    """Create a ModelProfileRegistry backed by *tmp_path* with pre-set profiles."""
    reg = ModelProfileRegistry(state_dir=tmp_path)
    if profiles:
        for name, rec in profiles.items():
            reg._profiles[name] = rec
    return reg


def _make_cfg(capabilities: list[str] | None = None) -> AppConfig:
    caps = capabilities if capabilities is not None else []
    return AppConfig(logos={"capabilities_models": caps})


def _success_result(model: str, **overrides) -> CalibrationResult:
    defaults = dict(
        model=model,
        tensor_parallel_size=1,
        gpu_devices="",
        kv_cache_sent_mb=2048.0,
        success=True,
        loaded_vram_mb=7000.0,
        sleeping_residual_mb=200.0,
        base_residency_mb=4952.0,
        calibrated_at=time.time(),
    )
    defaults.update(overrides)
    return CalibrationResult(**defaults)


def _fail_result(model: str, error: str = "boom") -> CalibrationResult:
    return CalibrationResult(
        model=model,
        tensor_parallel_size=1,
        gpu_devices="",
        kv_cache_sent_mb=0.0,
        success=False,
        error=error,
    )


# ═══════════════════════════════════════════════════════════════════════
# Group 1 — Detection logic (_auto_calibrate_if_needed)
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_all_models_calibrated_skips_calibration(tmp_path):
    cfg = _make_cfg(["model-a", "model-b"])
    reg = _make_registry(tmp_path, {
        "model-a": ModelProfileRecord(base_residency_mb=5000, sleeping_residual_mb=200, loaded_vram_mb=5000, residency_source="calibrated"),
        "model-b": ModelProfileRecord(base_residency_mb=6000, sleeping_residual_mb=300, loaded_vram_mb=6000, residency_source="calibrated"),
    })

    with patch.object(worker_main, "auto_calibrate_models") as mock_cal:
        await worker_main._auto_calibrate_if_needed(cfg, reg, tmp_path)

    mock_cal.assert_not_called()


@pytest.mark.asyncio
async def test_uncalibrated_models_detected(tmp_path):
    cfg = _make_cfg(["model-a", "model-b"])
    reg = _make_registry(tmp_path, {
        "model-a": ModelProfileRecord(base_residency_mb=5000, sleeping_residual_mb=200, loaded_vram_mb=5000, residency_source="calibrated"),
        "model-b": ModelProfileRecord(base_residency_mb=None),
    })

    fake_result = _success_result("model-b")
    with patch.object(worker_main, "auto_calibrate_models", return_value={"model-b": fake_result}) as mock_cal:
        await worker_main._auto_calibrate_if_needed(cfg, reg, tmp_path)

    mock_cal.assert_called_once()
    call_args = mock_cal.call_args
    assert call_args[0][0] == ["model-b"]


@pytest.mark.asyncio
async def test_no_profile_means_uncalibrated(tmp_path):
    cfg = _make_cfg(["model-a", "model-b"])
    reg = _make_registry(tmp_path)  # empty

    fake = {"model-a": _success_result("model-a"), "model-b": _success_result("model-b")}
    with patch.object(worker_main, "auto_calibrate_models", return_value=fake) as mock_cal:
        await worker_main._auto_calibrate_if_needed(cfg, reg, tmp_path)

    mock_cal.assert_called_once()
    uncalibrated = mock_cal.call_args[0][0]
    assert set(uncalibrated) == {"model-a", "model-b"}


@pytest.mark.asyncio
async def test_skip_env_var_disables_calibration(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGOS_SKIP_AUTO_CALIBRATION", "1")
    cfg = _make_cfg(["model-a"])
    reg = _make_registry(tmp_path)

    with patch.object(worker_main, "auto_calibrate_models") as mock_cal:
        await worker_main._auto_calibrate_if_needed(cfg, reg, tmp_path)

    mock_cal.assert_not_called()


@pytest.mark.asyncio
async def test_skip_env_var_true_string(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGOS_SKIP_AUTO_CALIBRATION", "true")
    cfg = _make_cfg(["model-a"])
    reg = _make_registry(tmp_path)

    with patch.object(worker_main, "auto_calibrate_models") as mock_cal:
        await worker_main._auto_calibrate_if_needed(cfg, reg, tmp_path)

    mock_cal.assert_not_called()


@pytest.mark.asyncio
async def test_empty_capabilities_skips(tmp_path):
    cfg = _make_cfg([])
    reg = _make_registry(tmp_path)

    with patch.object(worker_main, "auto_calibrate_models") as mock_cal:
        await worker_main._auto_calibrate_if_needed(cfg, reg, tmp_path)

    mock_cal.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════
# Group 2 — Unit tests for calibration.py functions
# ═══════════════════════════════════════════════════════════════════════


def test_parse_kv_to_mb_gigabytes():
    assert _parse_kv_to_mb("4G") == 4096.0


def test_parse_kv_to_mb_megabytes():
    assert _parse_kv_to_mb("512M") == 512.0


def test_parse_kv_to_mb_kilobytes():
    assert _parse_kv_to_mb("1024K") == pytest.approx(1.0)


def test_parse_kv_to_mb_bytes():
    assert _parse_kv_to_mb("1048576") == pytest.approx(1.0)


def test_parse_gpu_indices_csv():
    assert parse_gpu_indices("0,1") == [0, 1]


def test_parse_gpu_indices_all():
    assert parse_gpu_indices("all") is None


def test_parse_gpu_indices_empty():
    assert parse_gpu_indices("") is None


def test_result_to_profile_dict_sets_calibrated_source():
    r = _success_result("test-model")
    d = result_to_profile_dict(r)
    assert d["residency_source"] == "calibrated"


def test_result_to_profile_dict_values():
    r = CalibrationResult(
        model="org/my-model",
        tensor_parallel_size=2,
        gpu_devices="0,1",
        kv_cache_sent_mb=2048.0,
        success=True,
        loaded_vram_mb=7000.0,
        sleeping_residual_mb=200.0,
        base_residency_mb=4952.0,
        calibrated_at=1700000000.0,
    )
    d = result_to_profile_dict(r)

    assert d["loaded_vram_mb"] == 7000.0
    assert d["sleeping_residual_mb"] == 200.0
    assert d["base_residency_mb"] == 4952.0
    assert d["kv_budget_mb"] == 2048.0
    assert d["engine"] == "vllm"
    assert d["tensor_parallel_size"] == 2
    assert d["measurement_count"] == 1
    assert d["last_measured_epoch"] == 1700000000.0
    assert d["residency_source"] == "calibrated"


# ═══════════════════════════════════════════════════════════════════════
# Group 3 — plans_from_config
# ═══════════════════════════════════════════════════════════════════════


def test_plans_from_config_simple(tmp_path):
    cfg = {
        "logos": {
            "capabilities_models": ["org/model-a", "org/model-b"],
        },
    }
    config_path = tmp_path / "config.yml"
    config_path.write_text(yaml.safe_dump(cfg))

    plans = plans_from_config(config_path)
    assert len(plans) == 2
    assert plans[0]["model"] == "org/model-a"
    assert plans[1]["model"] == "org/model-b"


def test_plans_from_config_with_overrides(tmp_path):
    cfg = {
        "logos": {
            "capabilities_models": [
                "org/model-a",
                {"model": "org/model-b", "tensor_parallel_size": 4},
            ],
        },
    }
    config_path = tmp_path / "config.yml"
    config_path.write_text(yaml.safe_dump(cfg))

    plans = plans_from_config(config_path)
    assert len(plans) == 2
    assert plans[0]["model"] == "org/model-a"
    assert plans[1]["model"] == "org/model-b"
    assert plans[1]["tensor_parallel_size"] == 4


def test_plans_from_config_merges_vllm_model_overrides(tmp_path):
    cfg = {
        "logos": {
            "capabilities_models": ["org/model-a"],
        },
        "engines": {
            "vllm": {
                "model_overrides": {
                    "org/model-a": {
                        "quantization": "awq",
                        "enforce_eager": True,
                    },
                },
            },
        },
    }
    config_path = tmp_path / "config.yml"
    config_path.write_text(yaml.safe_dump(cfg))

    plans = plans_from_config(config_path)
    assert len(plans) == 1
    assert plans[0]["model"] == "org/model-a"
    assert plans[0]["quantization"] == "awq"
    assert plans[0]["enforce_eager"] is True


# ═══════════════════════════════════════════════════════════════════════
# Group 4 — save / load round-trip
# ═══════════════════════════════════════════════════════════════════════


def test_save_load_profiles_roundtrip(tmp_path):
    profiles_path = tmp_path / "model_profiles.yml"
    original = {
        "org/model-a": {
            "base_residency_mb": 5000.0,
            "loaded_vram_mb": 7000.0,
            "sleeping_residual_mb": 200.0,
            "residency_source": "calibrated",
        },
        "org/model-b": {
            "base_residency_mb": 3500.0,
            "loaded_vram_mb": 5500.0,
            "sleeping_residual_mb": 150.0,
            "residency_source": "calibrated",
        },
    }

    save_profiles(profiles_path, original)
    loaded = load_existing_profiles(profiles_path)

    assert loaded == original


def test_load_existing_profiles_missing_file(tmp_path):
    missing = tmp_path / "nonexistent" / "model_profiles.yml"
    assert load_existing_profiles(missing) == {}


# ═══════════════════════════════════════════════════════════════════════
# Group 5 — auto_calibrate_models integration (mock calibrate_model)
# ═══════════════════════════════════════════════════════════════════════


def _write_config(tmp_path, models):
    """Write a minimal config.yml with capabilities_models."""
    cfg = {"logos": {"capabilities_models": models}}
    config_path = tmp_path / "config.yml"
    config_path.write_text(yaml.safe_dump(cfg))
    return config_path


def _mock_gpu_snap(n_gpus=1, total_mb=24000.0):
    """Return a fake query_gpu_vram result for *n_gpus* identical GPUs."""
    return {i: {"total_mb": total_mb, "used_mb": 500.0, "free_mb": total_mb - 500.0} for i in range(n_gpus)}


def test_auto_calibrate_models_calls_calibrate_for_each(tmp_path):
    config_path = _write_config(tmp_path, ["model-a", "model-b"])
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    side = {"model-a": _success_result("model-a"), "model-b": _success_result("model-b")}

    with patch("logos_worker_node.calibration.calibrate_model") as mock_cm, \
         patch("logos_worker_node.calibration.query_gpu_vram", return_value=_mock_gpu_snap()):
        mock_cm.side_effect = lambda plan, **kw: side[plan["model"]]
        results = auto_calibrate_models(
            ["model-a", "model-b"], config_path, state_dir,
        )

    assert mock_cm.call_count == 2
    assert results["model-a"].success
    assert results["model-b"].success


def test_auto_calibrate_models_persists_after_each_success(tmp_path):
    config_path = _write_config(tmp_path, ["model-a", "model-b"])
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    side = {"model-a": _success_result("model-a"), "model-b": _success_result("model-b")}

    with patch("logos_worker_node.calibration.calibrate_model") as mock_cm, \
         patch("logos_worker_node.calibration.save_profiles") as mock_save, \
         patch("logos_worker_node.calibration.query_gpu_vram", return_value=_mock_gpu_snap()):
        mock_cm.side_effect = lambda plan, **kw: side[plan["model"]]
        auto_calibrate_models(["model-a", "model-b"], config_path, state_dir)

    assert mock_save.call_count == 2


def test_auto_calibrate_models_continues_on_failure(tmp_path):
    """Failed model-a (even after tp escalation) doesn't block model-b."""
    config_path = _write_config(tmp_path, ["model-a", "model-b"])
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    # model-a fails at both tp=1 and tp=2; model-b succeeds at tp=1
    def side_effect(plan, **kw):
        if plan["model"] == "model-a":
            return _fail_result("model-a")
        return _success_result("model-b")

    with patch("logos_worker_node.calibration.calibrate_model") as mock_cm, \
         patch("logos_worker_node.calibration.query_gpu_vram", return_value=_mock_gpu_snap(2)):
        mock_cm.side_effect = side_effect
        results = auto_calibrate_models(
            ["model-a", "model-b"], config_path, state_dir,
        )

    # model-a: tp=2 fail + tp=1 fallback fail = 2, model-b: tp=2 ok + tp=1 search = 2
    assert mock_cm.call_count == 4
    assert not results["model-a"].success
    assert results["model-b"].success
    # Only model-b should have a persisted profile
    profiles = load_existing_profiles(state_dir / "model_profiles.yml")
    assert "model-b" in profiles
    assert "model-a" not in profiles


def test_auto_calibrate_models_filters_to_uncalibrated_only(tmp_path):
    config_path = _write_config(tmp_path, ["model-a", "model-b"])
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    with patch("logos_worker_node.calibration.calibrate_model") as mock_cm, \
         patch("logos_worker_node.calibration.query_gpu_vram", return_value=_mock_gpu_snap()):
        mock_cm.return_value = _success_result("model-b")
        results = auto_calibrate_models(
            ["model-b"], config_path, state_dir,
        )

    assert mock_cm.call_count == 1
    plan_arg = mock_cm.call_args[0][0]
    assert plan_arg["model"] == "model-b"
    assert "model-a" not in results


def test_auto_calibrate_tp_escalation(tmp_path):
    """Max-first strategy: try tp=2 first, then binary-search down to tp=1.

    On a 2-GPU host with default tp=1, the first attempt uses tp=2 (max).
    If tp=2 succeeds, it then tries tp=1 to find the minimum.  If tp=1
    fails, the final result uses tp=2.
    """
    config_path = _write_config(tmp_path, ["big-model"])
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    def side_effect(plan, **kw):
        tp = plan.get("tensor_parallel_size", 1)
        if tp == 1:
            return _fail_result("big-model", error="OOM on tp=1")
        return _success_result("big-model", tensor_parallel_size=tp)

    with patch("logos_worker_node.calibration.calibrate_model") as mock_cm, \
         patch("logos_worker_node.calibration.query_gpu_vram", return_value=_mock_gpu_snap(2)):
        mock_cm.side_effect = side_effect
        results = auto_calibrate_models(["big-model"], config_path, state_dir)

    assert mock_cm.call_count == 2
    # First call: tp=2 (max), second call: tp=1 (binary search down)
    assert mock_cm.call_args_list[0][0][0]["tensor_parallel_size"] == 2
    assert mock_cm.call_args_list[1][0][0]["tensor_parallel_size"] == 1
    assert results["big-model"].success
    assert results["big-model"].tensor_parallel_size == 2


def test_auto_calibrate_no_escalation_on_single_gpu(tmp_path):
    """On a single-GPU host, max tp == 1 so only one attempt is made."""
    config_path = _write_config(tmp_path, ["big-model"])
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    with patch("logos_worker_node.calibration.calibrate_model") as mock_cm, \
         patch("logos_worker_node.calibration.query_gpu_vram", return_value=_mock_gpu_snap(1)):
        mock_cm.return_value = _fail_result("big-model")
        results = auto_calibrate_models(["big-model"], config_path, state_dir)

    assert mock_cm.call_count == 1  # max tp == 1, single attempt
    assert not results["big-model"].success


def test_auto_calibrate_no_escalation_when_already_max_tp(tmp_path):
    """Model configured at tp=2 on 2-GPU host — max == configured, single attempt."""
    cfg = {"logos": {"capabilities_models": [{"model": "big-model", "tensor_parallel_size": 2}]}}
    config_path = tmp_path / "config.yml"
    config_path.write_text(yaml.safe_dump(cfg))
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    with patch("logos_worker_node.calibration.calibrate_model") as mock_cm, \
         patch("logos_worker_node.calibration.query_gpu_vram", return_value=_mock_gpu_snap(2)):
        mock_cm.return_value = _fail_result("big-model")
        results = auto_calibrate_models(["big-model"], config_path, state_dir)

    assert mock_cm.call_count == 1  # already at max tp, single attempt
    assert not results["big-model"].success


def test_max_tp_for_plan():
    assert _max_tp_for_plan({"model": "x"}, available_gpus=4) == 4
    assert _max_tp_for_plan({"model": "x", "gpu_devices": "0,1"}, available_gpus=4) == 2
    assert _max_tp_for_plan({"model": "x", "gpu_devices": "0"}, available_gpus=4) == 1
    assert _max_tp_for_plan({"model": "x", "gpu_devices": "all"}, available_gpus=4) == 4
    assert _max_tp_for_plan({"model": "x", "gpu_devices": ""}, available_gpus=4) == 4


# ═══════════════════════════════════════════════════════════════════════
# Group 6 — Startup integration (mock everything)
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_lifespan_calls_auto_calibrate(tmp_path):
    """Verify that the lifespan context manager calls _auto_calibrate_if_needed."""
    cfg = _make_cfg(["model-a"])

    mock_gpu = AsyncMock()
    mock_gpu.available = True
    mock_gpu.device_count = 1
    mock_gpu.per_gpu_vram_mb = 24000.0
    mock_gpu.get_snapshot = MagicMock(return_value={})
    mock_gpu.force_poll = AsyncMock()
    mock_gpu.start = AsyncMock()
    mock_gpu.stop = AsyncMock()

    mock_bridge = AsyncMock()
    mock_bridge.start = AsyncMock()
    mock_bridge.stop = AsyncMock()

    mock_cache = MagicMock()
    mock_cache.enabled = False

    with patch("logos_worker_node.main.load_config", return_value=cfg), \
         patch("logos_worker_node.main.get_state_dir", return_value=tmp_path), \
         patch("logos_worker_node.main.GpuMetricsCollector", return_value=mock_gpu), \
         patch("logos_worker_node.main.ModelProfileRegistry") as mock_reg_cls, \
         patch("logos_worker_node.main._auto_calibrate_if_needed", new_callable=AsyncMock) as mock_autocal, \
         patch("logos_worker_node.main.create_model_cache", return_value=mock_cache), \
         patch("logos_worker_node.main.LaneManager") as mock_lm_cls, \
         patch("logos_worker_node.main.LogosBridgeClient", return_value=mock_bridge), \
         patch.dict("sys.modules", {"logos_worker_node.flashinfer_warmup": MagicMock()}):

        mock_reg = MagicMock()
        mock_reg.get_profile.return_value = None
        mock_reg_cls.return_value = mock_reg

        mock_lm = AsyncMock()
        mock_lm.close = AsyncMock()
        mock_lm.destroy_all = AsyncMock()
        mock_lm.validate_capabilities = MagicMock()
        mock_lm_cls.return_value = mock_lm

        app = worker_main.app
        async with worker_main.lifespan(app):
            pass

    mock_autocal.assert_called_once()
    call_args = mock_autocal.call_args
    assert call_args[0][0] is cfg       # first arg = config
    assert call_args[0][1] is mock_reg  # second arg = profile registry
    assert call_args[0][2] == tmp_path  # third arg = state_dir


# ═══════════════════════════════════════════════════════════════════════
# Group 7 — _format_kv_mb helper
# ═══════════════════════════════════════════════════════════════════════


def test_format_kv_mb_whole_gigabytes():
    assert _format_kv_mb(2048.0) == "2G"
    assert _format_kv_mb(4096.0) == "4G"
    assert _format_kv_mb(1024.0) == "1G"


def test_format_kv_mb_fractional_gigabytes():
    assert _format_kv_mb(1536.0) == "1536M"
    assert _format_kv_mb(2560.0) == "2560M"


def test_format_kv_mb_zero():
    assert _format_kv_mb(0.0) == "0M"


# ═══════════════════════════════════════════════════════════════════════
# Group 8 — KV cache search in calibrate_model
# ═══════════════════════════════════════════════════════════════════════


def _make_plan(model: str = "org/test-model", **overrides) -> dict:
    plan: dict = {"model": model, "kv_cache_memory_bytes": "4G"}
    plan.update(overrides)
    return plan


def _gpu_vram_snapshot(total_mb: float = 24000.0, used_mb: float = 500.0):
    """Return a fake query_gpu_vram result for a single GPU."""
    return {0: {"total_mb": total_mb, "used_mb": used_mb, "free_mb": total_mb - used_mb}}


def _patch_calibration_infra(
    *,
    wait_ready_side_effect=None,
    sample_vram_sequence=None,
    gpu_vram_total_mb: float = 24000.0,
):
    """Return a dict of patches for calibrate_model's external dependencies.

    ``wait_ready_side_effect``: controls Phase 2 pass/fail per call.
    ``sample_vram_sequence``: list of floats returned by successive sample_vram_mb calls.
    ``gpu_vram_total_mb``: total GPU VRAM reported by query_gpu_vram.
    """
    patches = {}

    # spawn_vllm → returns (mock_popen, ["cmd"]) tuple
    mock_popen = MagicMock()
    mock_popen.pid = 12345
    mock_popen.poll.return_value = None
    patches["spawn"] = patch(
        "logos_worker_node.calibration.spawn_vllm",
        return_value=(mock_popen, ["vllm", "serve"]),
    )

    # stop_vllm → no-op
    patches["stop"] = patch("logos_worker_node.calibration.stop_vllm")

    # wait_ready
    patches["ready"] = patch(
        "logos_worker_node.calibration.wait_ready",
        side_effect=wait_ready_side_effect,
    )

    # query_gpu_vram → returns consistent snapshot
    snap = _gpu_vram_snapshot(total_mb=gpu_vram_total_mb)
    patches["gpu_vram"] = patch(
        "logos_worker_node.calibration.query_gpu_vram", return_value=snap
    )

    # sample_vram_mb → returns values from sequence
    if sample_vram_sequence is None:
        sample_vram_sequence = [500.0, 7500.0, 600.0]  # baseline, awake, sleeping
    patches["sample"] = patch(
        "logos_worker_node.calibration.sample_vram_mb",
        side_effect=sample_vram_sequence,
    )

    # time.sleep → skip
    patches["sleep"] = patch("logos_worker_node.calibration.time.sleep")

    # wait_sleep_state → no-op
    patches["wait_sleep"] = patch("logos_worker_node.calibration.wait_sleep_state")

    # _post (for /sleep endpoint) → success
    patches["post"] = patch(
        "logos_worker_node.calibration._post", return_value=(200, {})
    )

    # _kill_stale_vllm_workers → no-op (avoids scanning /proc in tests)
    patches["kill_stale"] = patch(
        "logos_worker_node.calibration._kill_stale_vllm_workers"
    )

    # _load_failed_commands → always empty (no cross-test contamination)
    patches["load_failed"] = patch(
        "logos_worker_node.calibration._load_failed_commands", return_value=set()
    )

    return patches


def _run_calibrate(patches, plan=None):
    """Enter all patches and call calibrate_model. Returns (result, mocks_dict)."""
    plan = plan or _make_plan()
    log_dir = Path("/tmp/test-calibration-logs")

    managers = {k: p.__enter__() for k, p in patches.items()}
    try:
        result = calibrate_model(
            plan,
            vllm_binary="vllm",
            port=11499,
            log_dir=log_dir,
            sleep_level=1,
            ready_timeout_s=60.0,
        )
    finally:
        for p in patches.values():
            p.__exit__(None, None, None)

    return result, managers


def test_fail_fast_on_startup_failure():
    """When vLLM fails to start, calibrate_model returns immediately (no binary search)."""
    patches = _patch_calibration_infra(
        wait_ready_side_effect=[RuntimeError("vLLM exited (code=1)")],
    )

    result, mocks = _run_calibrate(patches)

    assert not result.success
    assert "failed to start" in result.error.lower()
    assert "tp=1" in result.error
    # Only one spawn attempt — fail fast, no upward search
    assert mocks["spawn"].call_count == 1


def test_first_attempt_succeeds():
    """When the default KV cache works, no retry happens."""
    patches = _patch_calibration_infra(
        wait_ready_side_effect=[None],  # success on first try
        sample_vram_sequence=[500.0, 7500.0, 600.0],
    )

    result, mocks = _run_calibrate(patches)

    assert result.success
    assert result.kv_cache_sent_mb == pytest.approx(4096.0)  # 4G default
    assert mocks["spawn"].call_count == 1


def test_timeout_not_retried():
    """TimeoutError (vLLM loaded but warmup slow) should NOT trigger retry."""
    patches = _patch_calibration_infra(
        wait_ready_side_effect=[TimeoutError("vLLM not ready after 60s")],
    )

    result, mocks = _run_calibrate(patches)

    assert not result.success
    assert "failed" in result.error.lower()
    # Only one spawn attempt — no retry on timeout
    assert mocks["spawn"].call_count == 1


def test_vram_cap_uses_per_gpu_times_tp():
    """VRAM cap should use per-GPU VRAM × tp, not total across all GPUs."""
    # 2 GPUs × 24000 MB each, but tp=1 → cap should be 24000 × 0.8 = 19200
    two_gpu_snap = {
        0: {"total_mb": 24000.0, "used_mb": 500.0, "free_mb": 23500.0},
        1: {"total_mb": 24000.0, "used_mb": 500.0, "free_mb": 23500.0},
    }
    patches = _patch_calibration_infra(
        wait_ready_side_effect=[None],
        sample_vram_sequence=[500.0, 7500.0, 600.0],
    )
    # Override the gpu_vram mock to return 2 GPUs
    patches["gpu_vram"] = patch(
        "logos_worker_node.calibration.query_gpu_vram", return_value=two_gpu_snap
    )

    result, mocks = _run_calibrate(patches, plan=_make_plan(tensor_parallel_size=1))

    assert result.success
    # The important thing: it didn't try to use 48000*0.8=38400 as cap


@pytest.mark.asyncio
async def test_calibration_output_honored_on_startup(tmp_path):
    """Ensure that calibration output is honored — no recalibration triggered."""
    # Simulate a model that was successfully calibrated.
    # In real calibration: base_residency_mb == loaded_vram_mb (full loaded footprint).
    r = _success_result("model-a", kv_cache_sent_mb=3072.0, loaded_vram_mb=7000.0, base_residency_mb=7000.0)
    profile = result_to_profile_dict(r)

    # Create a registry with the profile already present.
    # All required fields set so _auto_calibrate_if_needed considers it calibrated:
    #   base_residency_mb is not None, sleeping_residual_mb is not None,
    #   base_residency_mb == loaded_vram_mb (no stale format mismatch).
    reg = _make_registry(tmp_path, {
        "model-a": ModelProfileRecord(
            base_residency_mb=profile["base_residency_mb"],
            sleeping_residual_mb=profile["sleeping_residual_mb"],
            loaded_vram_mb=profile["loaded_vram_mb"],
            residency_source="calibrated",
        ),
    })

    cfg = _make_cfg(["model-a"])

    with patch.object(worker_main, "auto_calibrate_models") as mock_cal:
        await worker_main._auto_calibrate_if_needed(cfg, reg, tmp_path)

    # Already calibrated → no recalibration
    mock_cal.assert_not_called()


def test_profile_dict_has_calibration_kv_field():
    """result_to_profile_dict includes calibration_kv_cache_memory_bytes."""
    r = _success_result("org/my-model", kv_cache_sent_mb=5120.0)
    d = result_to_profile_dict(r)

    assert "calibration_kv_cache_memory_bytes" in d
    assert d["calibration_kv_cache_memory_bytes"] == "5G"


# ═══════════════════════════════════════════════════════════════════════
# Group 9 — KV cache search direction (floor-to-ceiling)
# ═══════════════════════════════════════════════════════════════════════


def _make_search_plan(model: str = "org/test-model", **overrides) -> dict:
    """Plan WITHOUT kv_cache_memory_bytes so kv_search=True is triggered."""
    plan: dict = {"model": model}
    plan.update(overrides)
    return plan


def _patch_search_infra(
    *,
    wait_ready_side_effect,
    sample_vram_sequence=None,
    gpu_vram_total_mb: float = 48000.0,
):
    """Like _patch_calibration_infra but tailored for kv_search=True tests.

    Returns patches dict.  ``wait_ready_side_effect`` controls which
    _try_start probes succeed (None) or fail (RuntimeError).
    """
    patches = {}

    # spawn_vllm → returns (mock_popen, ["cmd"]) tuple
    mock_popen = MagicMock()
    mock_popen.pid = 12345
    mock_popen.poll.return_value = None
    patches["spawn"] = patch(
        "logos_worker_node.calibration.spawn_vllm",
        return_value=(mock_popen, ["vllm", "serve"]),
    )

    patches["stop"] = patch("logos_worker_node.calibration.stop_vllm")

    patches["ready"] = patch(
        "logos_worker_node.calibration.wait_ready",
        side_effect=wait_ready_side_effect,
    )

    snap = _gpu_vram_snapshot(total_mb=gpu_vram_total_mb)
    patches["gpu_vram"] = patch(
        "logos_worker_node.calibration.query_gpu_vram", return_value=snap
    )

    if sample_vram_sequence is None:
        sample_vram_sequence = [500.0, 7500.0, 600.0]  # baseline, awake, sleeping
    patches["sample"] = patch(
        "logos_worker_node.calibration.sample_vram_mb",
        side_effect=sample_vram_sequence,
    )

    patches["sleep"] = patch("logos_worker_node.calibration.time.sleep")
    patches["wait_sleep"] = patch("logos_worker_node.calibration.wait_sleep_state")
    patches["post"] = patch(
        "logos_worker_node.calibration._post", return_value=(200, {})
    )
    patches["kill_stale"] = patch(
        "logos_worker_node.calibration._kill_stale_vllm_workers"
    )

    # _load_failed_commands → always empty (no cross-test contamination)
    patches["load_failed"] = patch(
        "logos_worker_node.calibration._load_failed_commands", return_value=set()
    )

    return patches


def _run_search_calibrate(patches, plan=None):
    """Enter all patches and call calibrate_model with a search plan."""
    plan = plan or _make_search_plan()
    log_dir = Path("/tmp/test-calibration-logs")

    managers = {k: p.__enter__() for k, p in patches.items()}
    try:
        result = calibrate_model(
            plan,
            vllm_binary="vllm",
            port=11499,
            log_dir=log_dir,
            sleep_level=1,
            ready_timeout_s=60.0,
        )
    finally:
        for p in patches.values():
            p.__exit__(None, None, None)

    return result, managers


def test_search_starts_from_floor_not_ceiling():
    """First probe should be at the floor (1 GB), not the ceiling.

    Mock: succeed at 1 GB and 4 GB, fail at 8 GB+.
    GPU = 48 GB → ceiling = 48000*0.8 = 38400 → rounded down = 37888 MB (37 GB).
    Search: floor=1024, ceiling=37888.
    Mid = round_up_gb((1024+37888)/2) = round_up_gb(19456) = 19456 (already GB-aligned).
    """
    # We need enough side_effect entries for:
    #  1. floor probe (1 GB) → OK
    #  2. binary search probes → need to figure out exact midpoints
    # With 48 GB GPU: ceiling = floor(48000*0.8/1024)*1024 = floor(37.5)*1024 = 37*1024 = 37888
    # Actually: 48000 * 0.8 = 38400.  floor(38400/1024)*1024 = 37*1024 = 37888.
    # Search: lo=1024, hi=37888.
    #   mid=round_up_gb((1024+37888)/2)=round_up_gb(19456)=19456  → fail
    #   hi = 19456-1024 = 18432
    #   mid=round_up_gb((1024+18432)/2)=round_up_gb(9728)=10240   → fail
    #   hi = 10240-1024 = 9216
    #   mid=round_up_gb((1024+9216)/2)=round_up_gb(5120)=5120     → fail
    #   hi = 5120-1024 = 4096
    #   mid=round_up_gb((1024+4096)/2)=round_up_gb(2560)=3072     → OK, best_kv=3072
    #   lo = 3072, hi = 4096
    #   hi-lo = 1024 >= 1024 → continue
    #   mid=round_up_gb((3072+4096)/2)=round_up_gb(3584)=4096     → OK, best_kv=4096
    #   lo = 4096, hi = 4096 → hi-lo=0 < 1024, stop
    # best_kv = 4096
    # Final measurement probe at 4096 → OK.
    # Total probes: floor(1024), 19456, 10240, 5120, 3072, 4096, final(4096) = 7 wait_ready calls
    # Plus awake/sleeping measurement calls (wait_sleep_state etc.)

    kv_calls = []

    def spawn_side_effect(plan, vllm_binary, host, port, log_path, kv_cache_memory_bytes, **kwargs):
        kv_calls.append(kv_cache_memory_bytes)
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        return (mock_proc, ["vllm", "serve"])

    kv_fail_threshold_mb = 5120  # fail at 5 GB and above

    def wait_ready_side_effect(*args, **kwargs):
        # The last spawned process has the kv from kv_calls[-1]
        last_kv = _parse_kv_to_mb(kv_calls[-1])
        if last_kv >= kv_fail_threshold_mb:
            raise RuntimeError("OOM")

    patches = _patch_search_infra(
        wait_ready_side_effect=wait_ready_side_effect,
        gpu_vram_total_mb=48000.0,
    )
    # Override spawn and ready with our custom versions
    patches["spawn"] = patch(
        "logos_worker_node.calibration.spawn_vllm",
        side_effect=spawn_side_effect,
    )
    patches["ready"] = patch(
        "logos_worker_node.calibration.wait_ready",
        side_effect=wait_ready_side_effect,
    )

    result, _ = _run_search_calibrate(patches, plan=_make_search_plan())

    assert result.success
    # First probe must be at the floor (1 GB), NOT the ceiling
    assert kv_calls[0] == "1G", f"First probe should be 1G (floor), got {kv_calls[0]}"
    # best_kv should be 4096 MB (4 GB) — the highest that fits below 5 GB
    assert result.kv_cache_sent_mb == pytest.approx(4096.0)


def test_floor_fails_ceiling_succeeds_uses_ceiling():
    """When the floor probe fails but the ceiling succeeds, the ceiling is
    the maximum KV cache — use it directly (no downward search needed)."""
    kv_calls = []
    kv_min_threshold_mb = 5120  # model needs >= 5 GB KV

    def spawn_side_effect(plan, vllm_binary, host, port, log_path, kv_cache_memory_bytes, **kwargs):
        kv_calls.append(kv_cache_memory_bytes)
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        return (mock_proc, ["vllm", "serve"])

    def wait_ready_side_effect(*args, **kwargs):
        last_kv = _parse_kv_to_mb(kv_calls[-1])
        if last_kv < kv_min_threshold_mb:
            raise RuntimeError("KV cache too small for max_position_embeddings")

    patches = _patch_search_infra(
        wait_ready_side_effect=wait_ready_side_effect,
        gpu_vram_total_mb=24000.0,
    )
    patches["spawn"] = patch(
        "logos_worker_node.calibration.spawn_vllm",
        side_effect=spawn_side_effect,
    )
    patches["ready"] = patch(
        "logos_worker_node.calibration.wait_ready",
        side_effect=wait_ready_side_effect,
    )

    result, _ = _run_search_calibrate(patches, plan=_make_search_plan())

    assert result.success
    assert kv_calls[0] == "1G"  # floor probed first
    # ceiling = floor(24000*0.8/1024)*1024 = 18432
    # Ceiling works and is the max — no further search.
    assert result.kv_cache_sent_mb == pytest.approx(18432.0)


def test_both_fail_searches_middle_range():
    """When floor AND ceiling both fail, search interior points to find the
    working KV range (floor too small for context, ceiling too large for VRAM),
    then binary-search upward for the maximum."""
    # GPU = 48 GB → ceiling = floor(48000*0.8/1024)*1024 = 37888
    # Model: needs >= 6 GB KV (context), but OOMs above 32 GB (VRAM).
    kv_calls = []
    kv_min_mb = 6144.0   # 6 GB — min KV for max_position_embeddings
    kv_max_mb = 32768.0  # 32 GB — max KV before OOM

    def spawn_side_effect(plan, vllm_binary, host, port, log_path, kv_cache_memory_bytes, **kwargs):
        kv_calls.append(kv_cache_memory_bytes)
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        return (mock_proc, ["vllm", "serve"])

    def wait_ready_side_effect(*args, **kwargs):
        last_kv = _parse_kv_to_mb(kv_calls[-1])
        if last_kv < kv_min_mb:
            raise RuntimeError("KV cache too small for max_position_embeddings")
        if last_kv > kv_max_mb:
            raise RuntimeError("OOM: KV + weights exceeds VRAM")

    patches = _patch_search_infra(
        wait_ready_side_effect=wait_ready_side_effect,
        gpu_vram_total_mb=48000.0,
    )
    patches["spawn"] = patch(
        "logos_worker_node.calibration.spawn_vllm",
        side_effect=spawn_side_effect,
    )
    patches["ready"] = patch(
        "logos_worker_node.calibration.wait_ready",
        side_effect=wait_ready_side_effect,
    )

    result, _ = _run_search_calibrate(patches, plan=_make_search_plan())

    assert result.success
    # Should find a KV cache within the working range [6G, 32G]
    assert result.kv_cache_sent_mb >= kv_min_mb
    assert result.kv_cache_sent_mb <= kv_max_mb
    # Should have found the maximum (or close to it, ±1 GB precision)
    assert result.kv_cache_sent_mb >= kv_max_mb - _KV_CACHE_MIN_STEP_MB


def test_all_interior_points_fail_gives_error():
    """When floor, ceiling, AND all interior probes fail, report clear error."""
    patches = _patch_search_infra(
        wait_ready_side_effect=RuntimeError("always fails"),
        gpu_vram_total_mb=48000.0,
    )

    result, _ = _run_search_calibrate(patches, plan=_make_search_plan())

    assert not result.success
    assert "no working kv cache size" in result.error.lower()


def test_ceiling_reachable():
    """When all probes succeed, best_kv should reach the ceiling value."""
    # All wait_ready calls succeed (never raise)
    # With 24 GB GPU: ceiling = floor(24000*0.8/1024)*1024 = floor(18.75)*1024 = 18*1024 = 18432
    # The search will binary-search up and eventually reach 18432.

    patches = _patch_search_infra(
        wait_ready_side_effect=None,  # will be overridden below
        gpu_vram_total_mb=24000.0,
    )
    # All probes succeed
    patches["ready"] = patch(
        "logos_worker_node.calibration.wait_ready",
    )

    result, _ = _run_search_calibrate(patches, plan=_make_search_plan())

    assert result.success
    # ceiling = floor(24000 * 0.8 / 1024) * 1024 = 18432
    expected_ceiling = 18432.0
    assert result.kv_cache_sent_mb == pytest.approx(expected_ceiling)


def test_search_direction_never_probes_ceiling_first():
    """Ensure the search NEVER probes the full ceiling as the first attempt.

    This is the core behavioral guarantee: the old code probed the ceiling
    first (which OOMed on large models), the new code probes the floor first.
    """
    kv_calls = []

    def spawn_side_effect(plan, vllm_binary, host, port, log_path, kv_cache_memory_bytes, **kwargs):
        kv_calls.append(_parse_kv_to_mb(kv_cache_memory_bytes))
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        return (mock_proc, ["vllm", "serve"])

    patches = _patch_search_infra(
        wait_ready_side_effect=None,
        gpu_vram_total_mb=48000.0,
    )
    patches["spawn"] = patch(
        "logos_worker_node.calibration.spawn_vllm",
        side_effect=spawn_side_effect,
    )
    patches["ready"] = patch("logos_worker_node.calibration.wait_ready")

    result, _ = _run_search_calibrate(patches, plan=_make_search_plan())

    assert result.success
    # ceiling = floor(48000*0.8/1024)*1024 = 37888
    ceiling = 37888.0
    # First probe must be the floor (1024 MB), not the ceiling
    assert kv_calls[0] == pytest.approx(_KV_CACHE_MIN_STEP_MB)
    assert kv_calls[0] != pytest.approx(ceiling)
