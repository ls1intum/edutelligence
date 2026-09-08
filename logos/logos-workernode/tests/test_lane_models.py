from __future__ import annotations

import pytest
from pydantic import ValidationError

from logos_worker_node.models import AppConfig, LaneConfig, LaneSetRequest, LogosConfig, VllmConfig


def test_lane_config_normalizes_gpu_devices() -> None:
    lane = LaneConfig(model="qwen2.5-coder:32b", gpu_devices="0, 1")
    assert lane.gpu_devices == "0,1"


def test_lane_config_rejects_invalid_gpu_devices() -> None:
    with pytest.raises(ValidationError):
        LaneConfig(model="demo", gpu_devices="gpu0")


def test_lane_config_rejects_vllm_false() -> None:
    """The Ollama engine was removed — every lane is a vLLM lane."""
    with pytest.raises(ValidationError, match="vllm=false"):
        LaneConfig(model="demo", vllm=False)


def test_lane_config_rejects_removed_ollama_lane_fields() -> None:
    with pytest.raises(ValidationError, match="keep_alive"):
        LaneConfig(model="demo", keep_alive="10m")


def test_vllm_config_gpu_memory_utilization_is_optional() -> None:
    cfg = VllmConfig()
    assert cfg.gpu_memory_utilization is None


def test_app_config_migrates_legacy_ollama_engine_fields() -> None:
    """engines.ollama.models_path/gpu_devices move to worker.* (with a warning)."""
    cfg = AppConfig.model_validate(
        {
            "worker": {"name": "w1"},
            "engines": {"ollama": {"models_path": "/custom/models", "gpu_devices": "0,1"}},
        }
    )
    assert cfg.worker.models_path == "/custom/models"
    assert cfg.worker.gpu_devices == "0,1"


def test_app_config_prefers_explicit_worker_fields_over_legacy_ollama() -> None:
    cfg = AppConfig.model_validate(
        {
            "worker": {"models_path": "/new/path"},
            "engines": {"ollama": {"models_path": "/custom/models"}},
        }
    )
    assert cfg.worker.models_path == "/new/path"


def test_lane_config_rejects_tensor_parallel_size_above_explicit_gpu_count() -> None:
    with pytest.raises(ValidationError):
        LaneConfig(
            model="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
            vllm=True,
            gpu_devices="0,1",
            vllm_config=VllmConfig(tensor_parallel_size=3),
        )


def test_lane_set_request_rejects_duplicate_normalized_lane_ids() -> None:
    with pytest.raises(ValidationError):
        LaneSetRequest(
            lanes=[
                LaneConfig(model="org/model:v1"),
                LaneConfig(model="org_model_v1"),
            ]
        )


def test_lane_set_request_allows_same_model_with_unique_lane_ids() -> None:
    req = LaneSetRequest(
        lanes=[
            LaneConfig(lane_id="replica-a", model="org/model:v1"),
            LaneConfig(lane_id="replica-b", model="org/model:v1"),
        ]
    )
    assert len(req.lanes) == 2


def test_logos_config_extracts_inline_capability_overrides() -> None:
    cfg = LogosConfig(
        enabled=True,
        logos_url="https://logos.example",
        provider_id=13,
        shared_key="secret",
        capabilities_models=[
            {
                "model": "Qwen/Qwen2.5-Coder-7B-Instruct-AWQ",
                "tensor_parallel_size": 1,
                "kv_budget_mb": 2048,
                "max_context_length": 4096,
            }
        ],
    )

    assert cfg.capabilities_models == ["Qwen/Qwen2.5-Coder-7B-Instruct-AWQ"]
    assert cfg.capabilities_overrides["Qwen/Qwen2.5-Coder-7B-Instruct-AWQ"] == {
        "tensor_parallel_size": 1,
        "kv_budget_mb": 2048,
        "max_context_length": 4096,
    }
