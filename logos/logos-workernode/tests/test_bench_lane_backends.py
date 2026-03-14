from __future__ import annotations

from bench_lane_backends import (
    build_batch_payloads,
    normalize_vllm_quantization,
    parse_bool_modes,
)


def test_parse_bool_modes_accepts_on_off_tokens() -> None:
    assert parse_bool_modes("off,on") == [False, True]
    assert parse_bool_modes("true,false,1,0") == [True, False, True, False]


def test_build_batch_payloads_fixed_mode_uses_shared_prefix() -> None:
    payloads = build_batch_payloads(
        model="demo-model",
        max_tokens=64,
        temperature=0.2,
        prompt_mode="fixed_shared_prefix",
        base_prompt="Hello benchmark prompt",
        batch_index=0,
        concurrency=3,
    )

    assert len(payloads) == 3
    assert payloads[0]["messages"] == payloads[1]["messages"] == payloads[2]["messages"]


def test_build_batch_payloads_varied_mode_injects_unique_nonce() -> None:
    payloads = build_batch_payloads(
        model="demo-model",
        max_tokens=64,
        temperature=0.2,
        prompt_mode="varied_unique_prefix",
        base_prompt="Hello benchmark prompt",
        batch_index=5,
        concurrency=3,
    )

    systems = [payload["messages"][0]["content"] for payload in payloads]
    users = [payload["messages"][1]["content"] for payload in payloads]

    # Unique nonce at the start should defeat cross-request prefix reuse.
    assert len(set(systems)) == 3
    assert len(set(users)) == 3


def test_normalize_vllm_quantization_auto_infers_awq_from_model_name() -> None:
    assert (
        normalize_vllm_quantization("auto", "Qwen/Qwen2.5-32B-Instruct-AWQ")
        == "awq"
    )


def test_normalize_vllm_quantization_none_disables_quantization() -> None:
    assert normalize_vllm_quantization("none", "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B") == ""
