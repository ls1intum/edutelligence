import asyncio
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
    credential_transport_is_secure,
    extract_serving_configuration,
    internal_benchmark_target,
    is_logos_benchmark_target,
    redact_secrets,
    resolve_benchmark_target,
    run_benchmark_job,
    send_warmup_request,
    successful_summary,
)


@pytest.mark.asyncio
async def test_cancelled_benchmark_is_marked_failed(monkeypatch) -> None:
    updates = []

    class DummyDB:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def update_job_status(self, job_id, status, **kwargs):
            updates.append((job_id, status, kwargs))

    async def cancelled_preparation():
        raise asyncio.CancelledError

    runner = importlib.import_module("logos.benchmarks.guidellm_runner")
    dbmanager = importlib.import_module("logos.dbutils.dbmanager")
    monkeypatch.setattr(runner.shutil, "which", lambda _: "/usr/bin/guidellm")
    monkeypatch.setattr(dbmanager, "DBManager", DummyDB)

    with pytest.raises(asyncio.CancelledError):
        await run_benchmark_job(
            job_id=7,
            model_provider_id=31,
            target="http://127.0.0.1:8080/v1",
            model="org/model",
            api_key=None,
            samples=5,
            max_output_tokens=32,
            serving_configuration={},
            worker_preparer=cancelled_preparation,
        )

    assert updates[-1] == (
        7,
        "failed",
        {"error_message": "Benchmark cancelled before completion"},
    )


@pytest.mark.asyncio
async def test_expired_lease_cancels_benchmark(monkeypatch) -> None:
    updates = []

    class DummyDB:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def update_job_status(self, job_id, status, **kwargs):
            updates.append((job_id, status, kwargs))

        def touch_model_benchmark_job(self, job_id):
            return False

    async def slow_preparation():
        await asyncio.sleep(10)
        return True

    runner = importlib.import_module("logos.benchmarks.guidellm_runner")
    dbmanager = importlib.import_module("logos.dbutils.dbmanager")
    monkeypatch.setattr(runner, "BENCHMARK_LEASE_HEARTBEAT_SECONDS", 0)
    monkeypatch.setattr(runner.shutil, "which", lambda _: "/usr/bin/guidellm")
    monkeypatch.setattr(dbmanager, "DBManager", DummyDB)

    with pytest.raises(asyncio.CancelledError):
        await run_benchmark_job(
            job_id=7,
            model_provider_id=31,
            target="http://127.0.0.1:8080/v1",
            model="org/model",
            api_key=None,
            samples=5,
            max_output_tokens=32,
            serving_configuration={},
            worker_preparer=slow_preparation,
        )

    assert updates[-1][2]["error_message"] == "Benchmark cancelled or lease expired"


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
    assert scenario["spec"]["backend"]["validate_backend"] is False
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


@pytest.mark.asyncio
async def test_warmup_redacts_secrets_before_truncating_error_details(monkeypatch) -> None:
    class Response:
        is_error = True
        status_code = 401
        text = "x" * 499 + "api-secret"

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return Response()

    runner = importlib.import_module("logos.benchmarks.guidellm_runner")
    monkeypatch.setattr(runner.httpx, "AsyncClient", Client)

    with pytest.raises(RuntimeError) as exc_info:
        await send_warmup_request(
            target="http://127.0.0.1:8080",
            model="org/model",
            api_key="api-secret",
            request_headers={},
        )

    assert "api-secret" not in str(exc_info.value)


def test_resolve_benchmark_target_uses_internal_api_for_own_domain() -> None:
    assert (
        resolve_benchmark_target(
            "https://logos-dev.aet.cit.tum.de/v1/",
            logos_domain="logos-dev.aet.cit.tum.de",
            internal_base_url="http://127.0.0.1:8080",
        )
        == "http://127.0.0.1:8080/v1"
    )


def test_internal_benchmark_target_is_job_scoped() -> None:
    assert (
        internal_benchmark_target(17, internal_base_url="http://127.0.0.1:8080/")
        == "http://127.0.0.1:8080/internal/model_benchmarks/jobs/17"
    )


def test_internal_benchmark_target_rejects_plaintext_non_loopback_transport() -> None:
    with pytest.raises(ValueError, match="HTTPS or a loopback"):
        internal_benchmark_target(17, internal_base_url="http://orchestrator.internal:8080")


def test_credential_transport_accepts_https_and_loopback_only() -> None:
    assert credential_transport_is_secure("https://provider.example/v1")
    assert credential_transport_is_secure("http://localhost:8080/v1")
    assert credential_transport_is_secure("http://127.0.0.1:8080/v1")
    assert not credential_transport_is_secure("http://provider.example/v1")


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
