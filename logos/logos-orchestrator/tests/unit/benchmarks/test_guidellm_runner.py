from pathlib import Path

import pytest

from logos.benchmarks.guidellm_runner import (
    build_scenario,
    extract_serving_configuration,
    redact_secrets,
    successful_summary,
)


def test_build_scenario_uses_fixed_gsm8k_test_split() -> None:
    scenario = build_scenario(
        target="https://provider.example/",
        model="Qwen/Qwen2.5-Coder-7B-Instruct-AWQ",
        api_key="provider-secret",
        samples=5,
        max_output_tokens=512,
        report_path=Path("/tmp/benchmarks.json"),
    )

    assert scenario["spec"]["backend"]["target"] == "https://provider.example"
    assert scenario["spec"]["backend"]["api_key"] == "provider-secret"
    assert scenario["spec"]["data"][0]["source"] == "openai/gsm8k"
    assert scenario["spec"]["data"][0]["load_kwargs"] == {"name": "main", "split": "test"}
    assert scenario["spec"]["data_loader"]["samples"] == 5


def test_redaction_and_serving_snapshot_never_keep_credentials() -> None:
    snapshot = {
        "runtime": {
            "lanes": [
                {
                    "model": "Qwen/Qwen2.5",
                    "lane_config": {
                        "gpu_devices": "1",
                        "vllm_config": {
                            "tensor_parallel_size": 1,
                            "max_model_len": 40960,
                            "kv_cache_memory_bytes": "4G",
                            "api_key": "must-not-survive",
                        },
                    },
                }
            ]
        }
    }

    serving = extract_serving_configuration(snapshot, "Qwen/Qwen2.5")

    assert serving == {
        "tensor_parallel_size": 1,
        "max_model_len": 40960,
        "kv_cache_memory": "4G",
        "gpu_devices": "1",
    }
    assert redact_secrets({"nested": {"token": "secret", "safe": 1}}) == {"nested": {"safe": 1}}


def test_successful_summary_requires_every_requested_sample() -> None:
    report = {
        "config": {"backend": {"api_key": "secret", "model": "Qwen/Qwen2.5"}},
        "benchmarks": [
            {
                "config": {"profile": {"kind": "synchronous"}},
                "metrics": {"request_totals": {"successful": 5, "incomplete": 0, "errored": 0, "total": 5}},
            }
        ],
    }

    summary = successful_summary(
        report,
        model_provider_id=3,
        expected_samples=5,
        serving_configuration={"tensor_parallel_size": 1},
    )

    assert summary["sample_size"] == 5
    assert summary["configuration"]["serving"] == {"tensor_parallel_size": 1}
    assert "api_key" not in summary["configuration"]["scenario"]["backend"]

    with pytest.raises(RuntimeError, match="all 6 requests"):
        successful_summary(
            report,
            model_provider_id=3,
            expected_samples=6,
            serving_configuration={},
        )
