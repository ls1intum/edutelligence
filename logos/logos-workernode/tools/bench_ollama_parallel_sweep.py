#!/usr/bin/env python3
"""
Ollama parallel sweep benchmark (fixed context length).

Runs the same workload across requested Ollama `num_parallel` targets
(for example 8,16,32) at a fixed context length. If a target cannot fit
in memory, it automatically finds the highest feasible value <= target
and continues.

Outputs:
  - timestamped JSON summary
  - timestamped CSV rows
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from bench_lane_backends import (
    DEFAULT_PROMPT,
    apply_single_lane,
    clear_lanes,
    parse_concurrency,
    resolve_openai_model,
    run_batch,
    wait_backend_ready,
    wait_for_lane_status,
    warmup,
)


def parse_int_list(raw: str, name: str) -> list[int]:
    values = [int(v.strip()) for v in raw.split(",") if v.strip()]
    if not values:
        raise ValueError(f"{name} is empty")
    if any(v < 1 for v in values):
        raise ValueError(f"{name} values must be >= 1")
    return values


def build_ollama_lane(
    model: str,
    num_parallel: int,
    context_length: int,
    gpu_devices: str,
    keep_alive: str,
    kv_cache_type: str,
    flash_attention: bool,
) -> dict[str, Any]:
    return {
        "model": model,
        "backend": "ollama",
        "num_parallel": num_parallel,
        "context_length": context_length,
        "keep_alive": keep_alive,
        "kv_cache_type": kv_cache_type,
        "flash_attention": flash_attention,
        "gpu_devices": gpu_devices,
    }


async def sample_gpu_memory() -> list[dict[str, int]]:
    proc = await asyncio.create_subprocess_exec(
        "nvidia-smi",
        "--query-gpu=index,memory.used,memory.total",
        "--format=csv,noheader,nounits",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _err = await proc.communicate()
    if proc.returncode != 0:
        return []

    rows: list[dict[str, int]] = []
    for raw_line in out.decode().strip().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            rows.append({
                "index": int(parts[0]),
                "used_mb": int(parts[1]),
                "total_mb": int(parts[2]),
            })
        except ValueError:
            continue
    rows.sort(key=lambda r: r["index"])
    return rows


def merge_peak(
    current: dict[int, dict[str, int]],
    sample: list[dict[str, int]],
) -> dict[int, dict[str, int]]:
    for row in sample:
        idx = int(row["index"])
        used = int(row["used_mb"])
        total = int(row["total_mb"])
        existing = current.get(idx)
        if existing is None:
            current[idx] = {"index": idx, "used_mb": used, "total_mb": total}
        elif used > int(existing["used_mb"]):
            existing["used_mb"] = used
            existing["total_mb"] = total
    return current


def normalize_peak(peak: dict[int, dict[str, int]]) -> list[dict[str, int]]:
    return [peak[idx] for idx in sorted(peak)]


class GpuPeakMonitor:
    def __init__(self, interval_s: float = 0.5) -> None:
        self.interval_s = interval_s
        self._task: asyncio.Task | None = None
        self._peak: dict[int, dict[str, int]] = {}
        self._stop = asyncio.Event()

    async def _loop(self) -> None:
        while not self._stop.is_set():
            sample = await sample_gpu_memory()
            merge_peak(self._peak, sample)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_s)
            except asyncio.TimeoutError:
                pass

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="gpu-peak-monitor")

    async def stop(self) -> list[dict[str, int]]:
        self._stop.set()
        if self._task is not None:
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        return normalize_peak(self._peak)


async def probe_num_parallel(
    controller_client: httpx.AsyncClient,
    api_key: str,
    lane_cfg: dict[str, Any],
    max_tokens: int,
) -> tuple[bool, dict[str, Any]]:
    model = str(lane_cfg["model"])
    np = int(lane_cfg["num_parallel"])
    try:
        await apply_single_lane(controller_client, api_key, lane_cfg)
        lane = await wait_for_lane_status(
            controller_client,
            api_key,
            model=model,
            backend="ollama",
            timeout_s=420,
        )
        port = int(lane["port"])
        base_url = f"http://127.0.0.1:{port}"
        await wait_backend_ready(base_url, "ollama", timeout_s=180)
        served_model = await resolve_openai_model(base_url, preferred=model)
        await warmup(
            base_url=base_url,
            model=served_model,
            warmup_count=1,
            max_tokens=max_tokens,
        )
        gpu_mem = await sample_gpu_memory()
        return True, {
            "num_parallel": np,
            "lane_port": port,
            "served_model": served_model,
            "gpu_memory_after_warmup": gpu_mem,
        }
    except Exception as exc:  # noqa: BLE001
        return False, {
            "num_parallel": np,
            "error": str(exc),
        }


async def find_highest_feasible_num_parallel(
    controller_client: httpx.AsyncClient,
    api_key: str,
    lane_base: dict[str, Any],
    target_num_parallel: int,
    max_tokens: int,
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []

    async def try_np(np: int) -> tuple[bool, dict[str, Any]]:
        lane_cfg = {**lane_base, "num_parallel": np}
        ok, info = await probe_num_parallel(
            controller_client=controller_client,
            api_key=api_key,
            lane_cfg=lane_cfg,
            max_tokens=max_tokens,
        )
        attempt = {
            "num_parallel": np,
            "ok": ok,
            "details": info,
        }
        attempts.append(attempt)
        return ok, info

    await clear_lanes(controller_client, api_key)
    ok, info = await try_np(target_num_parallel)
    if ok:
        return {
            "target_num_parallel": target_num_parallel,
            "effective_num_parallel": target_num_parallel,
            "saturated": False,
            "saturation_reason": "",
            "attempts": attempts,
            "probe_info": info,
        }

    saturation_reason = str(info.get("error", "unknown error"))
    low = 1
    high = target_num_parallel - 1
    best_ok: dict[str, Any] | None = None
    best_np = 0

    while low <= high:
        mid = (low + high) // 2
        await clear_lanes(controller_client, api_key)
        mid_ok, mid_info = await try_np(mid)
        if mid_ok:
            best_np = mid
            best_ok = mid_info
            low = mid + 1
        else:
            high = mid - 1

    if best_np <= 0 or best_ok is None:
        raise RuntimeError(
            f"No feasible num_parallel found at context_length={lane_base['context_length']} "
            f"for target={target_num_parallel}. Last error: {saturation_reason}"
        )

    return {
        "target_num_parallel": target_num_parallel,
        "effective_num_parallel": best_np,
        "saturated": best_np != target_num_parallel,
        "saturation_reason": saturation_reason,
        "attempts": attempts,
        "probe_info": best_ok,
    }


async def benchmark_effective_num_parallel(
    controller_client: httpx.AsyncClient,
    api_key: str,
    lane_base: dict[str, Any],
    effective_num_parallel: int,
    concurrency_levels: list[int],
    prompt: str,
    max_tokens: int,
    warmup_count: int,
) -> dict[str, Any]:
    lane_cfg = {**lane_base, "num_parallel": effective_num_parallel}

    await clear_lanes(controller_client, api_key)
    await apply_single_lane(controller_client, api_key, lane_cfg)
    lane = await wait_for_lane_status(
        controller_client,
        api_key,
        model=str(lane_cfg["model"]),
        backend="ollama",
        timeout_s=420,
    )

    port = int(lane["port"])
    base_url = f"http://127.0.0.1:{port}"
    await wait_backend_ready(base_url, "ollama", timeout_s=180)
    served_model = await resolve_openai_model(base_url, preferred=str(lane_cfg["model"]))

    monitor = GpuPeakMonitor(interval_s=0.5)
    await monitor.start()

    startup_gpu = await sample_gpu_memory()
    await warmup(
        base_url=base_url,
        model=served_model,
        warmup_count=warmup_count,
        max_tokens=max_tokens,
    )

    rows: list[dict[str, Any]] = []
    for concurrency in concurrency_levels:
        result = await run_batch(
            base_url=base_url,
            model=served_model,
            prompt=prompt,
            max_tokens=max_tokens,
            concurrency=concurrency,
        )
        rows.append(result)

    peak_gpu = await monitor.stop()

    return {
        "configured_model": lane_cfg["model"],
        "served_model": served_model,
        "lane_port": port,
        "num_parallel": effective_num_parallel,
        "context_length": lane_cfg["context_length"],
        "gpu_memory_start_mb": startup_gpu,
        "gpu_memory_peak_mb": peak_gpu,
        "results": rows,
    }


def write_csv(out_path: Path, sweep_rows: list[dict[str, Any]]) -> None:
    fields = [
        "timestamp_utc",
        "target_num_parallel",
        "effective_num_parallel",
        "saturated",
        "concurrency",
        "requests_ok",
        "errors",
        "total_tokens",
        "batch_time_s",
        "aggregate_tok_s",
        "avg_latency_s",
        "p50_latency_s",
        "p95_latency_s",
        "avg_ttft_ms",
        "avg_tok_per_req_s",
    ]
    now = datetime.now(timezone.utc).isoformat()
    with out_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for item in sweep_rows:
            target = int(item["target_num_parallel"])
            effective = int(item["effective_num_parallel"])
            sat = bool(item["saturated"])
            bench = item["benchmark"]
            for row in bench["results"]:
                writer.writerow({
                    "timestamp_utc": now,
                    "target_num_parallel": target,
                    "effective_num_parallel": effective,
                    "saturated": sat,
                    "concurrency": row.get("concurrency"),
                    "requests_ok": row.get("requests_ok"),
                    "errors": row.get("errors"),
                    "total_tokens": row.get("total_tokens"),
                    "batch_time_s": row.get("batch_time_s"),
                    "aggregate_tok_s": row.get("aggregate_tok_s"),
                    "avg_latency_s": row.get("avg_latency_s"),
                    "p50_latency_s": row.get("p50_latency_s"),
                    "p95_latency_s": row.get("p95_latency_s"),
                    "avg_ttft_ms": row.get("avg_ttft_ms"),
                    "avg_tok_per_req_s": row.get("avg_tok_per_req_s"),
                })


def print_summary(sweep_rows: list[dict[str, Any]]) -> None:
    print("\nOllama Parallel Sweep Summary (fixed context_length)")
    for item in sweep_rows:
        target = int(item["target_num_parallel"])
        effective = int(item["effective_num_parallel"])
        sat = bool(item["saturated"])
        bench = item["benchmark"]
        sat_note = "SATURATED" if sat else "ok"
        print(
            f"\n[target={target} -> effective={effective}] "
            f"context={bench['context_length']} ({sat_note})"
        )
        if sat and item.get("saturation_reason"):
            print(f"  saturation_reason: {item['saturation_reason']}")
        print(
            f"{'N':>4} {'Agg tok/s':>10} {'Avg lat':>10} {'P95 lat':>10} "
            f"{'TTFT ms':>10} {'Errors':>8}"
        )
        print("-" * 62)
        for row in bench["results"]:
            if "error_msgs" in row:
                print(f"{row['concurrency']:>4} {'FAILED':>10} {'-':>10} {'-':>10} {'-':>10} {row['errors']:>8}")
            else:
                print(
                    f"{row['concurrency']:>4} "
                    f"{row['aggregate_tok_s']:>10.3f} "
                    f"{row['avg_latency_s']:>10.3f} "
                    f"{row['p95_latency_s']:>10.3f} "
                    f"{row['avg_ttft_ms']:>10.1f} "
                    f"{row['errors']:>8}"
                )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ollama num_parallel sweep with memory saturation fallback.")
    parser.add_argument("--controller-url", default="http://127.0.0.1:8444")
    parser.add_argument("--api-key", default=os.environ.get("API_KEY", "RANDOM_DEFAULT_KEY"))
    parser.add_argument("--output-dir", default="bench_results")

    parser.add_argument("--ollama-model", default="qwen2.5-coder:32b")
    parser.add_argument("--context-length", type=int, default=4096)
    parser.add_argument("--target-num-parallel", default="8,16,32")
    parser.add_argument("--concurrency", default="1,4,8,16,32")
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=200)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)

    parser.add_argument("--ollama-gpu-devices", default="0,1")
    parser.add_argument("--ollama-keep-alive", default="10m")
    parser.add_argument("--ollama-kv-cache-type", default="q8_0")
    parser.add_argument("--ollama-flash-attention", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


async def main_async(args: argparse.Namespace) -> int:
    target_num_parallel = parse_int_list(args.target_num_parallel, "target_num_parallel")
    concurrency_levels = parse_concurrency(args.concurrency)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"ollama_parallel_sweep_{stamp}.json"
    csv_path = output_dir / f"ollama_parallel_sweep_{stamp}.csv"

    lane_base = build_ollama_lane(
        model=args.ollama_model,
        num_parallel=1,
        context_length=args.context_length,
        gpu_devices=args.ollama_gpu_devices,
        keep_alive=args.ollama_keep_alive,
        kv_cache_type=args.ollama_kv_cache_type,
        flash_attention=args.ollama_flash_attention,
    )

    timeout = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)
    sweep_rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(base_url=args.controller_url.rstrip("/"), timeout=timeout) as controller_client:
        try:
            for target in target_num_parallel:
                print(f"Resolving feasible num_parallel for target={target} (context={args.context_length})...")
                fit = await find_highest_feasible_num_parallel(
                    controller_client=controller_client,
                    api_key=args.api_key,
                    lane_base=lane_base,
                    target_num_parallel=target,
                    max_tokens=args.max_tokens,
                )
                effective = int(fit["effective_num_parallel"])
                if bool(fit["saturated"]):
                    print(f"  Saturated at target={target}; using effective={effective}")
                else:
                    print(f"  Feasible at target={target}")

                print(f"Benchmarking target={target} with effective num_parallel={effective}...")
                bench = await benchmark_effective_num_parallel(
                    controller_client=controller_client,
                    api_key=args.api_key,
                    lane_base=lane_base,
                    effective_num_parallel=effective,
                    concurrency_levels=concurrency_levels,
                    prompt=args.prompt,
                    max_tokens=args.max_tokens,
                    warmup_count=args.warmup,
                )
                sweep_rows.append({
                    **fit,
                    "benchmark": bench,
                })
        finally:
            try:
                await clear_lanes(controller_client, args.api_key)
            except Exception as exc:  # noqa: BLE001
                print(f"Warning: failed to clear lanes: {exc}")

    payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "controller_url": args.controller_url,
        "model": args.ollama_model,
        "context_length": args.context_length,
        "target_num_parallel": target_num_parallel,
        "concurrency": concurrency_levels,
        "max_tokens": args.max_tokens,
        "warmup": args.warmup,
        "sweep": sweep_rows,
    }

    json_path.write_text(json.dumps(payload, indent=2))
    write_csv(csv_path, sweep_rows)
    print_summary(sweep_rows)
    print(f"\nSaved JSON: {json_path}")
    print(f"Saved CSV:  {csv_path}")
    return 0


def main() -> int:
    args = parse_args()
    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("Interrupted")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
