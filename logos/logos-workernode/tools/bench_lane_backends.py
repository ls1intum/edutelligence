#!/usr/bin/env python3
"""
Sequential lane benchmark: vLLM vs Ollama.

This script benchmarks the two backends one after the other (never in
parallel VRAM residency):
  1) apply vLLM lane, warm up, run concurrency sweep
  2) replace with Ollama lane, warm up, run the same sweep

Outputs:
  - timestamped JSON summary
  - timestamped CSV rows
  - terminal comparison table
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

DEFAULT_PROMPT = (
    "Review this Python function for correctness and style. "
    "Give 3 concrete improvements with line references.\n\n"
    "```python\n"
    "def fibonacci(n):\n"
    "    if n <= 0:\n"
    "        return []\n"
    "    elif n == 1:\n"
    "        return [0]\n"
    "    fib = [0, 1]\n"
    "    for i in range(2, n):\n"
    "        fib.append(fib[i-1] + fib[i-2])\n"
    "    return fib\n"
    "```\n"
)

DEFAULT_SYSTEM_PROMPT = (
    "You are a strict senior code reviewer. Be concise, factual, and directly actionable."
)

VARIED_PROMPT_TEMPLATES = [
    (
        "Find one correctness bug and one style issue in this function. "
        "Output exactly two bullets.\n\n{code}"
    ),
    (
        "Write three edge-case unit tests for this function. "
        "Return JSON with keys test_name and assertion.\n\n{code}"
    ),
    (
        "Estimate time and space complexity, then propose one optimization. "
        "Max 120 words.\n\n{code}"
    ),
    (
        "Refactor this function for readability while preserving behavior. "
        "Return only the rewritten code block.\n\n{code}"
    ),
    (
        "Explain why this implementation might fail for large inputs and suggest a fix. "
        "Give two numbered points.\n\n{code}"
    ),
    (
        "Convert this review into a rubric with scores 1-5 for correctness, style, tests. "
        "Return compact JSON.\n\n{code}"
    ),
]


def parse_concurrency(raw: str) -> list[int]:
    values = [int(v.strip()) for v in raw.split(",") if v.strip()]
    if not values:
        raise ValueError("Concurrency list is empty")
    if any(v < 1 for v in values):
        raise ValueError("Concurrency values must be >= 1")
    return values


def parse_bool_modes(raw: str) -> list[bool]:
    values: list[bool] = []
    mapping = {
        "on": True,
        "off": False,
        "true": True,
        "false": False,
        "1": True,
        "0": False,
    }
    for token in raw.split(","):
        key = token.strip().lower()
        if not key:
            continue
        if key not in mapping:
            raise ValueError(
                "Invalid boolean mode token "
                f"{token!r}. Use comma-separated values from: on,off,true,false,1,0."
            )
        values.append(mapping[key])
    if not values:
        raise ValueError("Boolean mode list is empty")
    return values


def normalize_vllm_quantization(raw: str | None, model_name: str) -> str:
    """Normalize quantization CLI input for lane config.

    Accepted values:
      - ``auto`` / empty: infer from model name suffix (``*awq*`` -> ``awq``)
      - ``none`` / ``null``: disable quantization flag
      - any other token: pass through (e.g. ``awq``, ``gptq``, ``gguf``)
    """
    token = (raw or "").strip()
    lowered = token.lower()

    if lowered in {"none", "null"}:
        return ""
    if lowered in {"", "auto"}:
        return "awq" if "awq" in model_name.lower() else ""
    return token


def read_gpu_memory_used_mb() -> list[int] | None:
    """Return per-GPU used memory (MB) from nvidia-smi, or None if unavailable."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            text=True,
            timeout=5,
        )
    except Exception:  # noqa: BLE001
        return None

    values: list[int] = []
    for line in out.splitlines():
        token = line.strip()
        if not token:
            continue
        try:
            values.append(int(token))
        except ValueError:
            return None
    return values or None


async def sample_peak_gpu_memory_mb(
    stop_event: asyncio.Event,
    interval_s: float,
) -> dict[str, Any]:
    baseline = await asyncio.to_thread(read_gpu_memory_used_mb)
    peak_total = sum(baseline) if baseline else None
    peak_per_gpu = list(baseline) if baseline else None

    while not stop_event.is_set():
        current = await asyncio.to_thread(read_gpu_memory_used_mb)
        if current:
            current_total = sum(current)
            if peak_total is None or current_total > peak_total:
                peak_total = current_total
                peak_per_gpu = list(current)
        await asyncio.sleep(interval_s)

    baseline_total = sum(baseline) if baseline else None
    peak_delta = (
        peak_total - baseline_total
        if (peak_total is not None and baseline_total is not None)
        else None
    )
    return {
        "gpu_mem_baseline_total_mb": baseline_total,
        "gpu_mem_peak_total_mb": peak_total,
        "gpu_mem_peak_delta_mb": peak_delta,
        "gpu_mem_peak_per_gpu_mb": peak_per_gpu,
    }


def pctl(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(p * len(ordered)) - 1))
    return ordered[index]


def controller_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


async def controller_json(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    api_key: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = await client.request(
        method=method,
        url=path,
        headers=controller_headers(api_key),
        json=body,
    )
    response.raise_for_status()
    return response.json()


async def apply_single_lane(
    client: httpx.AsyncClient,
    api_key: str,
    lane: dict[str, Any],
) -> dict[str, Any]:
    result = await controller_json(
        client,
        "POST",
        "/admin/lanes/apply",
        api_key,
        {"lanes": [lane]},
    )
    if not result.get("success", False):
        raise RuntimeError(
            f"Lane apply failed: errors={result.get('errors')}, actions={result.get('actions')}"
        )
    return result


async def clear_lanes(client: httpx.AsyncClient, api_key: str) -> None:
    await controller_json(
        client,
        "POST",
        "/admin/lanes/apply",
        api_key,
        {"lanes": []},
    )


async def wait_for_lane_status(
    client: httpx.AsyncClient,
    api_key: str,
    model: str,
    backend: str,
    timeout_s: int = 900,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        lanes = await controller_json(client, "GET", "/admin/lanes", api_key)
        for lane in lanes:
            if lane.get("model") == model and lane.get("backend") == backend:
                if lane.get("process", {}).get("state") == "running":
                    return lane
        await asyncio.sleep(1.0)
    raise TimeoutError(
        f"Timed out waiting for lane model={model!r}, backend={backend!r} to be running"
    )


async def wait_backend_ready(
    base_url: str,
    backend: str,
    timeout_s: int = 900,
) -> None:
    async with httpx.AsyncClient() as client:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                if backend == "vllm":
                    health = await client.get(f"{base_url}/health", timeout=10.0)
                    models = await client.get(f"{base_url}/v1/models", timeout=10.0)
                    if health.status_code == 200 and models.status_code == 200:
                        return
                else:
                    version = await client.get(f"{base_url}/api/version", timeout=10.0)
                    if version.status_code == 200:
                        return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1.0)
    raise TimeoutError(f"{backend} endpoint did not become ready at {base_url}")


async def resolve_openai_model(base_url: str, preferred: str) -> str:
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{base_url}/v1/models", timeout=30.0)
        response.raise_for_status()
        data = response.json()
    ids = [item.get("id", "") for item in data.get("data", []) if item.get("id")]
    if preferred in ids:
        return preferred
    if ids:
        return ids[0]
    return preferred


async def warmup(
    base_url: str,
    model: str,
    warmup_count: int,
    max_tokens: int,
) -> None:
    if warmup_count <= 0:
        return
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Say hello in one word."}],
        "max_tokens": min(max_tokens, 16),
        "temperature": 0.0,
        "stream": False,
    }
    async with httpx.AsyncClient() as client:
        for _ in range(warmup_count):
            response = await client.post(
                f"{base_url}/v1/chat/completions",
                json=payload,
                timeout=600.0,
            )
            response.raise_for_status()


def build_request_payload(
    *,
    model: str,
    max_tokens: int,
    temperature: float,
    prompt_mode: str,
    base_prompt: str,
    batch_index: int,
    req_id: int,
) -> dict[str, Any]:
    if prompt_mode == "fixed_shared_prefix":
        system_prompt = DEFAULT_SYSTEM_PROMPT
        user_prompt = base_prompt
    else:
        # Unique leading nonce in system+user content intentionally defeats
        # prefix sharing, so any throughput delta is not just cache reuse.
        nonce = f"bench-{batch_index:03d}-{req_id:03d}"
        template = VARIED_PROMPT_TEMPLATES[(batch_index + req_id) % len(VARIED_PROMPT_TEMPLATES)]
        system_prompt = f"[{nonce}] {DEFAULT_SYSTEM_PROMPT}"
        user_prompt = f"[{nonce}] {template.format(code=base_prompt)}"

    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
        "stream_options": {"include_usage": True},
    }


def build_batch_payloads(
    *,
    model: str,
    max_tokens: int,
    temperature: float,
    prompt_mode: str,
    base_prompt: str,
    batch_index: int,
    concurrency: int,
) -> list[dict[str, Any]]:
    return [
        build_request_payload(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            prompt_mode=prompt_mode,
            base_prompt=base_prompt,
            batch_index=batch_index,
            req_id=req_id,
        )
        for req_id in range(concurrency)
    ]


async def single_streaming_request(
    client: httpx.AsyncClient,
    url: str,
    payload: dict[str, Any],
    req_id: int,
    request_timeout_s: float,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    first_token_time: float | None = None
    token_chunks = 0
    usage_completion_tokens: int | None = None

    try:
        async with client.stream("POST", url, json=payload, timeout=request_timeout_s) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line[6:].strip()
                if raw == "[DONE]":
                    break
                try:
                    chunk = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                usage = chunk.get("usage") or {}
                completion_tokens = usage.get("completion_tokens")
                if isinstance(completion_tokens, int) and completion_tokens >= 0:
                    usage_completion_tokens = completion_tokens

                choice = (chunk.get("choices") or [{}])[0]
                delta = choice.get("delta") or {}
                piece = (
                    (delta.get("content") or "")
                    + (delta.get("reasoning") or "")
                    + (delta.get("reasoning_content") or "")
                )
                if piece:
                    if first_token_time is None:
                        first_token_time = time.perf_counter()
                    token_chunks += 1
    except Exception as exc:  # noqa: BLE001
        return {"req_id": req_id, "error": str(exc), "tokens": 0, "latency": 0.0, "ttft": 0.0}

    total = time.perf_counter() - t0
    ttft = (first_token_time - t0) if first_token_time is not None else total
    token_count = usage_completion_tokens if usage_completion_tokens is not None else token_chunks
    return {
        "req_id": req_id,
        "tokens": token_count,
        "latency": total,
        "ttft": ttft,
        "tok_per_sec": token_count / total if total > 0 else 0.0,
    }


async def run_batch(
    base_url: str,
    model: str,
    prompt: str,
    max_tokens: int,
    concurrency: int,
    prompt_mode: str,
    batch_index: int,
    temperature: float,
    payload_sample_count: int,
    collect_gpu_memory: bool,
    gpu_mem_sample_interval_s: float,
    request_timeout_s: float,
    batch_timeout_s: float,
) -> dict[str, Any]:
    payloads = build_batch_payloads(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        prompt_mode=prompt_mode,
        base_prompt=prompt,
        batch_index=batch_index,
        concurrency=concurrency,
    )
    url = f"{base_url}/v1/chat/completions"

    mem_metrics: dict[str, Any] = {
        "gpu_mem_baseline_total_mb": None,
        "gpu_mem_peak_total_mb": None,
        "gpu_mem_peak_delta_mb": None,
        "gpu_mem_peak_per_gpu_mb": None,
    }
    mem_stop = asyncio.Event()
    mem_task: asyncio.Task | None = None
    if collect_gpu_memory:
        mem_task = asyncio.create_task(
            sample_peak_gpu_memory_mb(
                stop_event=mem_stop,
                interval_s=gpu_mem_sample_interval_s,
            )
        )

    timed_out = False
    try:
        async with httpx.AsyncClient() as client:
            tasks = [
                single_streaming_request(client, url, payload, i, request_timeout_s)
                for i, payload in enumerate(payloads)
            ]
            t_batch_start = time.perf_counter()
            if batch_timeout_s > 0:
                try:
                    results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=batch_timeout_s)
                except asyncio.TimeoutError:
                    timed_out = True
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    results = [
                        {
                            "req_id": i,
                            "error": f"batch timeout after {batch_timeout_s:.1f}s",
                            "tokens": 0,
                            "latency": 0.0,
                            "ttft": 0.0,
                        }
                        for i in range(concurrency)
                    ]
            else:
                results = await asyncio.gather(*tasks)
            t_batch_total = time.perf_counter() - t_batch_start
    finally:
        if mem_task is not None:
            mem_stop.set()
            mem_metrics = await mem_task

    errors = [result for result in results if "error" in result]
    ok = [result for result in results if "error" not in result]

    if not ok:
        out = {
            "concurrency": concurrency,
            "requests_ok": 0,
            "errors": len(errors),
            "error_rate": round(len(errors) / concurrency, 3),
            "error_msgs": [item["error"] for item in errors[:3]],
            "payload_samples": payloads[:payload_sample_count],
            **mem_metrics,
        }
        if timed_out:
            out["batch_timeout"] = True
        return out

    total_tokens = sum(result["tokens"] for result in ok)
    latencies = [result["latency"] for result in ok]
    ttfts = [result["ttft"] for result in ok]
    per_req_tps = [result["tok_per_sec"] for result in ok]

    out = {
        "concurrency": concurrency,
        "requests_ok": len(ok),
        "errors": len(errors),
        "error_rate": round(len(errors) / concurrency, 3),
        "total_tokens": total_tokens,
        "batch_time_s": round(t_batch_total, 3),
        "aggregate_tok_s": round(total_tokens / t_batch_total, 3) if t_batch_total > 0 else 0.0,
        "avg_latency_s": round(statistics.mean(latencies), 3),
        "p50_latency_s": round(statistics.median(latencies), 3),
        "p95_latency_s": round(pctl(latencies, 0.95), 3),
        "avg_ttft_ms": round(statistics.mean(ttfts) * 1000, 1),
        "avg_tok_per_req_s": round(statistics.mean(per_req_tps), 3),
        "payload_samples": payloads[:payload_sample_count],
        **mem_metrics,
    }
    if timed_out:
        out["batch_timeout"] = True
    return out


async def benchmark_backend(
    controller_client: httpx.AsyncClient,
    api_key: str,
    run_label: str,
    lane_config: dict[str, Any],
    concurrency_levels: list[int],
    prompt: str,
    prompt_mode: str,
    max_tokens: int,
    warmup_count: int,
    temperature: float,
    payload_sample_count: int,
    collect_gpu_memory: bool,
    gpu_mem_sample_interval_s: float,
    request_timeout_s: float,
    batch_timeout_s: float,
) -> dict[str, Any]:
    model = lane_config["model"]
    backend = lane_config["backend"]
    await apply_single_lane(controller_client, api_key, lane_config)

    lane = await wait_for_lane_status(
        controller_client,
        api_key,
        model=model,
        backend=backend,
    )
    port = int(lane["port"])
    base_url = f"http://127.0.0.1:{port}"
    await wait_backend_ready(base_url, backend)

    openai_model = await resolve_openai_model(base_url, preferred=model)
    await warmup(base_url, model=openai_model, warmup_count=warmup_count, max_tokens=max_tokens)

    rows: list[dict[str, Any]] = []
    payload_samples: list[dict[str, Any]] = []
    for batch_index, concurrency in enumerate(concurrency_levels):
        result = await run_batch(
            base_url=base_url,
            model=openai_model,
            prompt=prompt,
            max_tokens=max_tokens,
            concurrency=concurrency,
            prompt_mode=prompt_mode,
            batch_index=batch_index,
            temperature=temperature,
            payload_sample_count=payload_sample_count,
            collect_gpu_memory=collect_gpu_memory,
            gpu_mem_sample_interval_s=gpu_mem_sample_interval_s,
            request_timeout_s=request_timeout_s,
            batch_timeout_s=batch_timeout_s,
        )
        samples = list(result.get("payload_samples", []))
        if len(payload_samples) < payload_sample_count and samples:
            needed = payload_sample_count - len(payload_samples)
            payload_samples.extend(samples[:needed])
        result.pop("payload_samples", None)
        rows.append(result)

    return {
        "run_label": run_label,
        "backend": backend,
        "configured_model": model,
        "served_model": openai_model,
        "lane_port": port,
        "prompt_mode": prompt_mode,
        "payload_samples": payload_samples,
        "vllm_prefix_caching": lane_config.get("vllm", {}).get("enable_prefix_caching"),
        "ollama_num_parallel": lane_config.get("num_parallel"),
        "results": rows,
    }


def build_comparison(
    backend_results: list[dict[str, Any]],
    reference_run: str | None = None,
) -> list[dict[str, Any]]:
    by_conc: dict[int, dict[str, dict[str, Any]]] = {}
    for result in backend_results:
        run_label = result["run_label"]
        rows = result["results"]
        for row in rows:
            by_conc.setdefault(int(row["concurrency"]), {})[run_label] = row

    labels = [result["run_label"] for result in backend_results]
    chosen_reference = reference_run or next((label for label in labels if label.startswith("vllm_")), None)

    comparison: list[dict[str, Any]] = []
    for conc in sorted(by_conc):
        entry: dict[str, Any] = {"concurrency": conc}
        for run_label, row in by_conc[conc].items():
            entry[f"{run_label}_aggregate_tok_s"] = row.get("aggregate_tok_s")
            entry[f"{run_label}_avg_ttft_ms"] = row.get("avg_ttft_ms")

        if chosen_reference and chosen_reference in by_conc[conc]:
            ref_tps = float(by_conc[conc][chosen_reference].get("aggregate_tok_s", 0.0))
            for run_label, row in by_conc[conc].items():
                if run_label == chosen_reference or not run_label.startswith("ollama_"):
                    continue
                run_tps = float(row.get("aggregate_tok_s", 0.0))
                entry[f"speedup_{chosen_reference}_over_{run_label}"] = (
                    round(ref_tps / run_tps, 3) if run_tps > 0 else None
                )
        comparison.append(entry)
    return comparison


def write_csv(path: Path, backend_results: list[dict[str, Any]]) -> None:
    fieldnames = [
        "timestamp_utc",
        "run_label",
        "backend",
        "configured_model",
        "served_model",
        "lane_port",
        "prompt_mode",
        "vllm_prefix_caching",
        "ollama_num_parallel",
        "concurrency",
        "requests_ok",
        "errors",
        "error_rate",
        "total_tokens",
        "batch_time_s",
        "aggregate_tok_s",
        "avg_latency_s",
        "p50_latency_s",
        "p95_latency_s",
        "avg_ttft_ms",
        "avg_tok_per_req_s",
        "gpu_mem_baseline_total_mb",
        "gpu_mem_peak_total_mb",
        "gpu_mem_peak_delta_mb",
        "gpu_mem_peak_per_gpu_mb",
    ]
    now = datetime.now(timezone.utc).isoformat()
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for backend in backend_results:
            for row in backend["results"]:
                writer.writerow({
                    "timestamp_utc": now,
                    "run_label": backend["run_label"],
                    "backend": backend["backend"],
                    "configured_model": backend["configured_model"],
                    "served_model": backend["served_model"],
                    "lane_port": backend["lane_port"],
                    "prompt_mode": backend["prompt_mode"],
                    "vllm_prefix_caching": backend.get("vllm_prefix_caching"),
                    "ollama_num_parallel": backend.get("ollama_num_parallel"),
                    "concurrency": row.get("concurrency"),
                    "requests_ok": row.get("requests_ok"),
                    "errors": row.get("errors"),
                    "error_rate": row.get("error_rate"),
                    "total_tokens": row.get("total_tokens"),
                    "batch_time_s": row.get("batch_time_s"),
                    "aggregate_tok_s": row.get("aggregate_tok_s"),
                    "avg_latency_s": row.get("avg_latency_s"),
                    "p50_latency_s": row.get("p50_latency_s"),
                    "p95_latency_s": row.get("p95_latency_s"),
                    "avg_ttft_ms": row.get("avg_ttft_ms"),
                    "avg_tok_per_req_s": row.get("avg_tok_per_req_s"),
                    "gpu_mem_baseline_total_mb": row.get("gpu_mem_baseline_total_mb"),
                    "gpu_mem_peak_total_mb": row.get("gpu_mem_peak_total_mb"),
                    "gpu_mem_peak_delta_mb": row.get("gpu_mem_peak_delta_mb"),
                    "gpu_mem_peak_per_gpu_mb": row.get("gpu_mem_peak_per_gpu_mb"),
                })


def print_summary(backend_results: list[dict[str, Any]], comparison: list[dict[str, Any]]) -> None:
    print("\nBackend Results")
    for backend in backend_results:
        print(
            f"\n[{backend['run_label']}] backend={backend['backend']} "
            f"configured={backend['configured_model']} served={backend['served_model']} "
            f"lane_port={backend['lane_port']} prompt_mode={backend['prompt_mode']}"
        )
        print(
            f"{'N':>4} {'Agg tok/s':>10} {'Avg lat':>10} {'P95 lat':>10} "
            f"{'TTFT ms':>10} {'Mem GB':>8} {'Errors':>8} {'Err %':>8}"
        )
        print("-" * 82)
        for row in backend["results"]:
            peak_mb = row.get("gpu_mem_peak_total_mb")
            peak_gb = (float(peak_mb) / 1024.0) if isinstance(peak_mb, (int, float)) else None
            mem_text = f"{peak_gb:>7.1f}" if peak_gb is not None else f"{'-':>7}"
            if "error_msgs" in row:
                print(
                    f"{row['concurrency']:>4} {'FAILED':>10} {'-':>10} "
                    f"{'-':>10} {'-':>10} {mem_text:>8} {row['errors']:>8} "
                    f"{100.0 * float(row.get('error_rate', 0.0)):>7.1f}%"
                )
            else:
                print(
                    f"{row['concurrency']:>4} "
                    f"{row['aggregate_tok_s']:>10.3f} "
                    f"{row['avg_latency_s']:>10.3f} "
                    f"{row['p95_latency_s']:>10.3f} "
                    f"{row['avg_ttft_ms']:>10.1f} "
                    f"{mem_text:>8} "
                    f"{row['errors']:>8} "
                    f"{100.0 * float(row.get('error_rate', 0.0)):>7.1f}%"
                )

    label_order = [backend["run_label"] for backend in backend_results]
    print("\nComparison (aggregate tok/s by run)")
    print(f"{'N':>4} " + " ".join(f"{label:>16}" for label in label_order))
    print("-" * (6 + 17 * len(label_order)))
    for row in comparison:
        metrics = [
            row.get(f"{label}_aggregate_tok_s", "n/a")
            for label in label_order
        ]
        print(f"{row['concurrency']:>4} " + " ".join(f"{metric:>16}" for metric in metrics))

    speedup_keys = sorted(
        {
            key
            for row in comparison
            for key in row
            if key.startswith("speedup_")
        }
    )
    if speedup_keys:
        print("\nSpeedups")
        print(f"{'N':>4} " + " ".join(f"{key.replace('speedup_', ''):>24}" for key in speedup_keys))
        print("-" * (6 + 25 * len(speedup_keys)))
        for row in comparison:
            metrics = []
            for key in speedup_keys:
                val = row.get(key)
                metrics.append(f"{val:.3f}x" if isinstance(val, float) else "n/a")
            print(f"{row['concurrency']:>4} " + " ".join(f"{metric:>24}" for metric in metrics))


def build_run_plan(args: argparse.Namespace) -> list[tuple[str, dict[str, Any]]]:
    vllm_prefix_modes = parse_bool_modes(args.vllm_prefix_caching_modes)
    ollama_parallel_values = parse_concurrency(args.ollama_num_parallel_values)
    vllm_quantization = normalize_vllm_quantization(args.vllm_quantization, args.vllm_model)

    runs: list[tuple[str, dict[str, Any]]] = []

    if args.include_vllm:
        for prefix_mode in vllm_prefix_modes:
            label = f"vllm_prefix_{'on' if prefix_mode else 'off'}"
            runs.append((
                label,
                {
                    "model": args.vllm_model,
                    "backend": "vllm",
                    "context_length": args.max_model_len,
                    "flash_attention": False,
                    "gpu_devices": args.vllm_gpu_devices,
                    "vllm": {
                        "vllm_binary": args.vllm_binary,
                        "tensor_parallel_size": args.tensor_parallel_size,
                        "max_model_len": args.max_model_len,
                        "dtype": args.vllm_dtype,
                        "quantization": vllm_quantization,
                        "gpu_memory_utilization": args.vllm_gpu_memory_utilization,
                        "enforce_eager": args.vllm_enforce_eager,
                        "enable_prefix_caching": prefix_mode,
                        "extra_args": [],
                    },
                },
            ))

    if args.include_ollama:
        for num_parallel in ollama_parallel_values:
            runs.append((
                f"ollama_np{num_parallel}",
                {
                    "model": args.ollama_model,
                    "backend": "ollama",
                    "num_parallel": num_parallel,
                    "context_length": args.max_model_len,
                    "keep_alive": args.ollama_keep_alive,
                    "kv_cache_type": args.ollama_kv_cache_type,
                    "flash_attention": args.ollama_flash_attention,
                    "gpu_devices": args.ollama_gpu_devices,
                },
            ))

    return runs


async def main_async(args: argparse.Namespace) -> int:
    concurrency_levels = parse_concurrency(args.concurrency)
    run_plan = build_run_plan(args)
    if not run_plan:
        raise ValueError("Run plan is empty. Enable at least one backend.")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"lane_benchmark_{stamp}.json"
    csv_path = output_dir / f"lane_benchmark_{stamp}.csv"
    payload_path = output_dir / f"lane_benchmark_payloads_{stamp}.json"

    timeout = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)
    async with httpx.AsyncClient(base_url=args.controller_url.rstrip("/"), timeout=timeout) as controller_client:
        backend_results: list[dict[str, Any]] = []
        try:
            for idx, (run_label, lane_config) in enumerate(run_plan):
                if idx > 0:
                    await clear_lanes(controller_client, args.api_key)
                print(
                    f"Running {run_label} benchmark "
                    f"(backend={lane_config['backend']} model={lane_config['model']})..."
                )
                backend_result = await benchmark_backend(
                    controller_client=controller_client,
                    api_key=args.api_key,
                    run_label=run_label,
                    lane_config=lane_config,
                    concurrency_levels=concurrency_levels,
                    prompt=args.prompt,
                    prompt_mode=args.prompt_mode,
                    max_tokens=args.max_tokens,
                    warmup_count=args.warmup,
                    temperature=args.temperature,
                    payload_sample_count=args.payload_sample_count,
                    collect_gpu_memory=args.collect_gpu_memory,
                    gpu_mem_sample_interval_s=args.gpu_mem_sample_interval_s,
                    request_timeout_s=args.request_timeout_s,
                    batch_timeout_s=args.batch_timeout_s,
                )
                backend_results.append(backend_result)
        finally:
            if not args.keep_last_lane:
                try:
                    await clear_lanes(controller_client, args.api_key)
                except Exception as exc:  # noqa: BLE001
                    print(f"Warning: failed to clear lanes: {exc}")

    comparison = build_comparison(backend_results=backend_results, reference_run=args.reference_run)
    payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "controller_url": args.controller_url,
        "concurrency": concurrency_levels,
        "max_tokens": args.max_tokens,
        "warmup": args.warmup,
        "prompt_mode": args.prompt_mode,
        "temperature": args.temperature,
        "run_plan": [
            {"run_label": run_label, "lane_config": lane_config}
            for run_label, lane_config in run_plan
        ],
        "backends": backend_results,
        "comparison": comparison,
    }
    payload_samples = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "prompt_mode": args.prompt_mode,
        "runs": [
            {
                "run_label": backend["run_label"],
                "backend": backend["backend"],
                "configured_model": backend["configured_model"],
                "payload_samples": backend.get("payload_samples", []),
            }
            for backend in backend_results
        ],
    }

    json_path.write_text(json.dumps(payload, indent=2))
    payload_path.write_text(json.dumps(payload_samples, indent=2))
    write_csv(csv_path, backend_results)
    print_summary(backend_results, comparison)
    print(f"\nSaved JSON: {json_path}")
    print(f"Saved CSV:  {csv_path}")
    print(f"Saved payload samples: {payload_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sequential lane benchmark: vLLM and Ollama "
            "with optional prefix-caching and num_parallel sweeps."
        )
    )
    parser.add_argument("--controller-url", default="http://127.0.0.1:8444")
    parser.add_argument("--api-key", default=os.environ.get("API_KEY", "RANDOM_DEFAULT_KEY"))
    parser.add_argument("--output-dir", default="bench_results")
    parser.add_argument(
        "--include-vllm",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include vLLM runs in the benchmark plan.",
    )
    parser.add_argument(
        "--include-ollama",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include Ollama runs in the benchmark plan.",
    )
    parser.add_argument("--concurrency", default="1,4,8,16,32")
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=200)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument(
        "--prompt-mode",
        choices=["fixed_shared_prefix", "varied_unique_prefix"],
        default="varied_unique_prefix",
        help=(
            "fixed_shared_prefix keeps all requests identical (cache friendly). "
            "varied_unique_prefix injects unique leading nonce and varied tasks "
            "to defeat shared prefix caching."
        ),
    )
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--payload-sample-count", type=int, default=3)
    parser.add_argument(
        "--collect-gpu-memory",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Capture per-batch peak GPU memory via nvidia-smi.",
    )
    parser.add_argument(
        "--gpu-mem-sample-interval-s",
        type=float,
        default=0.25,
        help="Sampling interval for GPU memory collection.",
    )
    parser.add_argument(
        "--request-timeout-s",
        type=float,
        default=900.0,
        help="Per-request streaming timeout in seconds.",
    )
    parser.add_argument(
        "--batch-timeout-s",
        type=float,
        default=0.0,
        help="Optional whole-batch timeout; 0 disables.",
    )
    parser.add_argument("--max-model-len", type=int, default=4096)
    parser.add_argument("--keep-last-lane", action="store_true")
    parser.add_argument(
        "--reference-run",
        default=None,
        help="Optional run label used as speedup baseline (default: first vLLM run).",
    )

    # vLLM lane defaults (explicit profile for Turing + 2x16GB setup)
    parser.add_argument("--vllm-model", default="Qwen/Qwen2.5-Coder-32B-Instruct-AWQ")
    parser.add_argument("--vllm-binary", default="vllm")
    parser.add_argument("--vllm-gpu-devices", default="0,1")
    parser.add_argument("--tensor-parallel-size", type=int, default=2)
    parser.add_argument("--vllm-dtype", default="float16")
    parser.add_argument(
        "--vllm-quantization",
        default="auto",
        help=(
            "Quantization mode for vLLM lane. Use 'auto' (default) to infer "
            "awq for '*AWQ*' model names, 'none' for full precision, or an "
            "explicit token like awq/gptq/gguf."
        ),
    )
    parser.add_argument("--vllm-gpu-memory-utilization", type=float, default=0.90)
    parser.add_argument("--vllm-enforce-eager", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--vllm-prefix-caching-modes",
        default="off,on",
        help="Comma-separated modes: on/off. Example: off,on",
    )

    # Ollama baseline lane defaults
    parser.add_argument("--ollama-model", default="qwen2.5-coder:32b")
    parser.add_argument("--ollama-gpu-devices", default="0,1")
    parser.add_argument(
        "--ollama-num-parallel-values",
        default="2,4,8",
        help="Comma-separated OLLAMA_NUM_PARALLEL sweep values.",
    )
    parser.add_argument("--ollama-keep-alive", default="10m")
    parser.add_argument("--ollama-kv-cache-type", default="q8_0")
    parser.add_argument(
        "--ollama-flash-attention",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("Interrupted")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
