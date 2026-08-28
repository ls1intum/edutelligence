import importlib
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from logos.benchmarks.guidellm_runner import (
    BENCHMARK_PHASE_HEADER,
    BENCHMARK_PROVIDER_HEADER,
    BENCHMARK_TOKEN_HEADER,
    benchmark_affinity_headers,
    build_scenario,
    extract_serving_configuration,
    is_logos_benchmark_target,
    redact_secrets,
    resolve_benchmark_target,
    send_warmup_request,
    successful_summary,
)


def test_build_scenario_uses_fixed_gsm8k_test_split() -> None:
    affinity_headers = benchmark_affinity_headers(
        secret="internal-secret",
        job_id=17,
        provider_id=23,
        model="Qwen/Qwen2.5-Coder-7B-Instruct-AWQ",
    )
    scenario = build_scenario(
        target="https://provider.example/",
        model="Qwen/Qwen2.5-Coder-7B-Instruct-AWQ",
        api_key="provider-secret",
        samples=5,
        max_output_tokens=512,
        report_path=Path("/tmp/benchmarks.json"),
        request_headers=affinity_headers,
    )

    assert scenario["spec"]["backend"]["target"] == "https://provider.example"
    assert scenario["spec"]["backend"]["api_key"] == "provider-secret"
    assert scenario["spec"]["data"][0]["source"] == "openai/gsm8k"
    assert scenario["spec"]["data"][0]["load_kwargs"] == {"name": "main", "split": "test"}
    assert scenario["spec"]["data_loader"]["samples"] == 5
    assert scenario["spec"]["backend"]["extras"]["headers"][BENCHMARK_PROVIDER_HEADER] == "23"
    assert scenario["spec"]["backend"]["extras"]["headers"][BENCHMARK_PHASE_HEADER] == "measurement"
    assert scenario["spec"]["backend"]["extras"]["headers"][BENCHMARK_TOKEN_HEADER]


@pytest.mark.asyncio
async def test_warmup_request_uses_affinity_without_becoming_a_measurement(monkeypatch) -> None:
    response = AsyncMock()
    response.is_error = False
    post = AsyncMock(return_value=response)

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return await post(*args, **kwargs)

    runner = importlib.import_module("logos.benchmarks.guidellm_runner")
    monkeypatch.setattr(runner.httpx, "AsyncClient", Client)
    headers = benchmark_affinity_headers(secret="secret", job_id=1, provider_id=2, model="org/model")

    await send_warmup_request(
        target="http://logos.internal",
        model="org/model",
        api_key="api-secret",
        request_headers=headers,
    )

    call = post.await_args
    assert call.args[0] == "http://logos.internal/v1/chat/completions"
    assert call.kwargs["headers"][BENCHMARK_PHASE_HEADER] == "warmup"
    assert call.kwargs["headers"]["authorization"] == "Bearer api-secret"
    assert call.kwargs["json"]["max_tokens"] == 1


def test_resolve_benchmark_target_uses_internal_api_for_own_domain() -> None:
    assert (
        resolve_benchmark_target(
            "https://logos-dev.aet.cit.tum.de/v1/",
            logos_domain="logos-dev.aet.cit.tum.de",
            internal_base_url="http://127.0.0.1:8080",
        )
        == "http://127.0.0.1:8080/v1"
    )


def test_resolve_benchmark_target_preserves_external_provider() -> None:
    assert (
        resolve_benchmark_target(
            "https://provider.example/v1/",
            logos_domain="logos-dev.aet.cit.tum.de",
            internal_base_url="http://127.0.0.1:8080",
        )
        == "https://provider.example/v1"
    )


def test_only_configured_logos_domain_is_an_internal_benchmark_target() -> None:
    assert is_logos_benchmark_target(
        "https://logos-dev.aet.cit.tum.de/v1",
        logos_domain="logos-dev.aet.cit.tum.de",
    )
    assert not is_logos_benchmark_target(
        "https://provider.example/v1",
        logos_domain="logos-dev.aet.cit.tum.de",
    )


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
    assert redact_secrets({"headers": {BENCHMARK_TOKEN_HEADER: "signed", "accept": "json"}}) == {
        "headers": {"accept": "json"}
    }


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
