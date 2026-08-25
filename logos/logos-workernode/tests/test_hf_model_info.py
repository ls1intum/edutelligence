"""Tests for hf_model_info — the calibration compatibility precheck's HF fetch/math."""

from __future__ import annotations

import json
import sys
import time
from unittest.mock import MagicMock, mock_open, patch

import pytest

from logos_worker_node.hf_model_info import (
    HfModelInfoCache,
    HfModelMetadata,
    _derive_kv_per_token_bytes,
    fetch_hf_model_metadata,
    min_feasible_tp,
)


def test_derive_kv_per_token_bytes():
    # Standard case: head_dim = hidden_size / num_attention_heads.
    llama_like = {
        "num_hidden_layers": 32,
        "hidden_size": 4096,
        "num_attention_heads": 32,
        "num_key_value_heads": 8,
        "torch_dtype": "bfloat16",
    }
    assert _derive_kv_per_token_bytes(llama_like, None) == 2 * 32 * 8 * 128 * 2

    # Explicit head_dim overrides the hidden_size/num_attention_heads division.
    explicit_head_dim = {**llama_like, "num_hidden_layers": 10, "num_key_value_heads": 4, "head_dim": 256}
    assert _derive_kv_per_token_bytes(explicit_head_dim, None) == 2 * 10 * 4 * 256 * 2

    # No num_key_value_heads → MHA, falls back to num_attention_heads.
    mha = {"num_hidden_layers": 12, "hidden_size": 768, "num_attention_heads": 12, "torch_dtype": "float16"}
    assert _derive_kv_per_token_bytes(mha, None) == 2 * 12 * 12 * 64 * 2

    # VLM checkpoints nest the LM config under text_config.
    vlm = {"text_config": {**llama_like, "num_hidden_layers": 24, "hidden_size": 2048, "num_attention_heads": 16}}
    assert _derive_kv_per_token_bytes(vlm, None) == 2 * 24 * 8 * 128 * 2

    # dtype override wins over config; unknown dtype defaults to 2 bytes.
    minimal = {"num_hidden_layers": 1, "hidden_size": 128, "num_attention_heads": 1, "num_key_value_heads": 1}
    assert _derive_kv_per_token_bytes({**minimal, "torch_dtype": "float32"}, "int8") == 2 * 1 * 1 * 128 * 1
    assert _derive_kv_per_token_bytes({**minimal, "torch_dtype": "unknown-future-dtype"}, None) == 2 * 1 * 1 * 128 * 2

    # Missing required fields → None, never a guess.
    assert _derive_kv_per_token_bytes({}, None) is None
    assert _derive_kv_per_token_bytes({"num_hidden_layers": 10}, None) is None


def _fake_sibling(rfilename: str, size: int | None):
    sib = MagicMock()
    sib.rfilename = rfilename
    sib.size = size
    return sib


def test_fetch_hf_model_metadata_success():
    fake_info = MagicMock()
    fake_info.siblings = [
        _fake_sibling("model-00001-of-00002.safetensors", 3_000_000_000),
        _fake_sibling("model-00002-of-00002.safetensors", 2_000_000_000),
        _fake_sibling("README.md", 512),
    ]
    fake_api = MagicMock()
    fake_api.model_info.return_value = fake_info
    fake_config = {
        "num_hidden_layers": 32,
        "hidden_size": 4096,
        "num_attention_heads": 32,
        "num_key_value_heads": 8,
        "max_position_embeddings": 8192,
        "torch_dtype": "bfloat16",
    }

    with (
        patch("huggingface_hub.HfApi", return_value=fake_api),
        patch("huggingface_hub.hf_hub_download", return_value="/fake/config.json"),
        patch("builtins.open", mock_open(read_data=json.dumps(fake_config))),
    ):
        meta = fetch_hf_model_metadata("org/model", token=None)

    assert meta.source == "hf"
    assert meta.weight_bytes == 5_000_000_000
    assert meta.kv_per_token_bytes == 2 * 32 * 8 * 128 * 2
    assert meta.max_context_length == 8192


@pytest.mark.parametrize(
    "hf_api_patch",
    [
        patch("huggingface_hub.HfApi", side_effect=RuntimeError("401 gated repo")),
        patch("huggingface_hub.HfApi", side_effect=TimeoutError("timed out")),
    ],
)
def test_fetch_hf_model_metadata_never_raises_on_failure(hf_api_patch):
    with hf_api_patch, patch("huggingface_hub.hf_hub_download", side_effect=RuntimeError("boom")):
        meta = fetch_hf_model_metadata("org/model", token=None)

    assert meta.weight_bytes is None
    assert meta.source.startswith("error:")


def test_fetch_hf_model_metadata_handles_huggingface_hub_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "huggingface_hub", None)
    meta = fetch_hf_model_metadata("org/model", token=None)
    assert meta.source == "error:huggingface_hub-unavailable"


def test_fetch_hf_model_metadata_partial_success_when_only_weights_reachable():
    fake_info = MagicMock()
    fake_info.siblings = [_fake_sibling("model.safetensors", 1_000_000_000)]
    fake_api = MagicMock()
    fake_api.model_info.return_value = fake_info

    with (
        patch("huggingface_hub.HfApi", return_value=fake_api),
        patch("huggingface_hub.hf_hub_download", side_effect=RuntimeError("no config.json")),
    ):
        meta = fetch_hf_model_metadata("org/model", token=None)

    assert meta.source == "hf"
    assert meta.weight_bytes == 1_000_000_000
    assert meta.kv_per_token_bytes is None


def test_cache_round_trip_and_ttl(tmp_path):
    cache = HfModelInfoCache(tmp_path)
    assert cache.get("org/model") is None

    cache.put("org/model", HfModelMetadata(weight_bytes=123, source="hf"))
    reloaded = HfModelInfoCache(tmp_path)
    got = reloaded.get("org/model")
    assert got is not None and got.weight_bytes == 123

    stale_success = HfModelMetadata(weight_bytes=1, source="hf", fetched_at=time.time() - 25 * 3600)
    cache.put("stale-success", stale_success)
    assert cache.get("stale-success") is None

    stale_error = HfModelMetadata(source="error:gated", fetched_at=time.time() - 2 * 3600)
    cache.put("stale-error", stale_error)
    assert cache.get("stale-error") is None


def test_fetch_hf_model_metadata_uses_cache_without_refetching(tmp_path):
    cache = HfModelInfoCache(tmp_path)
    cache.put("org/model", HfModelMetadata(weight_bytes=999, source="hf"))

    with patch("huggingface_hub.HfApi") as fake_api_cls:
        meta = fetch_hf_model_metadata("org/model", token=None, cache=cache)

    fake_api_cls.assert_not_called()
    assert meta.weight_bytes == 999


def test_min_feasible_tp():
    gb = 1024 * 1024 * 1024
    # Fits at tp=1 on plenty of VRAM.
    assert min_feasible_tp(4 * gb, per_gpu_free_mb=20000.0, hardware_max_tp=8) == 1
    # 40 GB weights need tp=4 (10 GB/GPU) — tp=2 (20 GB/GPU) doesn't fit in 12 GB free.
    assert min_feasible_tp(40 * gb, per_gpu_free_mb=12000.0, hardware_max_tp=8) == 4
    # Doesn't fit anywhere, even at hardware max.
    assert min_feasible_tp(500 * gb, per_gpu_free_mb=20000.0, hardware_max_tp=8) is None
    # Never exceeds the hardware ceiling, even when more VRAM would allow it.
    assert min_feasible_tp(4 * gb, per_gpu_free_mb=100000.0, hardware_max_tp=1) == 1
    # min_kv_mb pushes the required tp up a step.
    assert min_feasible_tp(8 * gb, per_gpu_free_mb=12000.0, hardware_max_tp=8, min_kv_mb=0.0) == 1
    assert min_feasible_tp(8 * gb, per_gpu_free_mb=12000.0, hardware_max_tp=8, min_kv_mb=3000.0) == 2
    # Only steps through powers of two — 15 GB at tp=2 (7.5 GB/GPU) doesn't fit
    # a 5 GB budget, but tp=4 (3.75 GB/GPU) does; tp=3 is never considered.
    assert min_feasible_tp(15 * gb, per_gpu_free_mb=5000.0, hardware_max_tp=8) == 4
