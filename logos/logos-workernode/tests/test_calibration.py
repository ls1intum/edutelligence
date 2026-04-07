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
    _DEFAULT_KV_CACHE,
    _KV_CACHE_MIN_STEP_MB,
    _KV_CACHE_VRAM_CAP_RATIO,
    _format_kv_mb,
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
        "model-a": ModelProfileRecord(base_residency_mb=5000, residency_source="calibrated"),
        "model-b": ModelProfileRecord(base_residency_mb=6000, residency_source="calibrated"),
    })

    with patch.object(worker_main, "auto_calibrate_models") as mock_cal:
        await worker_main._auto_calibrate_if_needed(cfg, reg, tmp_path)

    mock_cal.assert_not_called()


@pytest.mark.asyncio
async def test_uncalibrated_models_detected(tmp_path):
    cfg = _make_cfg(["model-a", "model-b"])
    reg = _make_registry(tmp_path, {
        "model-a": ModelProfileRecord(base_residency_mb=5000, residency_source="calibrated"),
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


def test_auto_calibrate_models_calls_calibrate_for_each(tmp_path):
    config_path = _write_config(tmp_path, ["model-a", "model-b"])
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    side = {"model-a": _success_result("model-a"), "model-b": _success_result("model-b")}

    with patch("logos_worker_node.calibration.calibrate_model") as mock_cm:
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
         patch("logos_worker_node.calibration.save_profiles") as mock_save:
        mock_cm.side_effect = lambda plan, **kw: side[plan["model"]]
        auto_calibrate_models(["model-a", "model-b"], config_path, state_dir)

    assert mock_save.call_count == 2


def test_auto_calibrate_models_continues_on_failure(tmp_path):
    config_path = _write_config(tmp_path, ["model-a", "model-b"])
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    side = {"model-a": _fail_result("model-a"), "model-b": _success_result("model-b")}

    with patch("logos_worker_node.calibration.calibrate_model") as mock_cm:
        mock_cm.side_effect = lambda plan, **kw: side[plan["model"]]
        results = auto_calibrate_models(
            ["model-a", "model-b"], config_path, state_dir,
        )

    assert mock_cm.call_count == 2
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

    with patch("logos_worker_node.calibration.calibrate_model") as mock_cm:
        mock_cm.return_value = _success_result("model-b")
        results = auto_calibrate_models(
            ["model-b"], config_path, state_dir,
        )

    assert mock_cm.call_count == 1
    plan_arg = mock_cm.call_args[0][0]
    assert plan_arg["model"] == "model-b"
    assert "model-a" not in results


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

    with patch("logos_worker_node.main.load_config", return_value=cfg), \
         patch("logos_worker_node.main.get_state_dir", return_value=tmp_path), \
         patch("logos_worker_node.main.GpuMetricsCollector", return_value=mock_gpu), \
         patch("logos_worker_node.main.ModelProfileRegistry") as mock_reg_cls, \
         patch("logos_worker_node.main._auto_calibrate_if_needed", new_callable=AsyncMock) as mock_autocal, \
         patch("logos_worker_node.main.LaneManager") as mock_lm_cls, \
         patch("logos_worker_node.main.LogosBridgeClient", return_value=mock_bridge), \
         patch.dict("sys.modules", {"logos_worker_node.flashinfer_warmup": MagicMock()}):

        mock_reg = MagicMock()
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
    plan = {"model": model}
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

    # spawn_vllm → returns a mock Popen
    mock_popen = MagicMock()
    mock_popen.pid = 12345
    mock_popen.poll.return_value = None
    patches["spawn"] = patch(
        "logos_worker_node.calibration.spawn_vllm", return_value=mock_popen
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

    return patches


def _run_calibrate(patches, plan=None, kv_cache_memory_bytes=_DEFAULT_KV_CACHE):
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
            kv_cache_memory_bytes=kv_cache_memory_bytes,
        )
    finally:
        for p in patches.values():
            p.__exit__(None, None, None)

    return result, managers


def test_kv_search_succeeds_after_retries():
    """KV cache search finds a working size via binary search after failures."""
    # Default 4G on 24GB GPU (cap=19200 MB).
    # 4G (4096) fails → binary mid ~12G (12288) → succeeds
    patches = _patch_calibration_infra(
        wait_ready_side_effect=[
            RuntimeError("vLLM exited (code=1)"),
            None,  # success on 2nd attempt (midpoint)
        ],
        sample_vram_sequence=[500.0, 12500.0, 600.0],  # baseline, awake, sleeping
    )

    result, mocks = _run_calibrate(patches)

    assert result.success
    # Binary search: mid(4096, 19200) = 11648 → rounded up to 12G = 12288
    assert result.kv_cache_sent_mb == pytest.approx(12288.0)
    assert mocks["spawn"].call_count == 2


def test_kv_search_gives_up_at_vram_cap():
    """KV cache search stops when the range narrows below the minimum step."""
    total_gpu_mb = 10000.0  # 80% cap = 8000 MB
    # Start at 7G (7168 MB), cap = 8000. Gap = 832 MB < 1024 min step → give up
    patches = _patch_calibration_infra(
        wait_ready_side_effect=[RuntimeError("vLLM exited (code=1)")],
        gpu_vram_total_mb=total_gpu_mb,
    )

    result, mocks = _run_calibrate(patches, kv_cache_memory_bytes="7G")

    assert not result.success
    assert "KV cache search exhausted" in result.error
    assert "80%" in result.error


def test_kv_search_manual_override_as_starting_point():
    """Manual kv_cache_memory_bytes override is used as the search starting point."""
    # Plan has kv_cache_memory_bytes=2G on 24GB GPU (cap=19200).
    # 2G fails → binary mid(2048,19200)=10624→round up 11G(11264) → succeeds
    patches = _patch_calibration_infra(
        wait_ready_side_effect=[
            RuntimeError("vLLM exited (code=1)"),
            None,  # success at midpoint
        ],
        sample_vram_sequence=[500.0, 12000.0, 700.0],
    )

    plan = _make_plan(kv_cache_memory_bytes="2G")
    result, mocks = _run_calibrate(patches, plan=plan)

    assert result.success
    assert result.kv_cache_sent_mb == pytest.approx(11264.0)  # 11G


def test_kv_search_discovered_value_in_profile():
    """The discovered KV cache size is stored in the calibration profile."""
    # Use explicit 2G start on 24GB GPU so binary search is predictable:
    # 2G fails → mid(2048,19200)=10624→round up 11G(11264) → succeeds
    patches = _patch_calibration_infra(
        wait_ready_side_effect=[
            RuntimeError("vLLM exited (code=1)"),
            None,  # success at midpoint
        ],
        sample_vram_sequence=[500.0, 12000.0, 600.0],
    )

    result, _ = _run_calibrate(patches, kv_cache_memory_bytes="2G")

    assert result.success
    assert result.kv_cache_sent_mb == pytest.approx(11264.0)  # 11G

    profile = result_to_profile_dict(result)
    assert profile["calibration_kv_cache_memory_bytes"] == "11G"
    assert profile["_calibration_kv_cache_mb"] == pytest.approx(11264.0)
    assert profile["kv_budget_mb"] == pytest.approx(11264.0)


def test_kv_search_first_attempt_succeeds():
    """When the default KV cache works, no retry happens."""
    patches = _patch_calibration_infra(
        wait_ready_side_effect=[None],  # success on first try
        sample_vram_sequence=[500.0, 7500.0, 600.0],
    )

    result, mocks = _run_calibrate(patches)

    assert result.success
    assert result.kv_cache_sent_mb == pytest.approx(4096.0)  # 4G default
    assert mocks["spawn"].call_count == 1


def test_kv_search_timeout_not_retried():
    """TimeoutError (vLLM loaded but warmup slow) should NOT trigger retry."""
    patches = _patch_calibration_infra(
        wait_ready_side_effect=[TimeoutError("vLLM not ready after 60s")],
    )

    result, mocks = _run_calibrate(patches)

    assert not result.success
    assert "not ready after" in result.error
    # Only one spawn attempt — no retry on timeout
    assert mocks["spawn"].call_count == 1


def test_kv_search_binary_narrows_to_cap():
    """Binary KV search narrows the range until gap < min step, then gives up."""
    total_gpu_mb = 8000.0  # 80% cap = 6400 MB
    # Start at 4G (4096), cap = 6400.
    # 4G fails → mid(4096,6400)=5248→round up 6G(6144) → fails → gap 6144–6400=256 < 1024 → give up
    patches = _patch_calibration_infra(
        wait_ready_side_effect=[
            RuntimeError("fail"),
            RuntimeError("fail"),
        ],
        gpu_vram_total_mb=total_gpu_mb,
    )

    result, mocks = _run_calibrate(patches)

    assert not result.success
    assert "KV cache search exhausted" in result.error
    assert mocks["spawn"].call_count == 2


def test_calibration_output_honored_on_startup(tmp_path):
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
        asyncio.get_event_loop().run_until_complete(
            worker_main._auto_calibrate_if_needed(cfg, reg, tmp_path)
        )

    # Already calibrated → no recalibration
    mock_cal.assert_not_called()


def test_profile_dict_has_calibration_kv_field():
    """result_to_profile_dict includes calibration_kv_cache_memory_bytes."""
    r = _success_result("org/my-model", kv_cache_sent_mb=5120.0)
    d = result_to_profile_dict(r)

    assert "calibration_kv_cache_memory_bytes" in d
    assert d["calibration_kv_cache_memory_bytes"] == "5G"
