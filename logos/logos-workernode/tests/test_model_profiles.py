"""Tests for ModelProfileRegistry — observation-only, no estimation."""

import time
from pathlib import Path

import pytest

from logos_worker_node.model_profiles import (
    ModelProfileRegistry,
    ModelProfileRecord,
)


# ---------------------------------------------------------------------------
# Basic record/retrieve
# ---------------------------------------------------------------------------


def test_record_loaded_vram_with_kv_derives_base_residency():
    """When kv_cache_sent_mb is known, base_residency = loaded - kv_cache."""
    registry = ModelProfileRegistry()
    registry.record_loaded_vram(
        "org/model-7b",
        8000.0,
        engine="vllm",
        kv_cache_sent_mb=2048.0,
    )

    profile = registry.get_profile("org/model-7b")
    assert profile is not None
    assert profile.loaded_vram_mb == 8000.0
    assert profile.base_residency_mb == pytest.approx(8000.0 - 2048.0)
    assert profile.kv_budget_mb == pytest.approx(2048.0)
    assert profile.residency_source == "measured"
    assert profile.measurement_count == 1


def test_record_loaded_vram_without_kv_leaves_base_residency_none():
    """Without kv_cache_sent_mb, base_residency_mb is not touched — no guessing."""
    registry = ModelProfileRegistry()
    registry.record_loaded_vram("llama3:8b", 8000.0, engine="vllm")

    profile = registry.get_profile("llama3:8b")
    assert profile is not None
    assert profile.loaded_vram_mb == 8000.0
    assert profile.base_residency_mb is None
    assert profile.kv_budget_mb is None


def test_record_loaded_vram_without_kv_updates_loaded_vram_only():
    """For non-vllm engines or missing kv budget, only loaded_vram_mb is tracked."""
    registry = ModelProfileRegistry()
    registry.record_loaded_vram("gemma:2b", 3000.0, engine="ollama")

    profile = registry.get_profile("gemma:2b")
    assert profile.loaded_vram_mb == 3000.0
    assert profile.base_residency_mb is None


def test_record_successful_load_util_tracks_lowest_known_good_value():
    registry = ModelProfileRegistry()
    registry.record_successful_load_util("qwen-coder", 0.8)
    registry.record_successful_load_util("qwen-coder", 0.7)
    registry.record_successful_load_util("qwen-coder", 0.75)

    profile = registry.get_profile("qwen-coder")
    assert profile is not None
    assert profile.min_gpu_memory_utilization_to_load == 0.7


def test_record_loaded_vram_subsequent_uses_ema():
    registry = ModelProfileRegistry()
    registry.record_loaded_vram("llama3:8b", 8000.0, engine="vllm", kv_cache_sent_mb=2000.0)
    registry.record_loaded_vram("llama3:8b", 9000.0, engine="vllm", kv_cache_sent_mb=2000.0)

    profile = registry.get_profile("llama3:8b")
    assert profile is not None
    # EMA loaded: 0.3 * 9000 + 0.7 * 8000 = 8300
    assert abs(profile.loaded_vram_mb - 8300.0) < 1.0
    # EMA base: first=6000, second EMA(6000, 7000)=6300
    assert abs(profile.base_residency_mb - 6300.0) < 1.0
    assert profile.measurement_count == 2


def test_record_loaded_vram_ignores_zero():
    registry = ModelProfileRegistry()
    registry.record_loaded_vram("llama3:8b", 0.0)

    profile = registry.get_profile("llama3:8b")
    assert profile is None


def test_record_sleeping_vram():
    registry = ModelProfileRegistry()
    registry.record_sleeping_vram("llama3:8b", 512.0)

    profile = registry.get_profile("llama3:8b")
    assert profile is not None
    assert profile.sleeping_residual_mb == 512.0


def test_record_sleeping_vram_ema():
    registry = ModelProfileRegistry()
    registry.record_sleeping_vram("llama3:8b", 500.0)
    registry.record_sleeping_vram("llama3:8b", 600.0)

    profile = registry.get_profile("llama3:8b")
    # EMA: 0.3 * 600 + 0.7 * 500 = 530
    assert abs(profile.sleeping_residual_mb - 530.0) < 1.0


def test_record_disk_size_stores_metadata_only():
    """record_disk_size stores the value but does NOT derive base_residency from it."""
    registry = ModelProfileRegistry()
    registry.record_disk_size("llama3:8b", 4_000_000_000)

    profile = registry.get_profile("llama3:8b")
    assert profile is not None
    assert profile.disk_size_bytes == 4_000_000_000
    assert profile.base_residency_mb is None  # no estimation from disk size


# ---------------------------------------------------------------------------
# estimate_vram_mb — no estimation fallbacks
# ---------------------------------------------------------------------------


def test_estimate_vram_vllm_uses_base_residency():
    """vLLM engine: estimate_vram_mb returns base_residency_mb (not loaded_vram_mb)."""
    p = ModelProfileRecord(engine="vllm", base_residency_mb=5800.0, loaded_vram_mb=20000.0)
    assert p.estimate_vram_mb() == 5800.0


def test_estimate_vram_vllm_returns_zero_when_unknown():
    """vLLM with no base_residency returns 0.0 — caller must handle, no guessing."""
    p = ModelProfileRecord(engine="vllm")
    assert p.estimate_vram_mb() == 0.0


def test_estimate_vram_non_vllm_uses_loaded_vram():
    """Non-vLLM: estimate_vram_mb returns loaded_vram_mb."""
    p = ModelProfileRecord(loaded_vram_mb=8000.0)
    assert p.estimate_vram_mb() == 8000.0


def test_estimate_vram_fallback_zero_when_nothing_known():
    """No data at all → returns 0.0 (no speculative fallback)."""
    p = ModelProfileRecord()
    assert p.estimate_vram_mb() == 0.0


def test_estimate_base_residency_returns_stored_value():
    """estimate_base_residency_mb returns base_residency_mb; no name/disk fallback."""
    p = ModelProfileRecord(base_residency_mb=6000.0)
    assert p.estimate_base_residency_mb("org/model-7b") == 6000.0


def test_estimate_base_residency_returns_none_when_unknown():
    p = ModelProfileRecord()
    assert p.estimate_base_residency_mb("org/model-7b") is None


# ---------------------------------------------------------------------------
# get_all_profiles serialization
# ---------------------------------------------------------------------------


def test_get_all_profiles():
    registry = ModelProfileRegistry()
    registry.record_loaded_vram("llama3:8b", 8000.0)
    registry.record_disk_size("qwen3:8b", 5_000_000_000)

    profiles = registry.get_all_profiles()
    assert len(profiles) == 2
    assert "llama3:8b" in profiles
    assert "qwen3:8b" in profiles
    assert profiles["llama3:8b"]["loaded_vram_mb"] == 8000.0
    assert profiles["qwen3:8b"]["disk_size_bytes"] == 5_000_000_000


# ---------------------------------------------------------------------------
# Persistence (state directory)
# ---------------------------------------------------------------------------


def test_persist_and_reload(tmp_path):
    """Write to temp state dir, create new registry from same dir, verify loaded."""
    state_dir = tmp_path / "state"

    registry1 = ModelProfileRegistry(state_dir=state_dir)
    registry1.record_loaded_vram(
        "llama3:8b",
        8000.0,
        engine="vllm",
        observed_gpu_memory_utilization=0.75,
        tensor_parallel_size=2,
        kv_cache_sent_mb=2048.0,
    )
    registry1.record_successful_load_util("llama3:8b", 0.72)
    registry1.record_sleeping_vram("llama3:8b", 512.0)
    registry1.record_disk_size("qwen3:8b", 5_000_000_000)

    registry2 = ModelProfileRegistry(state_dir=state_dir)
    profiles = registry2.get_all_profiles()
    assert len(profiles) == 2

    llama = registry2.get_profile("llama3:8b")
    assert llama is not None
    assert llama.loaded_vram_mb == 8000.0
    assert llama.base_residency_mb == pytest.approx(8000.0 - 2048.0)
    assert llama.sleeping_residual_mb == 512.0
    assert llama.engine == "vllm"
    assert llama.observed_gpu_memory_utilization == 0.75
    assert llama.min_gpu_memory_utilization_to_load == 0.72
    assert llama.tensor_parallel_size == 2
    assert llama.residency_source == "measured"

    qwen = registry2.get_profile("qwen3:8b")
    assert qwen is not None
    assert qwen.disk_size_bytes == 5_000_000_000
    assert qwen.base_residency_mb is None  # disk size does not derive base_residency


def test_calibrated_profile_survives_restart(tmp_path):
    """Profiles written by calibrate_vram_profiles.py are loaded and trusted on restart."""
    import yaml

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    profiles_path = state_dir / "model_profiles.yml"

    # Simulate what calibrate_vram_profiles.py writes
    calibrated_data = {
        "model_profiles": {
            "Qwen/Qwen2.5-Coder-7B-Instruct-AWQ": {
                "loaded_vram_mb": 7296.0,
                "sleeping_residual_mb": 4800.0,
                "disk_size_bytes": None,
                "base_residency_mb": 5248.0,
                "kv_budget_mb": None,
                "engine": "vllm",
                "tensor_parallel_size": 1,
                "residency_source": "calibrated",
                "measurement_count": 1,
                "last_measured_epoch": time.time(),
                "observed_gpu_memory_utilization": None,
                "min_gpu_memory_utilization_to_load": None,
                "kv_per_token_bytes": None,
                "max_context_length": None,
            }
        }
    }
    profiles_path.write_text(yaml.safe_dump(calibrated_data))

    registry = ModelProfileRegistry(state_dir=state_dir)
    profile = registry.get_profile("Qwen/Qwen2.5-Coder-7B-Instruct-AWQ")

    assert profile is not None
    assert profile.base_residency_mb == pytest.approx(5248.0)
    assert profile.sleeping_residual_mb == pytest.approx(4800.0)
    assert profile.loaded_vram_mb == pytest.approx(7296.0)
    assert profile.residency_source == "calibrated"
    assert profile.engine == "vllm"


def test_calibrated_profile_not_overwritten_by_subsequent_load(tmp_path):
    """After calibration, first real load updates via EMA but source becomes 'measured'."""
    import yaml

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    profiles_path = state_dir / "model_profiles.yml"

    calibrated_data = {
        "model_profiles": {
            "org/model": {
                "loaded_vram_mb": 7000.0,
                "sleeping_residual_mb": 4500.0,
                "disk_size_bytes": None,
                "base_residency_mb": 5000.0,
                "kv_budget_mb": None,
                "engine": "vllm",
                "tensor_parallel_size": 1,
                "residency_source": "calibrated",
                "measurement_count": 1,
                "last_measured_epoch": time.time(),
                "observed_gpu_memory_utilization": None,
                "min_gpu_memory_utilization_to_load": None,
                "kv_per_token_bytes": None,
                "max_context_length": None,
            }
        }
    }
    profiles_path.write_text(yaml.safe_dump(calibrated_data))

    registry = ModelProfileRegistry(state_dir=state_dir)
    # Model actually loads — record the real measurement
    registry.record_loaded_vram("org/model", 7200.0, engine="vllm", kv_cache_sent_mb=2048.0)

    profile = registry.get_profile("org/model")
    # base_residency EMA: first was 5000, measured is 7200-2048=5152 → EMA(5000, 5152)
    expected_base = 0.3 * 5152.0 + 0.7 * 5000.0
    assert profile.base_residency_mb == pytest.approx(expected_base, abs=1.0)
    assert profile.residency_source == "measured"


def test_persist_no_state_dir():
    """No state dir → persist is a no-op."""
    registry = ModelProfileRegistry(state_dir=None)
    registry.record_loaded_vram("llama3:8b", 8000.0)
    assert registry.get_profile("llama3:8b").loaded_vram_mb == 8000.0


def test_reload_nonexistent_state_dir(tmp_path):
    """Non-existent state dir → no profiles loaded."""
    state_dir = tmp_path / "does-not-exist"
    registry = ModelProfileRegistry(state_dir=state_dir)
    assert registry.get_all_profiles() == {}


# ---------------------------------------------------------------------------
# seed_capabilities
# ---------------------------------------------------------------------------


def test_seed_capabilities_creates_stub_profile():
    """seed_capabilities creates a minimal profile with engine set."""
    registry = ModelProfileRegistry()
    registry.seed_capabilities(["org/new-model"])

    profile = registry.get_profile("org/new-model")
    assert profile is not None
    assert profile.engine == "vllm"
    assert profile.base_residency_mb is None  # no calibration data yet


def test_seed_capabilities_skips_existing_calibrated_profile(tmp_path):
    """seed_capabilities does not overwrite a calibrated profile loaded from YAML."""
    import yaml

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    profiles_path = state_dir / "model_profiles.yml"

    calibrated_data = {
        "model_profiles": {
            "org/model": {
                "base_residency_mb": 5000.0,
                "sleeping_residual_mb": 4000.0,
                "loaded_vram_mb": 7000.0,
                "engine": "vllm",
                "residency_source": "calibrated",
                "measurement_count": 1,
                "last_measured_epoch": time.time(),
                "disk_size_bytes": None,
                "kv_budget_mb": None,
                "observed_gpu_memory_utilization": None,
                "min_gpu_memory_utilization_to_load": None,
                "tensor_parallel_size": 1,
                "kv_per_token_bytes": None,
                "max_context_length": None,
            }
        }
    }
    profiles_path.write_text(yaml.safe_dump(calibrated_data))

    registry = ModelProfileRegistry(state_dir=state_dir)
    registry.seed_capabilities(["org/model"])

    profile = registry.get_profile("org/model")
    assert profile.base_residency_mb == pytest.approx(5000.0)
    assert profile.residency_source == "calibrated"


def test_seed_capabilities_sets_engine_if_missing():
    """seed_capabilities sets engine on existing profile if it was None."""
    registry = ModelProfileRegistry()
    registry._profiles["model/b"] = ModelProfileRecord(loaded_vram_mb=3000.0)
    registry.seed_capabilities(["model/b"], engine="vllm")

    profile = registry.get_profile("model/b")
    assert profile.engine == "vllm"
    assert profile.loaded_vram_mb == 3000.0  # preserved


def test_seed_capabilities_applies_manual_overrides():
    """Manual overrides from config.yml are applied to newly seeded profiles."""
    registry = ModelProfileRegistry(
        model_profile_overrides={
            "org/model": {"base_residency_mb": 6000.0, "tensor_parallel_size": 2},
        }
    )
    registry.seed_capabilities(["org/model"])

    profile = registry.get_profile("org/model")
    assert profile.base_residency_mb == pytest.approx(6000.0)
    assert profile.tensor_parallel_size == 2
    assert profile.residency_source == "override"


# ---------------------------------------------------------------------------
# Manual overrides
# ---------------------------------------------------------------------------


def test_manual_override_base_residency():
    registry = ModelProfileRegistry(
        model_profile_overrides={
            "org/model": {"base_residency_mb": 7500.0},
        }
    )
    registry.seed_capabilities(["org/model"])

    profile = registry.get_profile("org/model")
    assert profile.base_residency_mb == pytest.approx(7500.0)
    assert profile.residency_source == "override"


def test_kv_per_token_in_to_dict():
    """kv_per_token_bytes and max_context_length are included in serialization."""
    record = ModelProfileRecord(kv_per_token_bytes=57344, max_context_length=32768)
    d = record.to_dict()
    assert d["kv_per_token_bytes"] == 57344
    assert d["max_context_length"] == 32768


# ---------------------------------------------------------------------------
# Thread safety (basic)
# ---------------------------------------------------------------------------


def test_concurrent_record():
    """Basic thread safety — no crash under concurrent writes."""
    import concurrent.futures

    registry = ModelProfileRegistry()

    def record_batch(model_name, count):
        for i in range(count):
            registry.record_loaded_vram(model_name, 5000.0 + i)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(record_batch, f"model-{n}", 50) for n in range(4)]
        for f in futures:
            f.result()

    profiles = registry.get_all_profiles()
    assert len(profiles) == 4
    for name in ["model-0", "model-1", "model-2", "model-3"]:
        assert name in profiles
        assert profiles[name]["measurement_count"] == 50
