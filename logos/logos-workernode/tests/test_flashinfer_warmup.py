from __future__ import annotations

from logos_worker_node.flashinfer_warmup import kernel_configs_for_models


def test_kernel_configs_for_models_uses_safe_turing_capability_set() -> None:
    configs = kernel_configs_for_models(
        [
            "Qwen/Qwen2.5-Coder-7B-Instruct-AWQ",
            "Qwen/Qwen2.5-14B-Instruct-AWQ",
            "solidrust/Mistral-7B-Instruct-v0.3-AWQ",
            "MidnightPhreaker/Qwen3-Embedding-4B-AWQ-4Bit",
        ]
    )

    assert configs == [
        (28, 4, 128),
        (40, 8, 128),
        (32, 8, 128),
    ]


def test_kernel_configs_for_models_falls_back_to_default_set() -> None:
    assert kernel_configs_for_models([]) == [
        (32, 8, 128),
        (28, 4, 128),
        (40, 8, 128),
    ]
