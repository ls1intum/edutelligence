"""Tests for ModelProfileRegistry auto-calibration."""

import time
from pathlib import Path

import pytest

from logos_worker_node.model_profiles import ModelProfileRegistry, ModelProfileRecord


# ---------------------------------------------------------------------------
# Basic record/retrieve
# ---------------------------------------------------------------------------


def test_record_loaded_vram_first_sets_value():
    registry = ModelProfileRegistry()
    registry.record_loaded_vram(
        "llama3:8b",
        8000.0,
        engine="vllm",
        observed_gpu_memory_utilization=0.7,
        tensor_parallel_size=2,
    )

    profile = registry.get_profile("llama3:8b")
    assert profile is not None
    assert profile.loaded_vram_mb == 8000.0
    assert profile.engine == "vllm"
    assert profile.observed_gpu_memory_utilization == 0.7
    assert profile.tensor_parallel_size == 2
    assert profile.measurement_count == 1
    assert profile.base_residency_mb is not None
    assert profile.kv_budget_mb is not None


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
    registry.record_loaded_vram("llama3:8b", 8000.0)
    registry.record_loaded_vram("llama3:8b", 9000.0)

    profile = registry.get_profile("llama3:8b")
    assert profile is not None
    # EMA: 0.3 * 9000 + 0.7 * 8000 = 2700 + 5600 = 8300
    assert abs(profile.loaded_vram_mb - 8300.0) < 1.0
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
    # EMA: 0.3 * 600 + 0.7 * 500 = 180 + 350 = 530
    assert abs(profile.sleeping_residual_mb - 530.0) < 1.0


def test_record_disk_size():
    registry = ModelProfileRegistry()
    registry.record_disk_size("llama3:8b", 4_000_000_000)

    profile = registry.get_profile("llama3:8b")
    assert profile is not None
    assert profile.disk_size_bytes == 4_000_000_000


# ---------------------------------------------------------------------------
# estimate_vram_mb
# ---------------------------------------------------------------------------


def test_estimate_vram_measured():
    """Returns measured loaded_vram_mb when available."""
    p = ModelProfileRecord(loaded_vram_mb=8000.0)
    assert p.estimate_vram_mb() == 8000.0


def test_estimate_vram_disk_heuristic():
    """Falls back to disk_size heuristic when no measurement."""
    # 4 GB disk = 4096 MB * 1.1 = 4505.6
    p = ModelProfileRecord(disk_size_bytes=4 * 1024 * 1024 * 1024)
    expected = (4 * 1024 * 1024 * 1024 / (1024 * 1024)) * 1.1
    assert abs(p.estimate_vram_mb() - expected) < 1.0


def test_estimate_base_residency_from_model_name():
    p = ModelProfileRecord()
    estimated = p.estimate_base_residency_mb("Qwen/Qwen2.5-Coder-7B-Instruct")
    assert estimated is not None
    assert estimated > 10_000


def test_estimate_vram_fallback():
    """Conservative 4096 MB fallback when nothing available."""
    p = ModelProfileRecord()
    assert p.estimate_vram_mb() == 4096.0


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
# Persistence (config.yml)
# ---------------------------------------------------------------------------


def test_persist_and_reload(tmp_path):
    """Write to temp config.yml, create new registry from same path, verify loaded."""
    config_path = tmp_path / "config.yml"

    registry1 = ModelProfileRegistry(config_path=config_path)
    registry1.record_loaded_vram(
        "llama3:8b",
        8000.0,
        engine="vllm",
        observed_gpu_memory_utilization=0.75,
        tensor_parallel_size=2,
    )
    registry1.record_successful_load_util("llama3:8b", 0.72)
    registry1.record_sleeping_vram("llama3:8b", 512.0)
    registry1.record_disk_size("qwen3:8b", 5_000_000_000)

    # Create new registry from same path
    registry2 = ModelProfileRegistry(config_path=config_path)
    profiles = registry2.get_all_profiles()
    assert len(profiles) == 2

    llama = registry2.get_profile("llama3:8b")
    assert llama is not None
    assert llama.loaded_vram_mb == 8000.0
    assert llama.sleeping_residual_mb == 512.0
    assert llama.engine == "vllm"
    assert llama.observed_gpu_memory_utilization == 0.75
    assert llama.min_gpu_memory_utilization_to_load == 0.72
    assert llama.tensor_parallel_size == 2

    qwen = registry2.get_profile("qwen3:8b")
    assert qwen is not None
    assert qwen.disk_size_bytes == 5_000_000_000


def test_persist_no_config_path():
    """No config path → persist is a no-op."""
    registry = ModelProfileRegistry(config_path=None)
    registry.record_loaded_vram("llama3:8b", 8000.0)
    # Should not raise
    assert registry.get_profile("llama3:8b").loaded_vram_mb == 8000.0


def test_reload_nonexistent_config(tmp_path):
    """Non-existent config file → no profiles loaded."""
    config_path = tmp_path / "does-not-exist.yml"
    registry = ModelProfileRegistry(config_path=config_path)
    assert registry.get_all_profiles() == {}


# ---------------------------------------------------------------------------
# Thread safety (basic)
# ---------------------------------------------------------------------------


def test_concurrent_record(tmp_path):
    """Basic thread safety — no crash under concurrent writes."""
    import concurrent.futures

    registry = ModelProfileRegistry()

    def record_batch(model_name, count):
        for i in range(count):
            registry.record_loaded_vram(model_name, 5000.0 + i)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(record_batch, f"model-{n}", 50) for n in range(4)
        ]
        for f in futures:
            f.result()

    profiles = registry.get_all_profiles()
    assert len(profiles) == 4
    for name in ["model-0", "model-1", "model-2", "model-3"]:
        assert name in profiles
        assert profiles[name]["measurement_count"] == 50
