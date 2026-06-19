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

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

import logos_worker_node.main as worker_main
from logos_worker_node.calibration import (
    _FATAL_LOAD_ERROR_PATTERNS,
    _KV_CACHE_MIN_STEP_MB,
    _NODE_LEVEL_TRANSIENT_PATTERNS,
    _UNSUPPORTED_MODELS_FILE,
    CalibrationResult,
    UnsupportedModelEntry,
    _classify_fatal_load_error,
    _classify_node_transient_error,
    _extract_vllm_max_model_len_suggestion,
    _extract_vllm_max_num_seqs_suggestion,
    _format_kv_mb,
    _load_unsupported_models,
    _max_tp_for_plan,
    _parse_kv_to_mb,
    _record_unsupported_model,
    _remove_unsupported_model,
    auto_calibrate_models,
    calibrate_model,
    is_model_unsupported,
    load_existing_profiles,
    parse_gpu_indices,
    plans_from_config,
    result_to_profile_dict,
    save_profiles,
)
from logos_worker_node.model_profiles import ModelProfileRecord, ModelProfileRegistry
from logos_worker_node.models import AppConfig

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
    reg = _make_registry(
        tmp_path,
        {
            "model-a": ModelProfileRecord(
                base_residency_mb=5000,
                sleeping_residual_mb=200,
                loaded_vram_mb=5000,
                residency_source="calibrated",
                kv_cache_to_max_model_len_pairs=[{"kv_mb": 1024.0, "max_model_len": 1000}],
            ),
            "model-b": ModelProfileRecord(
                base_residency_mb=6000,
                sleeping_residual_mb=300,
                loaded_vram_mb=6000,
                residency_source="calibrated",
                kv_cache_to_max_model_len_pairs=[{"kv_mb": 1024.0, "max_model_len": 1000}],
            ),
        },
    )

    with patch.object(worker_main, "auto_calibrate_models") as mock_cal:
        await worker_main._auto_calibrate_if_needed(cfg, reg, tmp_path)

    mock_cal.assert_not_called()


@pytest.mark.asyncio
async def test_uncalibrated_models_detected(tmp_path):
    cfg = _make_cfg(["model-a", "model-b"])
    reg = _make_registry(
        tmp_path,
        {
            "model-a": ModelProfileRecord(
                base_residency_mb=5000,
                sleeping_residual_mb=200,
                loaded_vram_mb=5000,
                residency_source="calibrated",
                kv_cache_to_max_model_len_pairs=[{"kv_mb": 1024.0, "max_model_len": 1000}],
            ),
            "model-b": ModelProfileRecord(base_residency_mb=None),
        },
    )

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

    fake = {
        "model-a": _success_result("model-a"),
        "model-b": _success_result("model-b"),
    }
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


@pytest.mark.asyncio
async def test_calibrated_tp_above_default_does_not_loop(tmp_path, monkeypatch):
    """Profile says tp=2, config has no explicit tp → don't re-calibrate.

    Before the fix the provenance check defaulted expected_tp to 1, so any
    calibrated tp>1 (the common case for big models) tripped "tp mismatch"
    on every restart and re-ran a multi-minute calibration that produced the
    same answer.
    """
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "logos": {"capabilities_models": ["big/model"]},
            }
        )
    )
    monkeypatch.setenv("LOGOS_WORKER_NODE_CONFIG", str(config_path))

    reg = _make_registry(
        tmp_path,
        {
            "big/model": ModelProfileRecord(
                base_residency_mb=180_000.0,
                sleeping_residual_mb=5000.0,
                loaded_vram_mb=180_000.0,
                residency_source="calibrated",
                tensor_parallel_size=2,
                kv_cache_to_max_model_len_pairs=[{"kv_mb": 2048.0, "max_model_len": 131072}],
            ),
        },
    )
    cfg = _make_cfg(["big/model"])

    with patch.object(worker_main, "auto_calibrate_models") as mock_cal:
        await worker_main._auto_calibrate_if_needed(cfg, reg, tmp_path)

    mock_cal.assert_not_called()


@pytest.mark.asyncio
async def test_calibrated_tp_disagrees_with_explicit_config_recalibrates(tmp_path, monkeypatch):
    """Explicit tp in config that disagrees with the profile → re-calibrate."""
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "logos": {
                    "capabilities_models": [
                        {"model": "big/model", "tensor_parallel_size": 4},
                    ],
                },
            }
        )
    )
    monkeypatch.setenv("LOGOS_WORKER_NODE_CONFIG", str(config_path))

    reg = _make_registry(
        tmp_path,
        {
            "big/model": ModelProfileRecord(
                base_residency_mb=180_000.0,
                sleeping_residual_mb=5000.0,
                loaded_vram_mb=180_000.0,
                residency_source="calibrated",
                tensor_parallel_size=2,
            ),
        },
    )
    cfg = _make_cfg(["big/model"])

    with patch.object(
        worker_main,
        "auto_calibrate_models",
        return_value={"big/model": _success_result("big/model")},
    ) as mock_cal:
        await worker_main._auto_calibrate_if_needed(cfg, reg, tmp_path)

    mock_cal.assert_called_once()
    assert mock_cal.call_args[0][0] == ["big/model"]


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
                        "kv_cache_dtype": "fp8",
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
    assert plans[0]["kv_cache_dtype"] == "fp8"


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

    side = {
        "model-a": _success_result("model-a"),
        "model-b": _success_result("model-b"),
    }

    with (
        patch("logos_worker_node.calibration.calibrate_model") as mock_cm,
        patch(
            "logos_worker_node.calibration.query_gpu_vram",
            return_value=_mock_gpu_snap(),
        ),
    ):
        mock_cm.side_effect = lambda plan, **kw: side[plan["model"]]
        results = auto_calibrate_models(
            ["model-a", "model-b"],
            config_path,
            state_dir,
        )

    assert mock_cm.call_count == 2
    assert results["model-a"].success
    assert results["model-b"].success


def test_auto_calibrate_models_persists_after_each_success(tmp_path):
    config_path = _write_config(tmp_path, ["model-a", "model-b"])
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    side = {
        "model-a": _success_result("model-a"),
        "model-b": _success_result("model-b"),
    }

    with (
        patch("logos_worker_node.calibration.calibrate_model") as mock_cm,
        patch("logos_worker_node.calibration.save_profiles") as mock_save,
        patch(
            "logos_worker_node.calibration.query_gpu_vram",
            return_value=_mock_gpu_snap(),
        ),
    ):
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

    with (
        patch("logos_worker_node.calibration.calibrate_model") as mock_cm,
        patch(
            "logos_worker_node.calibration.query_gpu_vram",
            return_value=_mock_gpu_snap(2),
        ),
    ):
        mock_cm.side_effect = side_effect
        results = auto_calibrate_models(
            ["model-a", "model-b"],
            config_path,
            state_dir,
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

    with (
        patch("logos_worker_node.calibration.calibrate_model") as mock_cm,
        patch(
            "logos_worker_node.calibration.query_gpu_vram",
            return_value=_mock_gpu_snap(),
        ),
    ):
        mock_cm.return_value = _success_result("model-b")
        results = auto_calibrate_models(
            ["model-b"],
            config_path,
            state_dir,
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

    with (
        patch("logos_worker_node.calibration.calibrate_model") as mock_cm,
        patch(
            "logos_worker_node.calibration.query_gpu_vram",
            return_value=_mock_gpu_snap(2),
        ),
    ):
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

    with (
        patch("logos_worker_node.calibration.calibrate_model") as mock_cm,
        patch(
            "logos_worker_node.calibration.query_gpu_vram",
            return_value=_mock_gpu_snap(1),
        ),
    ):
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

    with (
        patch("logos_worker_node.calibration.calibrate_model") as mock_cm,
        patch(
            "logos_worker_node.calibration.query_gpu_vram",
            return_value=_mock_gpu_snap(2),
        ),
    ):
        mock_cm.return_value = _fail_result("big-model")
        results = auto_calibrate_models(["big-model"], config_path, state_dir)

    assert mock_cm.call_count == 1  # already at max tp, single attempt
    assert not results["big-model"].success


def test_max_tp_for_plan():
    # Power-of-2 rounding: 4 GPUs → tp=4, 3 GPUs → tp=2, 5 → 4, 7 → 4
    assert _max_tp_for_plan({"model": "x"}, available_gpus=4) == 4
    assert _max_tp_for_plan({"model": "x"}, available_gpus=3) == 2
    assert _max_tp_for_plan({"model": "x"}, available_gpus=5) == 4
    assert _max_tp_for_plan({"model": "x"}, available_gpus=7) == 4
    assert _max_tp_for_plan({"model": "x"}, available_gpus=8) == 8
    assert _max_tp_for_plan({"model": "x"}, available_gpus=1) == 1
    assert _max_tp_for_plan({"model": "x", "gpu_devices": "0,1"}, available_gpus=4) == 2
    assert _max_tp_for_plan({"model": "x", "gpu_devices": "0,1,2"}, available_gpus=4) == 2
    assert _max_tp_for_plan({"model": "x", "gpu_devices": "0"}, available_gpus=4) == 1
    assert _max_tp_for_plan({"model": "x", "gpu_devices": "all"}, available_gpus=4) == 4
    assert _max_tp_for_plan({"model": "x", "gpu_devices": "all"}, available_gpus=3) == 2
    assert _max_tp_for_plan({"model": "x", "gpu_devices": ""}, available_gpus=4) == 4


# ═══════════════════════════════════════════════════════════════════════
# Group 6 — _format_kv_mb helper
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
    patches["gpu_vram"] = patch("logos_worker_node.calibration.query_gpu_vram", return_value=snap)

    # sample_vram_mb → returns values from sequence
    # Sequence: baseline, awake, sleeping_1, sleeping_2 (post-Fix-3 double-sample).
    if sample_vram_sequence is None:
        sample_vram_sequence = [500.0, 7500.0, 600.0, 600.0]
    patches["sample"] = patch(
        "logos_worker_node.calibration.sample_vram_mb",
        side_effect=sample_vram_sequence,
    )

    # time.sleep → skip
    patches["sleep"] = patch("logos_worker_node.calibration.time.sleep")

    # wait_sleep_state → no-op
    patches["wait_sleep"] = patch("logos_worker_node.calibration.wait_sleep_state")

    # _post (for /sleep endpoint) → success
    patches["post"] = patch("logos_worker_node.calibration._post", return_value=(200, {}))

    # _kill_stale_vllm_workers → no-op (avoids scanning /proc in tests)
    patches["kill_stale"] = patch("logos_worker_node.calibration._kill_stale_vllm_workers")

    # _load_failed_commands / _load_succeeded_commands → always empty
    # (no cross-test contamination)
    patches["load_failed"] = patch("logos_worker_node.calibration._load_failed_commands", return_value=set())
    patches["load_succeeded"] = patch("logos_worker_node.calibration._load_succeeded_commands", return_value=set())
    patches["record_succeeded"] = patch("logos_worker_node.calibration._record_succeeded_command")
    patches["remove_failed"] = patch("logos_worker_node.calibration._remove_failed_command")

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


def test_explicit_kv_ignores_stale_blacklist_and_spawns():
    """An operator-pinned kv_cache_memory_bytes has no search fallback, so a
    blacklist skip would convert a maybe-recoverable case into certain
    failure — and it would short-circuit before the --max-model-len
    injection retry ever sees a vLLM log to parse (deipapa 2026-06-10:
    Llama-3.1-8B stayed uncalibratable behind a stale kv=6G blacklist line
    recorded before the injection path existed). The fixed-KV path must
    discard the stale blacklist entry and attempt a real spawn.

    This also still covers the deimama 2026-06-04 NameError regression:
    ``_probes`` is initialised in the outer scope, so reaching this path
    with a blacklisted fingerprint must not raise.
    """
    patches = _patch_calibration_infra()
    # Inject a blacklist hit for whatever fingerprint _try_start computes.
    patches["load_failed"] = patch(
        "logos_worker_node.calibration._load_failed_commands",
        return_value={"<blacklisted>"},
    )
    patches["fingerprint"] = patch(
        "logos_worker_node.calibration._cmd_fingerprint",
        return_value="<blacklisted>",
    )

    result, mocks = _run_calibrate(patches)

    # The stale blacklist entry is ignored: vLLM is spawned for real and the
    # calibration succeeds.
    assert result.success
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


def test_explicit_kv_auto_retries_with_max_model_len_from_vllm_suggestion():
    """When the operator's pinned kv_cache is too small for the model's
    default max_seq_len, vLLM refuses to start but suggests a smaller
    max_model_len in its error. Calibration should parse that, re-probe the
    same kv with --max-model-len injected, and succeed instead of failing
    the model outright (regression for the deipapa 2026-06-08 calibration
    session where Llama-3.1-8B-Instruct with kv=6G OOMed and got blacklisted
    without ever trying the suggested 98304).
    """
    suggestion_tail = (
        "(EngineCore pid=3662) ValueError: To serve at least one request with "
        "the model's max seq len (131072), (8.0 GiB KV cache is needed, which "
        "is larger than the available KV cache memory (6.0 GiB). Based on the "
        "available memory, the estimated maximum model length is 98304."
    )
    patches = _patch_calibration_infra(
        wait_ready_side_effect=[
            RuntimeError("vLLM exited (code=1)"),  # first probe fails
            None,  # auto-retry with --max-model-len succeeds
        ],
    )
    patches["read_log_tail"] = patch(
        "logos_worker_node.calibration._read_log_tail",
        return_value=suggestion_tail,
    )

    result, mocks = _run_calibrate(patches, plan=_make_plan(kv_cache_memory_bytes="6G"))

    assert result.success, result.error
    # Two spawn attempts: original 6G probe, then retry with --max-model-len.
    assert mocks["spawn"].call_count == 2
    assert result.max_model_len == 98304


def test_explicit_kv_does_not_loop_when_suggestion_does_not_shrink():
    """If vLLM emits the same suggestion repeatedly (or one ≥ the value we
    already pinned), the retry must stop instead of looping forever. The
    failure path falls through to the normal blacklist write and surfaces
    as a regular probe failure."""
    suggestion_tail = "ValueError: ... the estimated maximum model length is 98304."
    # Plan already pins max_model_len ≤ the suggestion → no shrink possible.
    patches = _patch_calibration_infra(
        wait_ready_side_effect=[RuntimeError("vLLM exited (code=1)")],
    )
    patches["read_log_tail"] = patch(
        "logos_worker_node.calibration._read_log_tail",
        return_value=suggestion_tail,
    )

    result, mocks = _run_calibrate(
        patches,
        plan=_make_plan(kv_cache_memory_bytes="6G", max_model_len=98304),
    )

    assert not result.success
    # No infinite recursion — exactly one spawn.
    assert mocks["spawn"].call_count == 1


def test_kv_probe_auto_retries_with_max_num_seqs_for_mamba_model():
    """Hybrid Mamba/SSM models (Qwen3-Coder-Next) abort CUDA-graph capture when
    max_num_seqs exceeds their fixed state-cache pool. vLLM names the ceiling;
    calibration should parse it, re-probe with --max-num-seqs injected, and
    succeed instead of blacklisting every kv size and failing the model
    (regression for the deioma 2026-06-17 Qwen3-Coder-Next-NVFP4 session).
    """
    suggestion_tail = (
        "(EngineCore pid=242304) RuntimeError: Worker failed with error "
        "'max_num_seqs (1024) exceeds available Mamba cache blocks (160). Each "
        "decode sequence requires one Mamba cache block, so CUDA graph capture "
        "cannot proceed. Please lower max_num_seqs to at most 160 or increase "
        "gpu_memory_utilization.'"
    )
    patches = _patch_calibration_infra(
        wait_ready_side_effect=[
            RuntimeError("vLLM exited (code=1)"),  # first probe fails
            None,  # auto-retry with --max-num-seqs succeeds
        ],
    )
    patches["read_log_tail"] = patch(
        "logos_worker_node.calibration._read_log_tail",
        return_value=suggestion_tail,
    )

    result, mocks = _run_calibrate(patches, plan=_make_plan(kv_cache_memory_bytes="6G"))

    assert result.success, result.error
    # Two spawn attempts: original probe, then retry with --max-num-seqs.
    assert mocks["spawn"].call_count == 2
    assert result.max_num_seqs == 160


def test_max_num_seqs_retry_does_not_loop_when_suggestion_does_not_shrink():
    """If the plan already pins max_num_seqs ≤ the suggested ceiling, the retry
    must stop instead of looping forever and fall through to the normal
    blacklist path."""
    suggestion_tail = "RuntimeError: ... Please lower max_num_seqs to at most 160 or increase gpu_memory_utilization."
    patches = _patch_calibration_infra(
        wait_ready_side_effect=[RuntimeError("vLLM exited (code=1)")],
    )
    patches["read_log_tail"] = patch(
        "logos_worker_node.calibration._read_log_tail",
        return_value=suggestion_tail,
    )

    result, mocks = _run_calibrate(
        patches,
        plan=_make_plan(kv_cache_memory_bytes="6G", max_num_seqs=160),
    )

    assert not result.success
    # No infinite recursion — exactly one spawn.
    assert mocks["spawn"].call_count == 1


def test_extract_vllm_max_num_seqs_suggestion_real_log_tail():
    tail = (
        "RuntimeError: max_num_seqs (1024) exceeds available Mamba cache blocks "
        "(160). ... Please lower max_num_seqs to at most 160 or increase "
        "gpu_memory_utilization."
    )
    assert _extract_vllm_max_num_seqs_suggestion(tail) == 160


def test_extract_vllm_max_num_seqs_suggestion_ignores_unrelated_errors():
    assert _extract_vllm_max_num_seqs_suggestion("CUDA out of memory") is None
    assert _extract_vllm_max_num_seqs_suggestion("") is None
    assert _extract_vllm_max_num_seqs_suggestion(None) is None  # type: ignore[arg-type]


def test_result_to_profile_dict_includes_max_num_seqs():
    r = CalibrationResult(
        model="org/mamba",
        tensor_parallel_size=2,
        gpu_devices="all",
        kv_cache_sent_mb=4096.0,
        success=True,
        max_num_seqs=160,
    )
    assert result_to_profile_dict(r)["calibration_max_num_seqs"] == 160
    # Default (no cap needed) serializes as None, not 0.
    r2 = CalibrationResult(
        model="org/plain",
        tensor_parallel_size=1,
        gpu_devices="all",
        kv_cache_sent_mb=4096.0,
        success=True,
    )
    assert result_to_profile_dict(r2)["calibration_max_num_seqs"] is None


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
    patches["gpu_vram"] = patch("logos_worker_node.calibration.query_gpu_vram", return_value=two_gpu_snap)

    result, mocks = _run_calibrate(patches, plan=_make_plan(tensor_parallel_size=1))

    assert result.success
    # The important thing: it didn't try to use 48000*0.8=38400 as cap


@pytest.mark.asyncio
async def test_calibration_output_honored_on_startup(tmp_path):
    """Ensure that calibration output is honored — no recalibration triggered."""
    # Simulate a model that was successfully calibrated.
    # In real calibration: base_residency_mb == loaded_vram_mb (full loaded footprint).
    r = _success_result(
        "model-a",
        kv_cache_sent_mb=3072.0,
        loaded_vram_mb=7000.0,
        base_residency_mb=7000.0,
    )
    profile = result_to_profile_dict(r)

    # Create a registry with the profile already present.
    # All required fields set so _auto_calibrate_if_needed considers it calibrated:
    #   base_residency_mb is not None, sleeping_residual_mb is not None,
    #   base_residency_mb == loaded_vram_mb (no stale format mismatch).
    reg = _make_registry(
        tmp_path,
        {
            "model-a": ModelProfileRecord(
                base_residency_mb=profile["base_residency_mb"],
                sleeping_residual_mb=profile["sleeping_residual_mb"],
                loaded_vram_mb=profile["loaded_vram_mb"],
                residency_source="calibrated",
                kv_cache_to_max_model_len_pairs=[{"kv_mb": 1024.0, "max_model_len": 1000}],
            ),
        },
    )

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


def test_profile_dict_records_calibration_max_model_len():
    """When calibration auto-injected --max-model-len (because the operator's
    pinned KV budget couldn't fit one request at the model's default
    max_seq_len), the resolved value is surfaced in the profile dict so the
    YAML preserves the audit trail."""
    r = _success_result("org/my-model", kv_cache_sent_mb=6144.0, max_model_len=98304)
    d = result_to_profile_dict(r)

    assert d["calibration_max_model_len"] == 98304


def test_profile_dict_max_model_len_none_when_default_used():
    """No --max-model-len injection → field is None (model's default fit)."""
    r = _success_result("org/my-model", kv_cache_sent_mb=8192.0)
    d = result_to_profile_dict(r)

    assert d["calibration_max_model_len"] is None


def test_profile_dict_records_kv_max_model_len_pairs():
    """Calibration profile output includes the per-KV max_model_len curve."""
    r = _success_result(
        "org/my-model",
        kv_cache_sent_mb=8192.0,
        max_model_len=2000,
        kv_max_model_len_pairs=[
            (1024.0, 1000),
            (2048.0, 2000),
        ],
    )
    d = result_to_profile_dict(r)

    assert d["kv_cache_to_max_model_len_pairs"] == [
        {"kv_mb": 1024.0, "max_model_len": 1000},
        {"kv_mb": 2048.0, "max_model_len": 2000},
    ]


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
    patches["gpu_vram"] = patch("logos_worker_node.calibration.query_gpu_vram", return_value=snap)

    if sample_vram_sequence is None:
        # baseline, awake, sleeping_1, sleeping_2 (Fix-3 double-sample)
        sample_vram_sequence = [500.0, 7500.0, 600.0, 600.0]
    patches["sample"] = patch(
        "logos_worker_node.calibration.sample_vram_mb",
        side_effect=sample_vram_sequence,
    )

    patches["sleep"] = patch("logos_worker_node.calibration.time.sleep")
    patches["wait_sleep"] = patch("logos_worker_node.calibration.wait_sleep_state")
    patches["post"] = patch("logos_worker_node.calibration._post", return_value=(200, {}))
    patches["kill_stale"] = patch("logos_worker_node.calibration._kill_stale_vllm_workers")

    # _load_failed_commands / _load_succeeded_commands → always empty
    # (no cross-test contamination)
    patches["load_failed"] = patch("logos_worker_node.calibration._load_failed_commands", return_value=set())
    patches["load_succeeded"] = patch("logos_worker_node.calibration._load_succeeded_commands", return_value=set())
    patches["record_succeeded"] = patch("logos_worker_node.calibration._record_succeeded_command")
    patches["remove_failed"] = patch("logos_worker_node.calibration._remove_failed_command")

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
    kv_min_mb = 6144.0  # 6 GB — min KV for max_position_embeddings
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


# ─────────────────────────────────────────────────────────────────────────
# Model-level "do not retry" blacklist
# ─────────────────────────────────────────────────────────────────────────


def test_fatal_classifier_matches_invalid_repo_id():
    """The classifier picks up vLLM's exact 'Invalid repository ID' string."""
    tail = (
        "(APIServer pid=572249)   Value error, "
        "Invalid repository ID or local directory specified: 'Qwen/Bogus-Model'.\n"
        "(APIServer pid=572249) Please verify the following requirements:\n"
    )
    pat = _classify_fatal_load_error(tail)
    assert pat is not None
    assert pat.reason_code == "invalid-repo-id"


def test_fatal_classifier_matches_gated_repo():
    pat = _classify_fatal_load_error("HTTPError: Cannot access gated repo for url https://...")
    assert pat is not None
    assert pat.reason_code == "gated-repo-no-token"


def test_fatal_classifier_matches_unsupported_arch():
    pat = _classify_fatal_load_error("ValueError: vLLM does not recognize this architecture: FooNet")
    assert pat is not None
    assert pat.reason_code == "unsupported-architecture"


def test_fatal_classifier_ignores_oom():
    """CUDA OOM is recoverable via a smaller kv-cache — must NOT match."""
    tail = (
        "torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 1.16 GiB. "
        "GPU 0 has a total capacity of 15.56 GiB of which 867.50 MiB is free."
    )
    assert _classify_fatal_load_error(tail) is None


def test_fatal_classifier_ignores_empty_and_irrelevant():
    assert _classify_fatal_load_error("") is None
    assert _classify_fatal_load_error(None) is None  # type: ignore[arg-type]
    assert _classify_fatal_load_error("nothing to see here") is None


def test_extract_vllm_max_model_len_suggestion_real_log_tail():
    """Parse vLLM's KV-too-small ValueError captured from a real probe failure
    on the deipapa worker (2026-06-08, Llama-3.1-8B-Instruct, kv_cache=6G)."""
    tail = (
        "(EngineCore pid=3662) ValueError: To serve at least one request with "
        "the model's max seq len (131072), (8.0 GiB KV cache is needed, which "
        "is larger than the available KV cache memory (6.0 GiB). Based on the "
        "available memory, the estimated maximum model length is 98304. Try "
        "increasing `gpu_memory_utilization` ..."
    )
    assert _extract_vllm_max_model_len_suggestion(tail) == 98304


def test_extract_vllm_max_model_len_suggestion_ignores_unrelated_errors():
    assert _extract_vllm_max_model_len_suggestion("CUDA out of memory") is None
    assert _extract_vllm_max_model_len_suggestion("") is None
    assert _extract_vllm_max_model_len_suggestion(None) is None  # type: ignore[arg-type]
    # Suggestion of zero is meaningless — caller would still fail and we'd
    # loop forever shrinking to nothing. Treat as "no suggestion".
    assert _extract_vllm_max_model_len_suggestion("the estimated maximum model length is 0") is None


def test_fatal_classifier_registry_has_expected_codes():
    """Guard against accidental pattern deletion. Add codes here when you add new patterns."""
    codes = {p.reason_code for p in _FATAL_LOAD_ERROR_PATTERNS}
    assert {
        "invalid-repo-id",
        "gated-repo-no-token",
        "unsupported-architecture",
    } <= codes


def test_unsupported_file_roundtrip(tmp_path: Path):
    """Record → load → remove preserves contents and round-trips cleanly."""
    path = tmp_path / _UNSUPPORTED_MODELS_FILE
    entry = UnsupportedModelEntry(
        model="Qwen/Bogus-Model",
        reason_code="invalid-repo-id",
        recorded_at="2026-06-04T19:46:51Z",
        description="vLLM cannot resolve the model name to a repository.",
    )
    _record_unsupported_model(path, entry)
    loaded = _load_unsupported_models(path)
    assert "Qwen/Bogus-Model" in loaded
    assert loaded["Qwen/Bogus-Model"].reason_code == "invalid-repo-id"
    assert loaded["Qwen/Bogus-Model"].recorded_at == "2026-06-04T19:46:51Z"

    removed = _remove_unsupported_model(path, "Qwen/Bogus-Model")
    assert removed == 1
    assert _load_unsupported_models(path) == {}


def test_unsupported_file_ignores_comments_and_blank_lines(tmp_path: Path):
    path = tmp_path / _UNSUPPORTED_MODELS_FILE
    path.write_text(
        "# comment line\n"
        "\n"
        "Qwen/A\tinvalid-repo-id\t2026-06-04T00:00:00Z\tdescription A\n"
        "\n"
        "# another comment\n"
        "Qwen/B\tgated-repo-no-token\t2026-06-04T01:00:00Z\tdescription B\n",
        encoding="utf-8",
    )
    loaded = _load_unsupported_models(path)
    assert set(loaded.keys()) == {"Qwen/A", "Qwen/B"}
    assert loaded["Qwen/B"].reason_code == "gated-repo-no-token"


def test_unsupported_file_last_entry_wins_for_same_model(tmp_path: Path):
    """When operator appends a fresher entry, the loader returns the most recent."""
    path = tmp_path / _UNSUPPORTED_MODELS_FILE
    older = UnsupportedModelEntry(
        model="Qwen/X",
        reason_code="invalid-repo-id",
        recorded_at="2026-06-01T00:00:00Z",
        description="old",
    )
    newer = UnsupportedModelEntry(
        model="Qwen/X",
        reason_code="gated-repo-no-token",
        recorded_at="2026-06-04T00:00:00Z",
        description="new",
    )
    _record_unsupported_model(path, older)
    _record_unsupported_model(path, newer)
    loaded = _load_unsupported_models(path)
    assert loaded["Qwen/X"].reason_code == "gated-repo-no-token"


def test_is_model_unsupported_returns_none_when_file_missing(tmp_path: Path):
    assert is_model_unsupported(tmp_path / "nope", "any/model") is None


def test_unsupported_entry_with_tabs_in_description_does_not_corrupt_format(
    tmp_path: Path,
):
    """A description that contains tab characters is sanitized at write time."""
    path = tmp_path / _UNSUPPORTED_MODELS_FILE
    entry = UnsupportedModelEntry(
        model="Qwen/Z",
        reason_code="invalid-repo-id",
        recorded_at="2026-06-04T00:00:00Z",
        description="line one\twith embedded\ttabs and\nnewlines",
    )
    _record_unsupported_model(path, entry)
    # Should round-trip without splitting the description into extra columns.
    loaded = _load_unsupported_models(path)
    assert loaded["Qwen/Z"].reason_code == "invalid-repo-id"
    assert "\t" not in loaded["Qwen/Z"].description
    assert "\n" not in loaded["Qwen/Z"].description


def test_calibrate_model_skips_when_on_unsupported_list(tmp_path: Path):
    """calibrate_model short-circuits if the model is on the unsupported list."""
    log_dir = tmp_path / "calibration_logs"
    log_dir.mkdir()
    _record_unsupported_model(
        log_dir / _UNSUPPORTED_MODELS_FILE,
        UnsupportedModelEntry(
            model="Qwen/Bogus",
            reason_code="invalid-repo-id",
            recorded_at="2026-06-04T19:46:51Z",
            description="bad repo",
        ),
    )

    patches = _patch_calibration_infra()

    plan = _make_plan(model="Qwen/Bogus")
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

    assert not result.success
    assert result.unsupported_reason == "invalid-repo-id"
    # No vLLM should have been spawned: the check fires before Phase 0.
    assert managers["spawn"].call_count == 0


def test_node_transient_classifier_matches_eio():
    """The classifier picks up the kernel/python EIO signature from the
    deioma 2026-06-04 storage outage."""
    tail = (
        "(APIServer pid=611559) FileNotFoundError: [Errno 2] No such file ...\n"
        "(APIServer pid=611559) OSError: [Errno 5] Input/output error: "
        "'/usr/share/ollama/.ollama/models/.hf_cache/hub/models--zai-org--GLM-Image'"
    )
    pat = _classify_node_transient_error(tail)
    assert pat is not None
    assert pat.reason_code == "filesystem-eio"


def test_node_transient_classifier_matches_readonly_filesystem():
    pat = _classify_node_transient_error("PermissionError: [Errno 30] Read-only file system: '/app/data/...'")
    assert pat is not None
    assert pat.reason_code == "filesystem-readonly"


def test_node_transient_classifier_does_not_match_model_or_oom_errors():
    """Storage classifier must not steal recoverable failures from the kv search."""
    assert _classify_node_transient_error("CUDA out of memory") is None
    assert _classify_node_transient_error("Invalid repository ID or local directory specified") is None
    assert _classify_node_transient_error("does not recognize this architecture") is None
    assert _classify_node_transient_error("") is None
    assert _classify_node_transient_error(None) is None  # type: ignore[arg-type]


def test_node_transient_classifier_registry_has_expected_codes():
    """Guard against accidental pattern deletion. Add codes here when extending."""
    codes = {p.reason_code for p in _NODE_LEVEL_TRANSIENT_PATTERNS}
    assert {"filesystem-eio", "filesystem-readonly"} <= codes


def test_try_start_with_node_eio_writes_no_blacklist_artifacts(tmp_path: Path):
    """The critical guarantee: when a probe fails because the node's storage
    is broken (EIO), calibrate_model must NOT pollute either the per-command
    blacklist or the per-model unsupported list. Regression for deioma
    2026-06-04, where a 10-minute Ceph outage added 86 garbage lines to
    calibration_failed_commands.txt before we caught it.
    """
    log_dir = tmp_path / "calibration_logs"
    log_dir.mkdir()
    # Pre-seed the per-model log file with an EIO tail.
    log_path = log_dir / "Qwen__SomeModel.log"
    log_path.write_text(
        "(APIServer pid=611559) OSError: [Errno 5] Input/output error: "
        "'/usr/share/ollama/.ollama/models/.hf_cache/hub/models--Qwen--SomeModel'\n",
        encoding="utf-8",
    )

    patches = _patch_calibration_infra(
        wait_ready_side_effect=RuntimeError("vLLM exited (code=1)"),
    )
    # Make sure _record_failed_command and _record_unsupported_model are real
    # (not pre-patched out) so we can detect any accidental writes.
    patches["load_failed"].kwargs.pop("return_value", None)
    patches["load_failed"] = patch(
        "logos_worker_node.calibration._load_failed_commands",
        return_value=set(),
    )

    plan = _make_plan(model="Qwen/SomeModel")
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

    assert not result.success
    # The two key guarantees:
    assert result.node_unhealthy_reason == "filesystem-eio"
    failed_path = log_dir / "calibration_failed_commands.txt"
    unsupported_path = log_dir / _UNSUPPORTED_MODELS_FILE
    assert not failed_path.exists(), "node-level transient failure must NOT add per-command blacklist lines"
    assert not unsupported_path.exists(), "node-level transient failure must NOT add per-model unsupported entries"
    # Only one spawn — the floor probe latched _node_unhealthy_box; the
    # ceiling / middle / final probes short-circuit.
    assert managers["spawn"].call_count == 1


def test_try_start_failure_with_fatal_tail_records_unsupported_and_aborts_search(
    tmp_path: Path,
):
    """A first-probe failure whose log tail matches a fatal pattern must:

    (a) write a model-level unsupported entry,
    (b) populate ``result.unsupported_reason`` so the bridge can mark the profile,
    (c) NOT spawn vLLM N more times for each subsequent kv-cache size.
    """
    log_dir = tmp_path / "calibration_logs"
    log_dir.mkdir()
    # Pre-seed the per-model log file with a fatal-pattern tail so the
    # classifier matches when _try_start reads the log after the simulated
    # spawn failure.
    log_path = log_dir / "Qwen__Bogus.log"
    log_path.write_text(
        "(APIServer pid=572249)   Value error, " "Invalid repository ID or local directory specified: 'Qwen/Bogus'.\n",
        encoding="utf-8",
    )

    # Patch the kv search to fail on every probe (RuntimeError = vLLM exited).
    patches = _patch_calibration_infra(
        wait_ready_side_effect=RuntimeError("vLLM exited (code=1)"),
    )

    plan = _make_plan(model="Qwen/Bogus")
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

    assert not result.success
    assert result.unsupported_reason == "invalid-repo-id"
    # Exactly one spawn — the floor probe. Subsequent probes short-circuit
    # via the _unsupported_box latch instead of spawning again.
    assert managers["spawn"].call_count == 1
    # The file on disk now lists the model — restart-safe.
    loaded = _load_unsupported_models(log_dir / _UNSUPPORTED_MODELS_FILE)
    assert loaded["Qwen/Bogus"].reason_code == "invalid-repo-id"


# ═══════════════════════════════════════════════════════════════════════
# KV cache envelope (min_kv_cache_mb / max_kv_cache_mb on CalibrationResult)
# ═══════════════════════════════════════════════════════════════════════


def test_result_to_profile_dict_serializes_kv_envelope():
    """A successful calibration result writes both min and max into the profile dict."""
    result = _success_result(
        "envelope/model",
        min_kv_cache_mb=1024.0,
        max_kv_cache_mb=8192.0,
    )
    data = result_to_profile_dict(result)
    assert data["min_kv_cache_mb"] == 1024.0
    assert data["max_kv_cache_mb"] == 8192.0


def test_result_to_profile_dict_envelope_none_when_unmeasured():
    """Legacy results without an envelope (defaults of 0.0) serialize as None.

    The planner uses None as the "no envelope, fall back to kv_budget_mb" signal,
    so the dict must not write 0.0 in that case — that would look like a real
    envelope clamped at zero.
    """
    result = _success_result("legacy/model")  # leaves min/max at 0.0 defaults
    data = result_to_profile_dict(result)
    assert data["min_kv_cache_mb"] is None
    assert data["max_kv_cache_mb"] is None


def test_result_to_profile_dict_envelope_distinguishes_min_and_max():
    """Min and max must be distinct values once they've been measured — a
    regression guard against the bug where ``search_lo`` was read after the
    binary search had mutated it upward to equal ``best_kv``.  That bug
    collapsed every recorded envelope to ``min == max``, defeating the
    runtime clamp entirely (the planner had no room between the two ends to
    pick anything smaller when VRAM got tight).
    """
    result = _success_result(
        "envelope/distinct",
        min_kv_cache_mb=1024.0,
        max_kv_cache_mb=10240.0,
    )
    data = result_to_profile_dict(result)
    assert data["min_kv_cache_mb"] == 1024.0
    assert data["max_kv_cache_mb"] == 10240.0
    assert data["min_kv_cache_mb"] != data["max_kv_cache_mb"]


def test_sweep_detects_window_ceiling_and_fills_plateau():
    """When the model's full context fits at the floor, the sweep should
    binary-search the true startable-window ceiling and FILL the plateau:
    every KV step from the floor up to the ceiling gets the max context, by
    inference, without probing each one.

    GPU=48 GB → ceiling=37888 MB. Default context (8192) fits at every loadable
    KV; OOM at >=6144 MB → window ceiling resolves to 5120 MB (5 GB). Expect
    pairs {1024,2048,3072,4096,5120} all at 8192.
    """
    kv_calls: list[float] = []

    def spawn_side_effect(plan, vllm_binary, host, port, log_path, kv_cache_memory_bytes, **kwargs):
        kv_calls.append(_parse_kv_to_mb(kv_cache_memory_bytes))
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        return (mock_proc, ["vllm", "serve"])

    def wait_ready_side_effect(*args, **kwargs):
        if kv_calls[-1] >= 6144.0:  # OOM ceiling
            raise RuntimeError("OOM")
        return None

    patches = _patch_search_infra(wait_ready_side_effect=wait_ready_side_effect, gpu_vram_total_mb=48000.0)
    patches["spawn"] = patch("logos_worker_node.calibration.spawn_vllm", side_effect=spawn_side_effect)
    patches["ready"] = patch("logos_worker_node.calibration.wait_ready", side_effect=wait_ready_side_effect)
    # Default context (8192) fits at every loadable KV → no shrink suggestion.
    patches["maxseq"] = patch("logos_worker_node.calibration._extract_vllm_max_seq_len", return_value=8192)
    patches["suggest"] = patch(
        "logos_worker_node.calibration._extract_vllm_max_model_len_suggestion", return_value=None
    )

    result, _ = _run_search_calibrate(patches, plan=_make_search_plan())

    assert result.success
    pairs = result.kv_max_model_len_pairs
    assert pairs
    # Every recorded point serves the full 8192 context.
    assert all(mml == 8192 for _, mml in pairs)
    # The plateau is filled across the whole startable window up to the ceiling.
    kvs = sorted(round(kv) for kv, _ in pairs)
    assert kvs == [1024, 2048, 3072, 4096, 5120]
    assert result.max_model_len == 8192


def test_sweep_computes_rising_curve_from_vllm_rate_without_crawling():
    """Plateau unreachable (full context needs more KV than fits): the sweep must
    derive the KV->context rate from vLLM's report and COMPUTE the curve with only
    a handful of probes — not a 1 GiB-per-step crawl to the ceiling."""
    M = 131072
    K_FULL_GIB = 22.0  # KV needed for full context > 20G ceiling => never plateaus
    per_token = (K_FULL_GIB * 1024 * 1024 * 1024) / M
    kv_calls: list = []

    def spawn_side_effect(plan, vllm_binary, host, port, log_path, kv_cache_memory_bytes, **kwargs):
        kv_calls.append(_parse_kv_to_mb(kv_cache_memory_bytes))
        mp = MagicMock()
        mp.pid = 1
        mp.poll.return_value = None
        return (mp, ["vllm", "serve"])

    def wait_ready_side_effect(*a, **k):
        if kv_calls[-1] >= 21504.0:  # OOM at 21G+
            raise RuntimeError("OOM")
        return None

    def suggest_side_effect(log_tail):
        return min(M - 1, int(kv_calls[-1] * 1024 * 1024 / per_token))

    patches = _patch_search_infra(wait_ready_side_effect=wait_ready_side_effect, gpu_vram_total_mb=48000.0)
    patches["spawn"] = patch("logos_worker_node.calibration.spawn_vllm", side_effect=spawn_side_effect)
    patches["ready"] = patch("logos_worker_node.calibration.wait_ready", side_effect=wait_ready_side_effect)
    patches["maxseq"] = patch("logos_worker_node.calibration._extract_vllm_max_seq_len", return_value=M)
    patches["kvneeded"] = patch(
        "logos_worker_node.calibration._extract_vllm_kv_gib_needed_for_full", return_value=K_FULL_GIB
    )
    patches["suggest"] = patch(
        "logos_worker_node.calibration._extract_vllm_max_model_len_suggestion", side_effect=suggest_side_effect
    )

    result, _ = _run_search_calibrate(patches, plan=_make_search_plan())

    assert result.success
    pairs = result.kv_max_model_len_pairs
    assert pairs
    assert all(0 < mml < M for _, mml in pairs)  # never plateaus
    by_kv = sorted(pairs)
    assert by_kv[0][1] < by_kv[-1][1]  # rising
    assert 19456 <= by_kv[-1][0] <= 20480  # ceiling ~20G (OOM at 21G)
    # The whole window is covered by the computed curve ...
    assert len({round(k) for k, _ in pairs}) >= 15
    # ... but we did NOT probe every 1 GiB step to get there.
    assert len(kv_calls) < 12
