"""Run a small GuideLLM benchmark and persist its safe summary."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

import httpx

DATASET = "openai/gsm8k"
_SECRET_KEYS = {"api_key", "apikey", "authorization", "password", "secret", "token"}
_SERVING_KEYS = {
    "tensor_parallel_size",
    "pipeline_parallel_size",
    "kv_cache_dtype",
    "kv_cache_memory_bytes",
    "max_num_seqs",
    "max_num_batched_tokens",
    "enable_prefix_caching",
    "max_model_len",
    "gpu_memory_utilization",
    "quantization",
    "dtype",
    "enforce_eager",
    "disable_custom_all_reduce",
    "hf_overrides",
}

BENCHMARK_JOB_HEADER = "x-logos-benchmark-job-id"
BENCHMARK_PROVIDER_HEADER = "x-logos-benchmark-provider-id"
BENCHMARK_TOKEN_HEADER = "x-logos-benchmark-token"
BENCHMARK_PHASE_HEADER = "x-logos-benchmark-phase"


def benchmark_affinity_token(*, secret: str, job_id: int, provider_id: int, model: str) -> str:
    """Sign the worker affinity carried by one internal benchmark job."""
    message = f"{int(job_id)}:{int(provider_id)}:{model}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def benchmark_affinity_headers(*, secret: str, job_id: int, provider_id: int, model: str) -> dict[str, str]:
    """Build the short-lived, signed routing headers used by GuideLLM."""
    return {
        BENCHMARK_JOB_HEADER: str(int(job_id)),
        BENCHMARK_PROVIDER_HEADER: str(int(provider_id)),
        BENCHMARK_TOKEN_HEADER: benchmark_affinity_token(
            secret=secret,
            job_id=job_id,
            provider_id=provider_id,
            model=model,
        ),
        BENCHMARK_PHASE_HEADER: "measurement",
    }


async def send_warmup_request(
    *,
    target: str,
    model: str,
    api_key: str | None,
    request_headers: dict[str, str] | None,
) -> None:
    """Send one unmeasured completion through the benchmark's exact route."""
    headers = dict(request_headers or {})
    headers[BENCHMARK_PHASE_HEADER] = "warmup"
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"

    normalized_target = target.rstrip("/")
    warmup_url = (
        f"{normalized_target}/chat/completions"
        if urlsplit(normalized_target).path.rstrip("/").endswith("/v1")
        else f"{normalized_target}/v1/chat/completions"
    )

    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0)) as client:
        response = await client.post(
            warmup_url,
            headers=headers,
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Reply with OK."}],
                "max_tokens": 1,
                "stream": False,
            },
        )
    if response.is_error:
        detail = response.text[:500]
        if api_key:
            detail = detail.replace(api_key, "[redacted]")
        raise RuntimeError(f"Benchmark warm-up failed with HTTP {response.status_code}: {detail}")


def resolve_benchmark_target(
    target: str,
    *,
    logos_domain: str | None = None,
    internal_base_url: str | None = None,
) -> str:
    """Use the container-local API when benchmarking this Logos instance."""
    normalized = target.rstrip("/")
    configured_domain = (logos_domain if logos_domain is not None else os.getenv("LOGOS_DOMAIN", "")).strip()
    if not is_logos_benchmark_target(normalized, logos_domain=configured_domain):
        return normalized

    internal = (
        internal_base_url
        if internal_base_url is not None
        else os.getenv("LOGOS_BENCHMARK_INTERNAL_BASE_URL", "http://127.0.0.1:8080")
    ).rstrip("/")
    path = urlsplit(normalized).path.rstrip("/")
    return f"{internal}{path}"


def is_logos_benchmark_target(target: str, *, logos_domain: str | None = None) -> bool:
    """Return whether ``target`` addresses this configured Logos instance."""
    configured_domain = (logos_domain if logos_domain is not None else os.getenv("LOGOS_DOMAIN", "")).strip()
    if not configured_domain:
        return False
    domain_url = configured_domain if "://" in configured_domain else f"//{configured_domain}"
    return urlsplit(target).hostname == urlsplit(domain_url).hostname


def redact_secrets(value: Any) -> Any:
    """Remove credential-like fields recursively before persistence."""
    if isinstance(value, dict):

        def is_secret_key(key: object) -> bool:
            normalized = str(key).lower()
            return normalized in _SECRET_KEYS or normalized.endswith(
                ("-api-key", "_api_key", "-authorization", "_authorization", "-secret", "_secret", "-token", "_token")
            )

        return {key: redact_secrets(item) for key, item in value.items() if not is_secret_key(key)}
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


def build_scenario(
    *,
    target: str,
    model: str,
    api_key: str | None,
    samples: int,
    max_output_tokens: int,
    report_path: Path,
    request_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the fixed, reproducible GSM8K scenario used by Logos."""
    backend: dict[str, Any] = {
        "kind": "openai_http",
        "target": target.rstrip("/"),
        "model": model,
        "request_format": "/v1/chat/completions",
        "extras": {"body": {"max_tokens": max_output_tokens}},
    }
    if api_key:
        backend["api_key"] = api_key
    if request_headers:
        backend["extras"]["headers"] = dict(request_headers)

    return {
        "metadata": {"labels": {"dataset": DATASET, "purpose": "logos-model-provider-performance"}},
        "spec": {
            "backend": backend,
            "profile": {"kind": "synchronous"},
            "constraints": [
                {"kind": "max_requests", "count": samples},
                {"kind": "max_errors", "count": 1},
            ],
            "data": [
                {
                    "kind": "huggingface",
                    "source": DATASET,
                    "load_kwargs": {"name": "main", "split": "test"},
                }
            ],
            "data_column_mapper": {
                "kind": "generative_column_mapper",
                "column_mappings": {"text_column": "question"},
            },
            "data_loader": {"kind": "pytorch", "samples": samples, "shuffle": False},
            "seed": {"kind": "static", "value": 42},
            "metrics": {"kind": "generative", "sample_size": 0},
            "outputs": [{"kind": "json", "path": str(report_path)}],
        },
    }


def extract_serving_configuration(snapshot: dict[str, Any] | None, model: str) -> dict[str, Any]:
    """Capture the live vLLM lane configuration for the benchmarked model."""
    runtime = (snapshot or {}).get("runtime")
    if not isinstance(runtime, dict):
        return {}
    lanes = runtime.get("lanes")
    if not isinstance(lanes, list):
        return {}

    for lane in lanes:
        if not isinstance(lane, dict) or lane.get("model") != model:
            continue
        lane_config = lane.get("lane_config")
        if not isinstance(lane_config, dict):
            lane_config = {}
        vllm_config = lane_config.get("vllm_config")
        if not isinstance(vllm_config, dict):
            vllm_config = {}
        result = {key: vllm_config[key] for key in _SERVING_KEYS if key in vllm_config}
        if "kv_cache_memory_bytes" in result:
            result["kv_cache_memory"] = result.pop("kv_cache_memory_bytes")
        if lane_config.get("gpu_devices"):
            result["gpu_devices"] = lane_config["gpu_devices"]
        if lane.get("command"):
            result["command"] = lane["command"]
        return redact_secrets(result)
    return {}


def successful_summary(
    report: dict[str, Any],
    *,
    model_provider_id: int,
    expected_samples: int,
    serving_configuration: dict[str, Any],
) -> dict[str, Any]:
    """Normalize exactly one complete, error-free benchmark result."""
    for benchmark in report.get("benchmarks", []):
        metrics = benchmark.get("metrics", {})
        totals = metrics.get("request_totals", {})
        successful = int(totals.get("successful", 0))
        incomplete = int(totals.get("incomplete", 0))
        errored = int(totals.get("errored", 0))
        total = int(totals.get("total", 0))
        if successful != expected_samples or total != expected_samples or incomplete or errored:
            continue

        end_time = benchmark.get("end_time")
        if end_time is None:
            end_time = benchmark.get("scheduler_metrics", {}).get("measure_end_time")
        recorded_at = (
            datetime.fromtimestamp(float(end_time), timezone.utc)
            if end_time is not None
            else datetime.now(timezone.utc)
        )
        return {
            "model_provider_id": model_provider_id,
            "configuration": {
                "tool": "guidellm",
                "metadata": redact_secrets(report.get("metadata", {})),
                "scenario": redact_secrets(report.get("config", {})),
                "benchmark": redact_secrets(benchmark.get("config", {})),
                "serving": serving_configuration,
            },
            "dataset": DATASET,
            "sample_size": total,
            "metrics": metrics,
            "recorded_at": recorded_at,
        }
    raise RuntimeError(f"GuideLLM did not complete all {expected_samples} requests successfully")


async def run_benchmark_job(
    *,
    job_id: int,
    model_provider_id: int,
    target: str,
    model: str,
    api_key: str | None,
    samples: int,
    max_output_tokens: int,
    serving_configuration: dict[str, Any],
    serving_configuration_getter: Callable[[], dict[str, Any]] | None = None,
    request_headers: dict[str, str] | None = None,
    worker_preparer: Callable[[], Awaitable[bool]] | None = None,
) -> None:
    """Execute GuideLLM outside the event loop and update the shared job row."""
    from logos.dbutils.dbmanager import DBManager
    from logos.dbutils.dbmodules import JobStatus

    with DBManager() as db:
        db.update_job_status(
            job_id,
            JobStatus.RUNNING.value,
            result_payload={"stage": "preparing_worker", "started_samples": 0, "total_samples": samples},
        )

    try:
        guidellm_bin = shutil.which("guidellm")
        if guidellm_bin is None:
            raise RuntimeError("GuideLLM executable is not installed in the orchestrator")

        if worker_preparer is not None and not await worker_preparer():
            raise RuntimeError("The selected worker could not prepare the benchmark model")

        with DBManager() as db:
            db.update_job_status(
                job_id,
                JobStatus.RUNNING.value,
                result_payload={"stage": "warming_up", "started_samples": 0, "total_samples": samples},
            )
        await send_warmup_request(
            target=target,
            model=model,
            api_key=api_key,
            request_headers=request_headers,
        )

        with DBManager() as db:
            db.update_job_status(
                job_id,
                JobStatus.RUNNING.value,
                result_payload={"stage": "benchmarking", "started_samples": 0, "total_samples": samples},
            )

        with tempfile.TemporaryDirectory(prefix="logos-guidellm-") as directory:
            workdir = Path(directory)
            report_path = workdir / "benchmarks.json"
            scenario_path = workdir / "scenario.json"
            scenario = build_scenario(
                target=target,
                model=model,
                api_key=api_key,
                samples=samples,
                max_output_tokens=max_output_tokens,
                report_path=report_path,
                request_headers=request_headers,
            )
            scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
            scenario_path.chmod(0o600)

            env = os.environ.copy()
            process = await asyncio.create_subprocess_exec(
                guidellm_bin,
                "run",
                "--config",
                str(scenario_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=7200)
            except TimeoutError:
                process.kill()
                await process.communicate()
                raise RuntimeError("GuideLLM benchmark timed out after two hours")
            if process.returncode != 0:
                output = (stderr or stdout).decode("utf-8", errors="replace")
                if api_key:
                    output = output.replace(api_key, "[redacted]")
                last_line = next((line.strip() for line in reversed(output.splitlines()) if line.strip()), "")
                raise RuntimeError(f"GuideLLM exited with code {process.returncode}: {last_line[:500]}")
            if not report_path.is_file():
                raise RuntimeError("GuideLLM did not create a benchmark report")

            report = json.loads(report_path.read_text(encoding="utf-8"))
            if serving_configuration_getter is not None:
                serving_configuration = {
                    **serving_configuration,
                    **serving_configuration_getter(),
                }
            summary = successful_summary(
                report,
                model_provider_id=model_provider_id,
                expected_samples=samples,
                serving_configuration=serving_configuration,
            )

        with DBManager() as db:
            benchmark_id = db.insert_model_provider_benchmark(**summary)
            db.update_job_status(
                job_id,
                JobStatus.SUCCESS.value,
                result_payload={"stage": "completed", "benchmark_id": benchmark_id},
                error_message=None,
            )
    except Exception as exc:
        message = str(exc)
        if api_key:
            message = message.replace(api_key, "[redacted]")
        with DBManager() as db:
            db.update_job_status(job_id, JobStatus.FAILED.value, error_message=message[:1000])
