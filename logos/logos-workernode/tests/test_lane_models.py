from __future__ import annotations

import pytest
from pydantic import ValidationError

from logos_worker_node.models import LaneConfig, LaneSetRequest, LogosConfig, RopeScalingConfig, VllmConfig


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


# ── RoPE scaling (issue #744) ────────────────────────────────────────────────


def test_vllm_config_rope_scaling_defaults_to_disabled() -> None:
    cfg = VllmConfig()
    assert cfg.rope_scaling is None


def test_rope_scaling_yarn_round_trips() -> None:
    cfg = VllmConfig(
        rope_scaling={
            "rope_type": "yarn",
            "factor": 4.0,
            "original_max_position_embeddings": 32768,
            "rope_theta": 10000000,
        }
    )
    rs = cfg.rope_scaling
    assert isinstance(rs, RopeScalingConfig)
    assert rs.rope_type == "yarn"
    assert rs.factor == 4.0
    assert rs.original_max_position_embeddings == 32768


def test_rope_scaling_requires_rope_type() -> None:
    with pytest.raises(ValidationError):
        VllmConfig(rope_scaling={"factor": 4.0})


def test_rope_scaling_rejects_unknown_rope_type() -> None:
    with pytest.raises(ValidationError, match="Invalid rope_type"):
        VllmConfig(rope_scaling={"rope_type": "yarnn"})


def test_rope_scaling_yarn_requires_factor_and_original_max() -> None:
    with pytest.raises(ValidationError, match="factor"):
        VllmConfig(rope_scaling={"rope_type": "yarn", "original_max_position_embeddings": 32768})
    with pytest.raises(ValidationError, match="original_max_position_embeddings"):
        VllmConfig(rope_scaling={"rope_type": "yarn", "factor": 4.0})


def test_rope_scaling_rejects_factor_below_one() -> None:
    with pytest.raises(ValidationError):
        VllmConfig(rope_scaling={"rope_type": "yarn", "factor": 0.5, "original_max_position_embeddings": 32768})


def test_rope_scaling_hf_overrides_default_key_and_strips_unset_keys() -> None:
    # Unset optional keys must not be emitted: the hf-overrides merge is a
    # deep merge, so a null factor would clobber the model's own value.
    cfg = VllmConfig(
        rope_scaling={
            "rope_type": "yarn",
            "factor": 2.0,
            "original_max_position_embeddings": 32768,
        }
    )
    assert cfg.rope_scaling.to_hf_overrides() == {
        "rope_scaling": {
            "rope_type": "yarn",
            "factor": 2.0,
            "original_max_position_embeddings": 32768,
        }
    }


def test_rope_scaling_passes_through_family_specific_keys() -> None:
    # The Qwen3.5/3.8-style block from issue #744: family-specific keys are
    # not part of the schema and must still reach vLLM.
    cfg = VllmConfig(
        rope_scaling={
            "rope_type": "yarn",
            "rope_theta": 10000000,
            "partial_rotary_factor": 0.25,
            "factor": 4.0,
            "original_max_position_embeddings": 262144,
            "mrope_interleaved": True,
            "mrope_section": [11, 11, 10],
            "config_path": "text_config.rope_parameters",
        }
    )
    assert cfg.rope_scaling.to_hf_overrides() == {
        "text_config": {
            "rope_parameters": {
                "rope_type": "yarn",
                "rope_theta": 10000000.0,
                "partial_rotary_factor": 0.25,
                "factor": 4.0,
                "original_max_position_embeddings": 262144,
                "mrope_interleaved": True,
                "mrope_section": [11, 11, 10],
            }
        }
    }


def test_rope_scaling_rejects_path_traversal_in_config_path() -> None:
    with pytest.raises(ValidationError, match="Invalid config_path"):
        VllmConfig(
            rope_scaling={
                "rope_type": "yarn",
                "factor": 2.0,
                "original_max_position_embeddings": 32768,
                "config_path": "../escape",
            }
        )


def test_rope_scaling_equality_sees_family_specific_keys() -> None:
    # _lane_needs_restart compares RopeScalingConfig values; extra keys must
    # participate in equality or a mrope_section change would not restart.
    base = {"rope_type": "yarn", "factor": 4.0, "original_max_position_embeddings": 262144}
    a = RopeScalingConfig.model_validate({**base, "mrope_section": [11, 11, 10]})
    b = RopeScalingConfig.model_validate({**base, "mrope_section": [11, 11, 10]})
    c = RopeScalingConfig.model_validate(base)
    assert a == b
    assert a != c


def test_vllm_config_rejects_rope_scaling_with_hf_overrides_extra_arg() -> None:
    with pytest.raises(ValidationError, match="mutually exclusive"):
        VllmConfig(
            rope_scaling={
                "rope_type": "yarn",
                "factor": 4.0,
                "original_max_position_embeddings": 32768,
            },
            extra_args=["--hf-overrides", '{"rope_scaling":{"rope_type":"linear","factor":2}}'],
        )


def test_vllm_config_rejects_rope_scaling_with_hf_overrides_equals_form() -> None:
    with pytest.raises(ValidationError, match="mutually exclusive"):
        VllmConfig(
            rope_scaling={
                "rope_type": "yarn",
                "factor": 4.0,
                "original_max_position_embeddings": 32768,
            },
            extra_args=['--hf-overrides={"rope_scaling":{"rope_type":"linear","factor":2}}'],
        )


def test_vllm_config_accepts_rope_scaling_alone() -> None:
    cfg = VllmConfig(rope_scaling={"rope_type": "linear", "factor": 2.0})
    assert cfg.rope_scaling is not None
    assert cfg.rope_scaling.rope_type == "linear"
