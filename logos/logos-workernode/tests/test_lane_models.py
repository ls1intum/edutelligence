from __future__ import annotations

import pytest
from pydantic import ValidationError

from logos_worker_node.models import LaneConfig, LaneSetRequest, LogosConfig, VllmConfig


def test_lane_config_normalizes_gpu_devices() -> None:
    lane = LaneConfig(model="qwen2.5-coder:32b", gpu_devices="0, 1")
    assert lane.gpu_devices == "0,1"


def test_lane_config_rejects_invalid_gpu_devices() -> None:
    with pytest.raises(ValidationError):
        LaneConfig(model="demo", gpu_devices="gpu0")


def test_lane_config_rejects_vllm_block_on_ollama_backend() -> None:
    with pytest.raises(ValidationError):
        LaneConfig(
            model="demo",
            vllm=False,
            vllm_config=VllmConfig(gpu_memory_utilization=0.75),
        )


def test_vllm_config_gpu_memory_utilization_is_optional() -> None:
    cfg = VllmConfig()
    assert cfg.gpu_memory_utilization is None


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
