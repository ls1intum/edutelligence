#!/usr/bin/env python3
"""
Replay the same scheduling workload CSVs used by run_api_workload.py against a
bare Ollama instance (no Logos server in between).

Produces output in the same format (summary.csv, detailed.csv, charts) so that
results can be compared directly with the vLLM/Logos benchmarks.

Usage:
    python3 tests/performance/run_ollama_benchmark.py \
        --workload tests/performance/workloads/explicit/10m/workload_explicit_hw3_even_random_150_10m.csv \
        --ollama-base http://localhost:11434 \
        --output-dir tests/performance/results_ollama/hw3_random_10m_150req

The script:
  1. Unloads all models from Ollama (cold start).
  2. Remaps vLLM model names → Ollama Q4_K_M tags.
  3. Replays the workload with the same timing as the original.
  4. Adds a configurable overhead (default 0.5 s) to each measured latency
     to approximate the Logos server overhead absent in direct-to-Ollama calls.
  5. Writes results in the same CSV/chart format as run_api_workload.py.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import httpx

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import ScalarFormatter, MaxNLocator
import numpy as np


# ── Model name mapping: vLLM AWQ → Ollama Q4_K_M ────────────────────────
MODEL_MAP: dict[str, str] = {
    "Qwen/Qwen2.5-Coder-7B-Instruct-AWQ": "qwen2.5-coder:7b-instruct-q4_K_M",
    "Qwen/Qwen2.5-Coder-14B-Instruct-AWQ": "qwen2.5-coder:14b-instruct-q4_K_M",
    "solidrust/Mistral-7B-Instruct-v0.3-AWQ": "mistral:7b-instruct-v0.3-q4_K_M",
}

# Overhead added to each request's measured latency (ms) to approximate
# the Logos server processing time absent in direct-to-Ollama calls.
DEFAULT_OVERHEAD_MS = 500.0

# ── Data structures ──────────────────────────────────────────────────────

@dataclass(slots=True)
class WorkloadEntry:
    request_id: str
    arrival_offset: float  # ms from workload start
    mode: str
    priority: str
    body_json: str
    original_model: str = ""

    def render_payload(self, model_map: dict[str, str]) -> dict:
        body = json.loads(self.body_json)
        self.original_model = body.get("model", "")
        body["model"] = model_map.get(self.original_model, self.original_model)
        return body


@dataclass(slots=True)
class RequestResult:
    request_id: str
    original_model: str
    ollama_model: str
    http_status: int
    client_duration_ms: float
    ttft_ms: Optional[float]
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    total_tokens: Optional[int]
    response_text: Optional[str]
    response_body_json: Optional[str]
    error: Optional[str]
    load_duration_ms: Optional[float]
    request_sent_at: Optional[datetime] = None
    response_received_at: Optional[datetime] = None
    mode: str = ""
    priority: str = ""


# ── Helpers ──────────────────────────────────────────────────────────────

def parse_workload(path: Path) -> List[WorkloadEntry]:
    entries: List[WorkloadEntry] = []
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("Workload CSV is missing a header row.")
        normalized = [h.strip().lower() for h in reader.fieldnames]
        reader.fieldnames = normalized
        for idx, row in enumerate(reader, start=1):
            request_id = row.get("request_id") or f"req-{idx}"
            offset = float(row["arrival_offset"])
            body_json = row.get("body_json", "")
            mode = row.get("mode", "interactive").strip().lower()
            priority = row.get("priority", "mid").strip().lower()
            entries.append(WorkloadEntry(
                request_id=request_id,
                arrival_offset=offset,
                mode=mode,
                priority=priority,
                body_json=body_json,
            ))
    entries.sort(key=lambda e: (e.arrival_offset, e.request_id))
    return entries


def calculate_percentile(values: List[float], p: float) -> float:
    if not values:
        return math.nan
    s = sorted(values)
    k = (len(s) - 1) * (p / 100.0)
    f = int(math.floor(k))
    c = int(math.ceil(k))
    if f == c:
        return s[f]
    return s[f] * (c - k) + s[c] * (k - f)


# ── Ollama interaction ───────────────────────────────────────────────────

async def ensure_models_pulled(base_url: str, models: list[str]) -> None:
    """Pull models that are not yet downloaded."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{base_url}/api/tags")
        resp.raise_for_status()
        local_models = {m["name"] for m in resp.json().get("models", [])}

    needed = [m for m in models if m not in local_models]
    if not needed:
        print("All Ollama models already downloaded.")
        return

    for model in needed:
        print(f"Pulling {model} (this may take a while)...")
        async with httpx.AsyncClient(timeout=3600.0) as client:
            resp = await client.post(
                f"{base_url}/api/pull",
                json={"name": model, "stream": False},
            )
            resp.raise_for_status()
        print(f"  ✓ {model} pulled.")


async def unload_all_models(base_url: str) -> None:
    """Unload all models from Ollama memory for a cold start."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{base_url}/api/ps")
        resp.raise_for_status()
        running = resp.json().get("models", [])

    if not running:
        print("No models loaded in Ollama — cold start confirmed.")
        return

    async with httpx.AsyncClient(timeout=120.0) as client:
        for m in running:
            name = m.get("name", m.get("model", ""))
            print(f"Unloading {name}...")
            await client.post(
                f"{base_url}/api/generate",
                json={"model": name, "keep_alive": 0},
            )
    # Wait a moment for VRAM to free up
    await asyncio.sleep(2.0)
    print("All models unloaded — cold start ready.")


async def dispatch_request(
    client: httpx.AsyncClient,
    base_url: str,
    entry: WorkloadEntry,
    model_map: dict[str, str],
    start_monotonic: float,
) -> RequestResult:
    wait = (entry.arrival_offset / 1000.0) - (asyncio.get_event_loop().time() - start_monotonic)
    if wait > 0:
        await asyncio.sleep(wait)

    payload = entry.render_payload(model_map)
    ollama_model = payload["model"]
    url = f"{base_url}/v1/chat/completions"

    ttft_ms: Optional[float] = None
    response_text: Optional[str] = None
    response_body_json: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    load_duration_ms: Optional[float] = None

    request_sent_at = datetime.now(timezone.utc)
    start = time.perf_counter()
    try:
        if payload.get("stream") is True:
            content_parts: list[str] = []
            final_chunk: Optional[dict] = None
            async with client.stream("POST", url, json=payload) as response:
                status_code = response.status_code
                first_token_seen = False
                async for line in response.aiter_lines():
                    stripped = line.strip()
                    if not stripped.startswith("data:"):
                        continue
                    data = stripped[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        item = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(item, dict):
                        continue
                    final_chunk = item
                    # Detect TTFT on first content delta
                    if not first_token_seen:
                        for choice in item.get("choices", []):
                            delta = choice.get("delta", {})
                            if delta.get("content"):
                                ttft_ms = (time.perf_counter() - start) * 1000
                                first_token_seen = True
                                break
                    # Collect content
                    for choice in item.get("choices", []):
                        delta = choice.get("delta", {})
                        piece = delta.get("content")
                        if isinstance(piece, str):
                            content_parts.append(piece)
                    # Usage
                    usage = item.get("usage")
                    if isinstance(usage, dict):
                        prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
                        completion_tokens = usage.get("completion_tokens", completion_tokens)
                        total_tokens = usage.get("total_tokens", total_tokens)

            duration_ms = (time.perf_counter() - start) * 1000
            response_text = "".join(content_parts)
            if final_chunk:
                response_body_json = json.dumps(final_chunk, ensure_ascii=False)[:2000]
        else:
            resp = await client.post(url, json=payload)
            duration_ms = (time.perf_counter() - start) * 1000
            status_code = resp.status_code
            body = resp.json()
            response_body_json = json.dumps(body, ensure_ascii=False)[:2000]
            usage = body.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
            total_tokens = usage.get("total_tokens")
            # Extract text
            for choice in body.get("choices", []):
                msg = choice.get("message", {})
                if msg.get("content"):
                    response_text = msg["content"]
                    break
            # TTFT = total duration for non-streaming
            ttft_ms = duration_ms

        # Extract load_duration from Ollama-specific fields if present
        if final_chunk and isinstance(final_chunk, dict):
            ld = final_chunk.get("load_duration")
            if ld is not None:
                load_duration_ms = float(ld) / 1_000_000.0 if float(ld) > 1_000_000 else float(ld)

        response_received_at = datetime.now(timezone.utc)
        return RequestResult(
            request_id=entry.request_id,
            original_model=entry.original_model,
            ollama_model=ollama_model,
            http_status=status_code,
            client_duration_ms=duration_ms,
            ttft_ms=ttft_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            response_text=response_text,
            response_body_json=response_body_json,
            error=None if status_code < 400 else (response_body_json or "HTTP error"),
            load_duration_ms=load_duration_ms,
            request_sent_at=request_sent_at,
            response_received_at=response_received_at,
            mode=entry.mode,
            priority=entry.priority,
        )
    except Exception as exc:
        duration_ms = (time.perf_counter() - start) * 1000
        response_received_at = datetime.now(timezone.utc)
        return RequestResult(
            request_id=entry.request_id,
            original_model=entry.original_model,
            ollama_model=ollama_model,
            http_status=0,
            client_duration_ms=duration_ms,
            ttft_ms=None,
            prompt_tokens=None,
            completion_tokens=None,
            total_tokens=None,
            response_text=None,
            response_body_json=None,
            error=str(exc)[:500],
            load_duration_ms=None,
            request_sent_at=request_sent_at,
            response_received_at=response_received_at,
            mode=entry.mode,
            priority=entry.priority,
        )


# ── Workload runner ──────────────────────────────────────────────────────

async def run_workload(
    workload: Sequence[WorkloadEntry],
    base_url: str,
    model_map: dict[str, str],
    request_timeout_s: float,
) -> List[RequestResult]:
    async def report_progress(
        start_monotonic: float,
        completed: dict[str, int],
        stop_event: asyncio.Event,
    ) -> None:
        total = len(workload)
        loop = asyncio.get_event_loop()
        while not stop_event.is_set():
            elapsed_s = loop.time() - start_monotonic
            due = sum(1 for e in workload if (e.arrival_offset / 1000.0) <= elapsed_s)
            print(
                f"[progress] elapsed={elapsed_s:.1f}s due={due}/{total} completed={completed['n']}/{total}",
                flush=True,
            )
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                continue

    async with httpx.AsyncClient(timeout=request_timeout_s) as client:
        start_monotonic = asyncio.get_event_loop().time()
        stop_event = asyncio.Event()
        completed = {"n": 0}
        progress_task = asyncio.create_task(
            report_progress(start_monotonic, completed, stop_event)
        )
        tasks = [
            asyncio.create_task(
                dispatch_request(client, base_url, entry, model_map, start_monotonic)
            )
            for entry in workload
        ]
        results: List[RequestResult] = []
        try:
            for task in asyncio.as_completed(tasks):
                result = await task
                results.append(result)
                completed["n"] += 1
        finally:
            stop_event.set()
            await asyncio.gather(progress_task, return_exceptions=True)
        return results


# ── Result processing ────────────────────────────────────────────────────

def build_results(
    results: List[RequestResult],
    workload: Sequence[WorkloadEntry],
    overhead_ms: float,
    latency_slo_ms: float,
) -> tuple[dict, List[dict]]:
    detail_records: List[dict] = []
    ttft_values: List[float] = []
    tpot_values: List[float] = []
    latency_values: List[float] = []
    successes = 0

    offset_by_id = {e.request_id: e.arrival_offset for e in workload}

    for r in results:
        # Total latency = client_duration + overhead
        total_latency = r.client_duration_ms + overhead_ms
        ttft = (r.ttft_ms + overhead_ms) if r.ttft_ms is not None else None
        tokens = r.completion_tokens
        tpot: Optional[float] = None
        total_tps: Optional[float] = None
        completion_tps: Optional[float] = None

        if ttft is not None and total_latency > 0 and tokens is not None and tokens > 1:
            tpot = (total_latency - ttft) / (tokens - 1)
        if total_latency > 0 and r.total_tokens is not None:
            total_tps = r.total_tokens / (total_latency / 1000.0)
        if ttft is not None and total_latency > ttft and r.completion_tokens is not None:
            completion_tps = r.completion_tokens / ((total_latency - ttft) / 1000.0)

        is_success = r.http_status and r.http_status < 400
        if is_success:
            successes += 1
            if ttft is not None:
                ttft_values.append(ttft)
            if tpot is not None:
                tpot_values.append(tpot)
            latency_values.append(total_latency)

        detail_records.append({
            "log_id": "",
            "request_id": r.request_id,
            "server_request_id": "",
            "mode": r.mode,
            "priority": r.priority,
            "priority_when_scheduled": "",
            "http_status": r.http_status,
            "client_duration_ms": r.client_duration_ms,
            "request_body_json": "",
            "provider_name": "ollama-direct",
            "model_name": r.original_model,
            "cold_start": "",
            "load_duration_ms": r.load_duration_ms,
            "result_status": "success" if is_success else "error",
            "prompt_tokens": r.prompt_tokens,
            "completion_tokens": r.completion_tokens,
            "total_tokens": r.total_tokens,
            "total_tokens_per_second": total_tps,
            "completion_tokens_per_second": completion_tps,
            "ttft_ms": ttft,
            "tpot_ms": tpot,
            "tokens": tokens,
            "total_latency_ms": total_latency,
            "queue_depth_at_arrival": "",
            "utilization_at_arrival": "",
            "queue_depth_at_schedule": "",
            "queue_wait_ms": overhead_ms,  # the 0.5s overhead stands in for queue wait
            "processing_ms": r.client_duration_ms,
            "scheduler_total_ms": total_latency,
            "available_vram_mb": "",
            "azure_rate_remaining_requests": "",
            "azure_rate_remaining_tokens": "",
            "response_body_json": r.response_body_json or "",
            "response_text": r.response_text or "",
            "error": r.error or "",
            "request_sent_at": r.request_sent_at.isoformat().replace("+00:00", "Z") if r.request_sent_at else "",
            "response_received_at": r.response_received_at.isoformat().replace("+00:00", "Z") if r.response_received_at else "",
            "arrival_offset_ms": offset_by_id.get(r.request_id, ""),
        })

    total = len(results)
    errors = total - successes
    error_rate = (errors / total * 100) if total else math.nan
    slo_hits = sum(1 for v in latency_values if v <= latency_slo_ms)
    slo_rate = (slo_hits / len(latency_values) * 100) if latency_values else math.nan

    summary = {
        "total_requests": total,
        "successful_requests": successes,
        "failed_requests": errors,
        "error_rate": error_rate,
        "slo_attainment_rate": slo_rate,
        "avg_ttft_ms": sum(ttft_values) / len(ttft_values) if ttft_values else math.nan,
        "p50_ttft_ms": calculate_percentile(ttft_values, 50),
        "p95_ttft_ms": calculate_percentile(ttft_values, 95),
        "p99_ttft_ms": calculate_percentile(ttft_values, 99),
        "avg_tpot_ms": sum(tpot_values) / len(tpot_values) if tpot_values else math.nan,
        "p50_tpot_ms": calculate_percentile(tpot_values, 50),
        "p95_tpot_ms": calculate_percentile(tpot_values, 95),
        "p99_tpot_ms": calculate_percentile(tpot_values, 99),
        "avg_latency_ms": sum(latency_values) / len(latency_values) if latency_values else math.nan,
        "p50_latency_ms": calculate_percentile(latency_values, 50),
        "p95_latency_ms": calculate_percentile(latency_values, 95),
        "p99_latency_ms": calculate_percentile(latency_values, 99),
        "avg_queue_wait_ms": overhead_ms,
        "p50_queue_wait_ms": overhead_ms,
        "p95_queue_wait_ms": overhead_ms,
        "p99_queue_wait_ms": overhead_ms,
        "avg_processing_ms": sum(r.client_duration_ms for r in results) / total if total else math.nan,
        "p50_processing_ms": calculate_percentile([r.client_duration_ms for r in results], 50),
        "p95_processing_ms": calculate_percentile([r.client_duration_ms for r in results], 95),
        "p99_processing_ms": calculate_percentile([r.client_duration_ms for r in results], 99),
        "avg_scheduler_total_ms": sum(latency_values) / len(latency_values) if latency_values else math.nan,
        "p50_scheduler_total_ms": calculate_percentile(latency_values, 50),
        "p95_scheduler_total_ms": calculate_percentile(latency_values, 95),
        "p99_scheduler_total_ms": calculate_percentile(latency_values, 99),
    }
    return summary, detail_records


# ── Writers (match run_api_workload.py format exactly) ───────────────────

def write_summary_csv(path: Path, stats: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    def fmt(v):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return "N/A"
        if isinstance(v, float):
            return f"{v:.2f}"
        return str(v)

    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["metric", "value", "unit"])
        w.writerow(["total_requests", stats["total_requests"], "count"])
        w.writerow(["successful_requests", stats["successful_requests"], "count"])
        w.writerow(["failed_requests", stats["failed_requests"], "count"])
        w.writerow(["error_rate", fmt(stats["error_rate"]), "%"])
        w.writerow(["slo_attainment_rate", fmt(stats["slo_attainment_rate"]), "%"])
        for metric in ("ttft", "tpot"):
            unit = "ms" if metric == "ttft" else "ms/token"
            for agg in ("avg", "p50", "p95", "p99"):
                w.writerow([f"{agg}_{metric}", fmt(stats[f"{agg}_{metric}_ms"]), unit])
        for metric, key in (("total_latency", "latency"), ("queue_wait", "queue_wait"), ("processing", "processing"), ("scheduler_total", "scheduler_total")):
            for agg in ("avg", "p50", "p95", "p99"):
                w.writerow([f"{agg}_{metric}", fmt(stats[f"{agg}_{key}_ms"]), "ms"])


def write_detailed_csv(path: Path, records: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "log_id", "request_id", "server_request_id", "mode", "priority",
        "priority_when_scheduled", "http_status", "client_duration_ms",
        "request_body_json", "provider_name", "model_name", "cold_start",
        "load_duration_ms", "result_status", "prompt_tokens", "completion_tokens",
        "total_tokens", "total_tokens_per_second", "completion_tokens_per_second",
        "ttft_ms", "tpot_ms", "tokens", "total_latency_ms",
        "queue_depth_at_arrival", "utilization_at_arrival", "queue_depth_at_schedule",
        "queue_wait_ms", "processing_ms", "scheduler_total_ms", "available_vram_mb",
        "azure_rate_remaining_requests", "azure_rate_remaining_tokens",
        "response_body_json", "response_text", "error",
        "request_sent_at", "response_received_at", "arrival_offset_ms",
    ]
    def fmt(v):
        if v is None or v == "" or (isinstance(v, float) and math.isnan(v)):
            return ""
        if isinstance(v, float):
            return f"{v:.2f}"
        return str(v)

    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        for rec in records:
            w.writerow([fmt(rec.get(h, "")) for h in headers])


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Chart generation (matches plot_benchmark_distributions.py style) ─────

COLOR_FILL = "#C8A415"
COLOR_EDGE = "#2255A0"
COLOR_P50 = "#1a7a1a"
COLOR_MEAN = "#cc6600"
COLOR_P95 = "#cc2222"
COLOR_P99 = "#8822aa"
COLOR_GRID = "#cccccc"
BG_COLOR = "#f5f5f5"


def gaussian_kde(data: list[float], x_grid: np.ndarray, bandwidth: Optional[float] = None) -> np.ndarray:
    n = len(data)
    if n == 0:
        return np.zeros_like(x_grid)
    std = float(np.std(data))
    if std == 0:
        std = 1.0
    if bandwidth is None:
        bandwidth = 1.06 * std * n ** (-1.0 / 5.0)
    result = np.zeros_like(x_grid, dtype=float)
    for xi in data:
        result += np.exp(-0.5 * ((x_grid - xi) / bandwidth) ** 2)
    result /= (n * bandwidth * math.sqrt(2 * math.pi))
    return result


def plot_distribution(
    values: list[float],
    title: str,
    xlabel: str,
    out_path: Path,
) -> None:
    if not values:
        return
    s = sorted(values)
    mean_v = sum(s) / len(s)
    p50 = calculate_percentile(s, 50)
    p95 = calculate_percentile(s, 95)
    p99 = calculate_percentile(s, 99)

    fig, ax = plt.subplots(figsize=(12, 6))
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)

    n_bins = min(80, max(20, len(s) // 3))
    counts, bin_edges, patches = ax.hist(
        s, bins=n_bins, density=True, alpha=0.7,
        color=COLOR_FILL, edgecolor=COLOR_EDGE, linewidth=0.5,
    )

    x_grid = np.linspace(min(s) - 0.1 * (max(s) - min(s) + 1), max(s) + 0.1 * (max(s) - min(s) + 1), 300)
    kde = gaussian_kde(s, x_grid)
    ax.plot(x_grid, kde, color=COLOR_EDGE, linewidth=2)

    for val, color, label in [
        (p50, COLOR_P50, f"Median: {p50:.0f}"),
        (mean_v, COLOR_MEAN, f"Mean: {mean_v:.0f}"),
        (p95, COLOR_P95, f"P95: {p95:.0f}"),
        (p99, COLOR_P99, f"P99: {p99:.0f}"),
    ]:
        ax.axvline(val, color=color, linestyle="--", linewidth=1.5, label=label)

    ax.set_xlabel(xlabel)
    ax.set_ylabel("Density")
    ax.set_title(title)
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.3, color=COLOR_GRID)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_timeline(
    records: List[dict],
    out_path: Path,
) -> None:
    successful = [r for r in records if r.get("result_status") == "success"]
    if not successful:
        return

    # Sort by request_id to get chronological order
    model_colors = {}
    color_cycle = ["#4C72B0", "#55A868", "#C44E52", "#8172B2", "#CCB974"]
    for r in successful:
        m = r.get("model_name", "")
        if m not in model_colors:
            model_colors[m] = color_cycle[len(model_colors) % len(color_cycle)]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    fig.patch.set_facecolor(BG_COLOR)
    for ax in (ax1, ax2):
        ax.set_facecolor(BG_COLOR)

    for i, r in enumerate(successful):
        color = model_colors.get(r.get("model_name", ""), "#999999")
        ttft = r.get("ttft_ms")
        latency = r.get("total_latency_ms")
        if isinstance(ttft, (int, float)):
            ax1.scatter(i, ttft, c=color, s=15, alpha=0.7)
        if isinstance(latency, (int, float)):
            ax2.scatter(i, latency, c=color, s=15, alpha=0.7)

    ax1.set_ylabel("TTFT (ms)")
    ax1.set_title("TTFT over Request Order")
    ax1.grid(True, alpha=0.3)
    ax2.set_ylabel("Total Latency (ms)")
    ax2.set_title("Total Latency over Request Order")
    ax2.set_xlabel("Request index")
    ax2.grid(True, alpha=0.3)

    # Legend
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor=c, markersize=8, label=m)
        for m, c in model_colors.items()
    ]
    ax1.legend(handles=legend_elements, loc="upper right", fontsize=8)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def generate_all_charts(out_dir: Path, records: List[dict]) -> None:
    successful = [r for r in records if r.get("result_status") == "success"]

    ttft_vals = [r["ttft_ms"] for r in successful if isinstance(r.get("ttft_ms"), (int, float))]
    latency_vals = [r["total_latency_ms"] for r in successful if isinstance(r.get("total_latency_ms"), (int, float))]
    qwait_vals = [r["queue_wait_ms"] for r in successful if isinstance(r.get("queue_wait_ms"), (int, float))]

    plot_distribution(ttft_vals, "TTFT Distribution (Ollama)", "TTFT (ms)", out_dir / "chart_ttft_distribution.png")
    plot_distribution(latency_vals, "Total Latency Distribution (Ollama)", "Total Latency (ms)", out_dir / "chart_total_latency_distribution.png")
    plot_distribution(qwait_vals, "Queue Wait Distribution (Ollama)", "Queue Wait (ms)", out_dir / "chart_queue_wait_distribution.png")
    plot_timeline(records, out_dir / "chart_timeline.png")


# ── Main ─────────────────────────────────────────────────────────────────

async def async_main(args: argparse.Namespace) -> None:
    workload = parse_workload(args.workload)
    print(f"Loaded workload: {len(workload)} requests from {args.workload}")

    # Collect unique Ollama models needed
    ollama_models = set()
    for entry in workload:
        body = json.loads(entry.body_json)
        vllm_model = body.get("model", "")
        ollama_model = MODEL_MAP.get(vllm_model, vllm_model)
        ollama_models.add(ollama_model)

    print(f"Required Ollama models: {ollama_models}")

    # Step 1: Ensure models are downloaded
    await ensure_models_pulled(args.ollama_base, list(ollama_models))

    # Step 2: Cold start — unload everything
    print("\n--- Cold start: unloading all models ---")
    await unload_all_models(args.ollama_base)

    # Step 3: Run workload
    print(f"\n--- Running workload ({len(workload)} requests) ---")
    run_started = datetime.now(timezone.utc)
    results = await run_workload(workload, args.ollama_base, MODEL_MAP, args.request_timeout_s)
    run_finished = datetime.now(timezone.utc)

    # Step 4: Build results with overhead
    summary, detail_records = build_results(results, workload, args.overhead_ms, args.latency_slo_ms)

    # Step 5: Write outputs
    out_dir = Path(args.output_dir)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    run_dir = out_dir / f"{timestamp} - {args.workload.stem}"
    run_dir.mkdir(parents=True, exist_ok=True)

    summary_path = run_dir / "results_summary.csv"
    detailed_path = run_dir / "results_detailed.csv"

    write_summary_csv(summary_path, summary)
    write_detailed_csv(detailed_path, detail_records)
    generate_all_charts(run_dir, detail_records)
    write_json(run_dir / "run_meta.json", {
        "workload": str(args.workload),
        "ollama_base": args.ollama_base,
        "overhead_ms": args.overhead_ms,
        "request_timeout_s": args.request_timeout_s,
        "request_count": len(results),
        "model_map": MODEL_MAP,
        "run_started_at": run_started.isoformat().replace("+00:00", "Z"),
        "run_finished_at": run_finished.isoformat().replace("+00:00", "Z"),
        "engine": "ollama",
    })

    print(f"\n=== Benchmark complete ===")
    print(f"  Results: {run_dir}")
    print(f"  Summary: {summary_path}")
    print(f"  Detailed: {detailed_path}")
    print(f"  Requests: {summary['total_requests']} total, {summary['successful_requests']} ok, {summary['failed_requests']} failed")
    if not math.isnan(summary["avg_latency_ms"]):
        print(f"  Avg latency: {summary['avg_latency_ms']:.0f} ms (incl. {args.overhead_ms:.0f} ms overhead)")
        print(f"  P50 latency: {summary['p50_latency_ms']:.0f} ms")
        print(f"  P95 latency: {summary['p95_latency_ms']:.0f} ms")
    if not math.isnan(summary["avg_ttft_ms"]):
        print(f"  Avg TTFT:    {summary['avg_ttft_ms']:.0f} ms")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Ollama with the same workloads as Logos/vLLM.")
    parser.add_argument("--workload", type=Path, required=True, help="Path to workload CSV (same format as run_api_workload.py).")
    parser.add_argument("--ollama-base", default="http://localhost:11434", help="Ollama API base URL.")
    parser.add_argument("--output-dir", type=Path, default=Path("tests/performance/results_ollama"), help="Output directory.")
    parser.add_argument("--overhead-ms", type=float, default=DEFAULT_OVERHEAD_MS, help="Overhead in ms added to each latency (default 500).")
    parser.add_argument("--latency-slo-ms", type=float, default=10_000.0, help="Latency SLO threshold in ms.")
    parser.add_argument("--request-timeout-s", type=float, default=1200.0, help="Per-request timeout in seconds.")
    args = parser.parse_args()
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
