"""Tests for ModelProfileRegistry auto-calibration."""

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from logos_worker_node.model_profiles import (
    ModelProfileRegistry,
    ModelProfileRecord,
    _fetch_hf_model_size_bytes,
    _fetch_hf_kv_params,
    _compute_kv_per_token_bytes,
)


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
    # 4 GB disk = 4096 MB * 1.2 (20% inference overhead)
    p = ModelProfileRecord(disk_size_bytes=4 * 1024 * 1024 * 1024)
    expected = (4 * 1024 * 1024 * 1024 / (1024 * 1024)) * 1.2
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


# ---------------------------------------------------------------------------
# HuggingFace API model size fetching
# ---------------------------------------------------------------------------


def _mock_hf_response(model_name):
    """Simulate HF API response for safetensors metadata."""
    import json
    import io

    responses = {
        "Qwen/Qwen2.5-Coder-7B-Instruct": {
            "safetensors": {
                "parameters": {"BF16": 7615616512},
                "total": 7615616512,
            }
        },
        "meta-llama/Llama-3.1-70B": {
            "safetensors": {
                "parameters": {"BF16": 70553706496},
                "total": 70553706496,
            }
        },
    }
    data = responses.get(model_name, {})

    class FakeResponse:
        def read(self):
            return json.dumps(data).encode()
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    return FakeResponse()


def test_fetch_hf_model_size_bytes_qwen():
    """Fetches real model weight size from HF API mock."""
    with patch("logos_worker_node.model_profiles.urllib.request.urlopen") as mock_url:
        mock_url.return_value = _mock_hf_response("Qwen/Qwen2.5-Coder-7B-Instruct")
        result = _fetch_hf_model_size_bytes("Qwen/Qwen2.5-Coder-7B-Instruct")

    # 7615616512 params × 2 bytes (BF16) = 15231233024 bytes
    assert result == 7615616512 * 2
    assert result / (1024 ** 3) == pytest.approx(14.19, abs=0.1)


def test_fetch_hf_model_size_bytes_skips_non_hf_names():
    """Models without / in name are not HF model IDs."""
    result = _fetch_hf_model_size_bytes("gemma2:2b")
    assert result is None


def test_fetch_hf_model_size_bytes_handles_error():
    """Network errors return None gracefully."""
    with patch("logos_worker_node.model_profiles.urllib.request.urlopen") as mock_url:
        mock_url.side_effect = Exception("Connection refused")
        result = _fetch_hf_model_size_bytes("Qwen/Qwen2.5-Coder-7B-Instruct")
    assert result is None


def test_ensure_disk_size_populates_base_residency():
    """record_loaded_vram fetches HF size and computes accurate base_residency."""
    registry = ModelProfileRegistry()

    with patch("logos_worker_node.model_profiles._fetch_hf_model_size_bytes") as mock_fetch:
        # 7B BF16 = ~14.2 GB weight bytes
        mock_fetch.return_value = 7615616512 * 2
        registry.record_loaded_vram(
            "Qwen/Qwen2.5-Coder-7B-Instruct",
            28000.0,  # effective_vram_mb when loaded at 0.90
            engine="vllm",
            observed_gpu_memory_utilization=0.90,
            tensor_parallel_size=2,
        )

    profile = registry.get_profile("Qwen/Qwen2.5-Coder-7B-Instruct")
    assert profile is not None
    assert profile.disk_size_bytes == 7615616512 * 2
    # base_residency = disk_size / 1024² × 1.2 ≈ 14.2 GB × 1.2 ≈ 17.0 GB
    expected_base = (7615616512 * 2 / (1024 * 1024)) * 1.2
    assert abs(profile.base_residency_mb - expected_base) < 10
    # kv_budget = loaded_vram - base_residency
    assert profile.kv_budget_mb is not None
    assert profile.kv_budget_mb > 0
    assert profile.kv_budget_mb == pytest.approx(28000.0 - profile.base_residency_mb, abs=10)


def test_ensure_disk_size_only_fetches_once():
    """HF API is called at most once per model, even on repeated record calls."""
    registry = ModelProfileRegistry()

    with patch("logos_worker_node.model_profiles._fetch_hf_model_size_bytes") as mock_fetch, \
         patch("logos_worker_node.model_profiles._fetch_hf_kv_params") as mock_kv:
        mock_fetch.return_value = None  # simulate failure
        mock_kv.return_value = None
        registry.record_loaded_vram("Qwen/Qwen2.5-Coder-7B-Instruct", 28000.0, engine="vllm")
        registry.record_loaded_vram("Qwen/Qwen2.5-Coder-7B-Instruct", 28000.0, engine="vllm")
        registry.record_loaded_vram("Qwen/Qwen2.5-Coder-7B-Instruct", 28000.0, engine="vllm")
        assert mock_fetch.call_count == 1  # only first attempt


# ---------------------------------------------------------------------------
# HF config.json KV params
# ---------------------------------------------------------------------------

def test_fetch_hf_kv_params_qwen():
    """config.json fetch extracts architecture params for KV cache calculation."""
    # Qwen2.5-7B config.json structure
    fake_config = {
        "num_hidden_layers": 28,
        "num_attention_heads": 28,
        "num_key_value_heads": 4,
        "hidden_size": 3584,
        "max_position_embeddings": 32768,
    }
    import json
    import io

    def mock_urlopen(req, timeout=10):
        resp = io.BytesIO(json.dumps(fake_config).encode())
        resp.status = 200
        return resp

    with patch("logos_worker_node.model_profiles.urllib.request.urlopen", mock_urlopen):
        result = _fetch_hf_kv_params("Qwen/Qwen2.5-Coder-7B-Instruct")

    assert result is not None
    assert result["num_layers"] == 28
    assert result["num_kv_heads"] == 4
    assert result["head_dim"] == 128  # 3584 // 28
    assert result["max_context"] == 32768


def test_fetch_hf_kv_params_non_gqa():
    """Models without num_key_value_heads fall back to num_attention_heads."""
    fake_config = {
        "num_hidden_layers": 12,
        "num_attention_heads": 12,
        "hidden_size": 768,
        "max_position_embeddings": 2048,
    }
    import json
    import io

    def mock_urlopen(req, timeout=10):
        return io.BytesIO(json.dumps(fake_config).encode())

    with patch("logos_worker_node.model_profiles.urllib.request.urlopen", mock_urlopen):
        result = _fetch_hf_kv_params("org/small-model")

    assert result is not None
    assert result["num_kv_heads"] == 12  # fallback to num_attention_heads
    assert result["head_dim"] == 64  # 768 // 12


def test_fetch_hf_kv_params_skips_non_hf():
    """Non-HF model names (no /) return None."""
    assert _fetch_hf_kv_params("gemma2:2b") is None


def test_compute_kv_per_token_bytes():
    """Verify KV per-token formula: 2 × layers × kv_heads × head_dim × 2 (BF16)."""
    # Qwen2.5-7B: 2 × 28 × 4 × 128 × 2 = 57,344
    params = {"num_layers": 28, "num_kv_heads": 4, "head_dim": 128, "max_context": 32768}
    assert _compute_kv_per_token_bytes(params) == 57344

    # Gemma2-2B: 2 × 26 × 4 × 256 × 2 = 106,496
    params2 = {"num_layers": 26, "num_kv_heads": 4, "head_dim": 256, "max_context": 8192}
    assert _compute_kv_per_token_bytes(params2) == 106496


def test_kv_per_token_in_to_dict():
    """kv_per_token_bytes and max_context_length are included in serialization."""
    record = ModelProfileRecord(
        kv_per_token_bytes=57344,
        max_context_length=32768,
    )
    d = record.to_dict()
    assert d["kv_per_token_bytes"] == 57344
    assert d["max_context_length"] == 32768


def test_ensure_disk_size_fetches_kv_params():
    """_ensure_disk_size also fetches KV params from config.json."""
    registry = ModelProfileRegistry()
    kv_params = {"num_layers": 28, "num_kv_heads": 4, "head_dim": 128, "max_context": 32768}

    with patch("logos_worker_node.model_profiles._fetch_hf_model_size_bytes") as mock_size, \
         patch("logos_worker_node.model_profiles._fetch_hf_kv_params") as mock_kv:
        mock_size.return_value = 15231233024
        mock_kv.return_value = kv_params
        registry.record_loaded_vram(
            "Qwen/Qwen2.5-Coder-7B-Instruct", 28000.0, engine="vllm",
        )

    profile = registry.get_profile("Qwen/Qwen2.5-Coder-7B-Instruct")
    assert profile is not None
    assert profile.kv_per_token_bytes == 57344  # 2 * 28 * 4 * 128 * 2
    assert profile.max_context_length == 32768
