from __future__ import annotations

import pytest
from pydantic import ValidationError

from node_controller.models import LaneConfig, LaneSetRequest, VllmConfig


def test_lane_config_normalizes_gpu_devices() -> None:
    lane = LaneConfig(model="qwen2.5-coder:32b", backend="ollama", gpu_devices="0, 1")
    assert lane.gpu_devices == "0,1"


def test_lane_config_rejects_invalid_backend() -> None:
    with pytest.raises(ValidationError):
        LaneConfig(model="demo", backend="invalid")


def test_lane_config_rejects_invalid_gpu_devices() -> None:
    with pytest.raises(ValidationError):
        LaneConfig(model="demo", backend="ollama", gpu_devices="gpu0")


def test_lane_config_rejects_vllm_block_on_ollama_backend() -> None:
    with pytest.raises(ValidationError):
        LaneConfig(
            model="demo",
            backend="ollama",
            vllm=VllmConfig(gpu_memory_utilization=0.75),
        )


def test_lane_config_rejects_tensor_parallel_size_above_explicit_gpu_count() -> None:
    with pytest.raises(ValidationError):
        LaneConfig(
            model="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
            backend="vllm",
            gpu_devices="0,1",
            vllm=VllmConfig(tensor_parallel_size=3),
        )


def test_lane_set_request_rejects_duplicate_normalized_lane_ids() -> None:
    with pytest.raises(ValidationError):
        LaneSetRequest(
            lanes=[
                LaneConfig(model="org/model:v1", backend="ollama"),
                LaneConfig(model="org_model_v1", backend="ollama"),
            ]
        )


def test_lane_set_request_allows_same_model_with_unique_lane_ids() -> None:
    req = LaneSetRequest(
        lanes=[
            LaneConfig(lane_id="replica-a", model="org/model:v1", backend="ollama"),
            LaneConfig(lane_id="replica-b", model="org/model:v1", backend="ollama"),
        ]
    )
    assert len(req.lanes) == 2
