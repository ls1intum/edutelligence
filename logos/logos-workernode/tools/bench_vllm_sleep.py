#!/usr/bin/env python3
"""
Benchmark vLLM sleep levels and wake-up latency.

This script:
1) starts vLLM servers for configured models,
2) measures VRAM before sleep, during sleep, and after wake-up,
3) measures time from wake-up until the first successful response,
4) writes CSV + JSON artifacts to bench_results/.

Important:
- Sleep APIs require:
  - vLLM started with ``--enable-sleep-mode``
  - env ``VLLM_SERVER_DEV_MODE=1`` (exposes /sleep, /wake_up, /is_sleeping)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_MODEL_PLANS: list[dict[str, Any]] = [
    {
        "name": "Qwen/Qwen2.5-32B-Instruct-AWQ",
        "gpu_devices": "0,1",
        "tensor_parallel_size": 2,
        "dtype": "float16",
        "quantization": "awq",
        "gpu_memory_utilization": 0.90,
        "max_model_len": 4096,
        "enforce_eager": True,
        "enable_prefix_caching": False,
    },
    {
        "name": "Qwen/Qwen2.5-Coder-32B-Instruct-AWQ",
        "gpu_devices": "0,1",
        "tensor_parallel_size": 2,
        "dtype": "float16",
        "quantization": "awq",
        "gpu_memory_utilization": 0.90,
        "max_model_len": 4096,
        "enforce_eager": True,
        "enable_prefix_caching": False,
    },
    {
        # Matches the latest lane runs from 2026-03-10 in this repository.
        "name": "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        "gpu_devices": "0,1",
        "tensor_parallel_size": 2,
        "dtype": "float16",
        "quantization": "",
        "gpu_memory_utilization": 0.70,
        "max_model_len": 4096,
        "enforce_eager": True,
        "enable_prefix_caching": False,
    },
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(value: str) -> str:
    return (
        value.lower()
        .replace("/", "__")
        .replace(":", "_")
        .replace(" ", "_")
        .replace(".", "_")
    )


def model_cache_dir(model_name: str) -> Path:
    # HuggingFace cache naming convention used by vLLM.
    return Path.home() / ".cache" / "huggingface" / "hub" / f"models--{model_name.replace('/', '--')}"


def run_command(cmd: list[str], timeout_s: float = 10.0) -> str:
    out = subprocess.run(
        cmd,
        check=True,
        text=True,
        capture_output=True,
        timeout=timeout_s,
    )
    return out.stdout.strip()


def query_gpu_snapshot() -> dict[str, Any]:
    """
    Returns:
      {
        "timestamp_utc": ...,
        "total_used_mb": float,
        "gpus": [{"index": int, "name": str, "total_mb": float, "used_mb": float}, ...]
      }
    """
    raw = run_command(
        [
            "nvidia-smi",
            "--query-gpu=index,name,memory.total,memory.used",
            "--format=csv,noheader,nounits",
        ],
        timeout_s=10.0,
    )
    gpus: list[dict[str, Any]] = []
    total_used = 0.0
    for line in raw.splitlines():
        # Expected format: index, name, total, used
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        idx = int(parts[0])
        name = parts[1]
        total_mb = float(parts[2])
        used_mb = float(parts[3])
        gpus.append(
            {
                "index": idx,
                "name": name,
                "total_mb": total_mb,
                "used_mb": used_mb,
            }
        )
        total_used += used_mb
    return {
        "timestamp_utc": utc_now(),
        "total_used_mb": total_used,
        "gpus": gpus,
    }


def summarize_samples(samples: list[dict[str, Any]]) -> dict[str, float]:
    totals = [float(s["total_used_mb"]) for s in samples]
    if not totals:
        return {"min_total_mb": 0.0, "avg_total_mb": 0.0, "max_total_mb": 0.0}
    return {
        "min_total_mb": min(totals),
        "avg_total_mb": sum(totals) / len(totals),
        "max_total_mb": max(totals),
    }


def collect_samples(duration_s: float, interval_s: float) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    deadline = time.perf_counter() + duration_s
    while True:
        samples.append(query_gpu_snapshot())
        now = time.perf_counter()
        if now >= deadline:
            break
        sleep_for = min(interval_s, max(0.0, deadline - now))
        if sleep_for > 0:
            time.sleep(sleep_for)
    return samples


def http_request_json(
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
    timeout_s: float = 30.0,
) -> tuple[int, Any, float]:
    payload = None
    headers: dict[str, str] = {}
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url=url, data=payload, headers=headers, method=method)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            text = raw.decode("utf-8", errors="replace")
            if not text:
                parsed: Any = {}
            else:
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    parsed = text
            return resp.status, parsed, elapsed_ms
    except urllib.error.HTTPError as e:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} for {url}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Request failed for {url}: {e}") from e


def wait_until_ready(
    base_url: str,
    timeout_s: float,
    process: subprocess.Popen[str] | None = None,
    log_path: Path | None = None,
) -> float:
    start = time.perf_counter()
    deadline = start + timeout_s
    last_error: str | None = None
    while time.perf_counter() < deadline:
        if process is not None and process.poll() is not None:
            exit_code = process.poll()
            log_hint = f" See log: {log_path}" if log_path is not None else ""
            raise RuntimeError(
                f"vLLM process exited before readiness check (exit_code={exit_code}).{log_hint}"
            )
        try:
            status_health, _, _ = http_request_json("GET", f"{base_url}/health", timeout_s=5.0)
            status_models, models, _ = http_request_json("GET", f"{base_url}/v1/models", timeout_s=10.0)
            if status_health == 200 and status_models == 200 and isinstance(models, dict):
                return (time.perf_counter() - start) * 1000.0
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        time.sleep(1.0)
    raise TimeoutError(f"vLLM did not become ready in {timeout_s}s. Last error: {last_error}")


def wait_sleep_state(base_url: str, target: bool, timeout_s: float) -> float:
    start = time.perf_counter()
    deadline = start + timeout_s
    last_state: Any = None
    while time.perf_counter() < deadline:
        status, payload, _ = http_request_json("GET", f"{base_url}/is_sleeping", timeout_s=5.0)
        if status == 200 and isinstance(payload, dict):
            last_state = payload.get("is_sleeping")
            if bool(last_state) is target:
                return (time.perf_counter() - start) * 1000.0
        time.sleep(0.5)
    raise TimeoutError(
        f"/is_sleeping did not reach target={target} in {timeout_s}s (last={last_state})"
    )


def make_probe_payload(model: str, max_tokens: int) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "Reply with exactly: READY"},
        ],
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "stream": False,
    }


def wait_for_first_response_after_wake(
    base_url: str,
    model: str,
    per_request_timeout_s: float,
    overall_timeout_s: float,
    max_tokens: int,
) -> tuple[float, float, int]:
    """
    Returns:
      (wake_to_first_success_ms, successful_request_latency_ms, probe_attempts)
    """
    start = time.perf_counter()
    deadline = start + overall_timeout_s
    attempts = 0
    last_error: str | None = None
    while time.perf_counter() < deadline:
        attempts += 1
        try:
            status, _, req_ms = http_request_json(
                "POST",
                f"{base_url}/v1/chat/completions",
                body=make_probe_payload(model, max_tokens),
                timeout_s=per_request_timeout_s,
            )
            if status == 200:
                total_ms = (time.perf_counter() - start) * 1000.0
                return total_ms, req_ms, attempts
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        time.sleep(0.5)
    raise TimeoutError(
        f"No successful post-wake response within {overall_timeout_s}s "
        f"(attempts={attempts}, last_error={last_error})"
    )


@dataclass
class SleepRunSummary:
    timestamp_utc: str
    model: str
    sleep_level: int
    repeat: int
    ready_ms: float
    warmup_ms: float
    sleep_call_ms: float
    sleep_to_state_ms: float
    wake_call_ms: float
    wake_to_not_sleeping_ms: float
    wake_to_first_response_ms: float
    first_response_latency_ms: float
    probe_attempts: int
    vram_before_sleep_total_mb: float
    vram_sleep_min_total_mb: float
    vram_sleep_avg_total_mb: float
    vram_sleep_max_total_mb: float
    vram_after_sleep_total_mb: float
    vram_after_wake_total_mb: float
    vram_after_first_response_total_mb: float


def parse_sleep_levels(raw: str) -> list[int]:
    vals: list[int] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        level = int(token)
        if level not in (1, 2):
            raise ValueError(f"Unsupported sleep level {level}. Use 1 and/or 2.")
        vals.append(level)
    if not vals:
        raise ValueError("At least one sleep level must be provided.")
    return vals


def load_plans(plan_file: str | None, model_filter: set[str] | None) -> list[dict[str, Any]]:
    plans = DEFAULT_MODEL_PLANS
    if plan_file:
        with Path(plan_file).open("r", encoding="utf-8") as f:
            loaded = json.load(f)
        if not isinstance(loaded, list):
            raise ValueError("Plan file must be a JSON list of model plan objects.")
        plans = loaded
    if model_filter:
        plans = [p for p in plans if p.get("name") in model_filter]
    return plans


def start_vllm(
    plan: dict[str, Any],
    vllm_binary: str,
    host: str,
    port: int,
    log_path: Path,
) -> tuple[subprocess.Popen[str], list[str]]:
    model = str(plan["name"])
    tp = int(plan.get("tensor_parallel_size", 1))
    dtype = str(plan.get("dtype", "float16"))
    quant = str(plan.get("quantization", "") or "")
    gmu = float(plan.get("gpu_memory_utilization", 0.90))
    max_model_len = int(plan.get("max_model_len", 4096))
    enforce_eager = bool(plan.get("enforce_eager", True))
    enable_prefix_caching = bool(plan.get("enable_prefix_caching", False))

    cmd = [
        vllm_binary,
        "serve",
        model,
        "--host",
        host,
        "--port",
        str(port),
        "--tensor-parallel-size",
        str(tp),
        "--gpu-memory-utilization",
        str(gmu),
        "--dtype",
        dtype,
        "--max-model-len",
        str(max_model_len),
        "--enable-sleep-mode",
    ]
    if quant:
        cmd.extend(["--quantization", quant])
    if enforce_eager:
        cmd.append("--enforce-eager")
    if enable_prefix_caching:
        cmd.append("--enable-prefix-caching")

    env = os.environ.copy()
    env["VLLM_SERVER_DEV_MODE"] = "1"
    # Keep helper tools (for example `ninja` used by FlashInfer JIT) available
    # even when the virtualenv is not activated in the caller shell.
    vllm_bin_dir = str(Path(vllm_binary).resolve().parent)
    current_path = env.get("PATH", "")
    env["PATH"] = (
        vllm_bin_dir
        if not current_path
        else f"{vllm_bin_dir}{os.pathsep}{current_path}"
    )
    gpu_devices = str(plan.get("gpu_devices", "") or "")
    if gpu_devices and gpu_devices.lower() not in ("all", "none"):
        env["CUDA_VISIBLE_DEVICES"] = gpu_devices
    elif gpu_devices.lower() == "none":
        env["CUDA_VISIBLE_DEVICES"] = ""

    log_file = log_path.open("w", encoding="utf-8")
    try:
        process = subprocess.Popen(
            cmd,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
    finally:
        log_file.close()
    return process, cmd


def stop_process(process: subprocess.Popen[str], timeout_s: float = 20.0) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout_s)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="vLLM sleep benchmark (VRAM before/during/after + wake latency)."
    )
    parser.add_argument(
        "--plan-file",
        help="Optional JSON file with model plans. Defaults to built-in plans.",
    )
    parser.add_argument(
        "--models",
        default="",
        help="Comma-separated model names to run from the plan (default: all).",
    )
    parser.add_argument(
        "--vllm-binary",
        default=str(Path(".venv/bin/vllm")),
        help="Path to vLLM CLI binary.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port-start", type=int, default=11560)
    parser.add_argument("--sleep-levels", default="1,2")
    parser.add_argument("--sleep-mode", default="wait", choices=["abort", "wait", "keep"])
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--baseline-seconds", type=float, default=8.0)
    parser.add_argument("--sleep-hold-seconds", type=float, default=20.0)
    parser.add_argument("--recovery-seconds", type=float, default=8.0)
    parser.add_argument("--sample-interval-seconds", type=float, default=0.5)
    parser.add_argument("--startup-timeout-seconds", type=float, default=420.0)
    parser.add_argument("--sleep-state-timeout-seconds", type=float, default=90.0)
    parser.add_argument("--wake-response-timeout-seconds", type=float, default=180.0)
    parser.add_argument("--per-request-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--probe-max-tokens", type=int, default=16)
    parser.add_argument(
        "--skip-missing-cache",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip models missing from local HF cache to avoid large downloads.",
    )
    parser.add_argument(
        "--output-dir",
        default="bench_results",
        help="Directory where benchmark artifacts are written.",
    )
    args = parser.parse_args()

    sleep_levels = parse_sleep_levels(args.sleep_levels)
    model_filter = {m.strip() for m in args.models.split(",") if m.strip()}
    plans = load_plans(args.plan_file, model_filter if model_filter else None)

    if not plans:
        print("No model plans selected. Nothing to run.")
        return 0

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir) / f"sleep_benchmark_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] Output directory: {out_dir}", flush=True)
    print(f"[INFO] vLLM binary: {args.vllm_binary}", flush=True)

    summaries: list[SleepRunSummary] = []
    raw_records: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for idx, plan in enumerate(plans):
        model = str(plan.get("name", "")).strip()
        if not model:
            failures.append({"model": model, "reason": "invalid plan: missing name"})
            continue

        cache_dir = model_cache_dir(model)
        if args.skip_missing_cache and not cache_dir.exists():
            msg = f"cache missing at {cache_dir}"
            print(f"[SKIP] {model}: {msg}")
            skipped.append({"model": model, "reason": msg})
            continue

        port = args.port_start + idx
        base_url = f"http://{args.host}:{port}"
        model_slug = slugify(model)
        log_path = out_dir / f"{model_slug}.log"

        print(f"[INFO] Starting model {model} on {base_url}", flush=True)
        process: subprocess.Popen[str] | None = None
        cmd: list[str] = []

        try:
            process, cmd = start_vllm(
                plan=plan,
                vllm_binary=args.vllm_binary,
                host=args.host,
                port=port,
                log_path=log_path,
            )
            ready_ms = wait_until_ready(
                base_url,
                timeout_s=args.startup_timeout_seconds,
                process=process,
                log_path=log_path,
            )

            # Warmup once before measured runs.
            _, _, warmup_ms = http_request_json(
                "POST",
                f"{base_url}/v1/chat/completions",
                body=make_probe_payload(model, args.probe_max_tokens),
                timeout_s=args.per_request_timeout_seconds,
            )

            for repeat in range(1, args.repeats + 1):
                baseline_samples = collect_samples(
                    duration_s=args.baseline_seconds,
                    interval_s=args.sample_interval_seconds,
                )
                baseline_summary = summarize_samples(baseline_samples)
                del baseline_summary  # baseline stored raw; primary comparison is sleep-window.

                for level in sleep_levels:
                    before_sleep = query_gpu_snapshot()

                    sleep_url = (
                        f"{base_url}/sleep?"
                        f"{urllib.parse.urlencode({'level': str(level), 'mode': args.sleep_mode})}"
                    )
                    _, _, sleep_call_ms = http_request_json(
                        "POST", sleep_url, body=None, timeout_s=30.0
                    )
                    sleep_to_state_ms = wait_sleep_state(
                        base_url, target=True, timeout_s=args.sleep_state_timeout_seconds
                    )

                    during_sleep_samples = collect_samples(
                        duration_s=args.sleep_hold_seconds,
                        interval_s=args.sample_interval_seconds,
                    )
                    during_summary = summarize_samples(during_sleep_samples)
                    after_sleep = query_gpu_snapshot()

                    _, _, wake_call_ms = http_request_json(
                        "POST", f"{base_url}/wake_up", body=None, timeout_s=30.0
                    )
                    wake_to_not_sleeping_ms = wait_sleep_state(
                        base_url, target=False, timeout_s=args.sleep_state_timeout_seconds
                    )
                    wake_to_first_ms, first_req_ms, attempts = wait_for_first_response_after_wake(
                        base_url=base_url,
                        model=model,
                        per_request_timeout_s=args.per_request_timeout_seconds,
                        overall_timeout_s=args.wake_response_timeout_seconds,
                        max_tokens=args.probe_max_tokens,
                    )

                    after_wake = query_gpu_snapshot()
                    post_wake_samples = collect_samples(
                        duration_s=args.recovery_seconds,
                        interval_s=args.sample_interval_seconds,
                    )
                    after_first_response = post_wake_samples[-1] if post_wake_samples else after_wake

                    summary = SleepRunSummary(
                        timestamp_utc=utc_now(),
                        model=model,
                        sleep_level=level,
                        repeat=repeat,
                        ready_ms=ready_ms,
                        warmup_ms=warmup_ms,
                        sleep_call_ms=sleep_call_ms,
                        sleep_to_state_ms=sleep_to_state_ms,
                        wake_call_ms=wake_call_ms,
                        wake_to_not_sleeping_ms=wake_to_not_sleeping_ms,
                        wake_to_first_response_ms=wake_to_first_ms,
                        first_response_latency_ms=first_req_ms,
                        probe_attempts=attempts,
                        vram_before_sleep_total_mb=float(before_sleep["total_used_mb"]),
                        vram_sleep_min_total_mb=float(during_summary["min_total_mb"]),
                        vram_sleep_avg_total_mb=float(during_summary["avg_total_mb"]),
                        vram_sleep_max_total_mb=float(during_summary["max_total_mb"]),
                        vram_after_sleep_total_mb=float(after_sleep["total_used_mb"]),
                        vram_after_wake_total_mb=float(after_wake["total_used_mb"]),
                        vram_after_first_response_total_mb=float(after_first_response["total_used_mb"]),
                    )
                    summaries.append(summary)

                    raw_records.append(
                        {
                            "summary": summary.__dict__,
                            "model_plan": plan,
                            "spawn_cmd": cmd,
                            "before_sleep_snapshot": before_sleep,
                            "during_sleep_samples": during_sleep_samples,
                            "after_sleep_snapshot": after_sleep,
                            "after_wake_snapshot": after_wake,
                            "post_wake_samples": post_wake_samples,
                            "baseline_samples": baseline_samples,
                        }
                    )
                    print(
                        "[OK] "
                        f"model={model} repeat={repeat} level={level} "
                        f"sleep_min={summary.vram_sleep_min_total_mb:.1f}MB "
                        f"wake_to_first={summary.wake_to_first_response_ms:.1f}ms"
                    ,
                        flush=True,
                    )

        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] model={model}: {exc}", file=sys.stderr, flush=True)
            failures.append({"model": model, "error": str(exc), "log_path": str(log_path)})
        finally:
            if process is not None:
                stop_process(process)

    csv_path = out_dir / "sleep_benchmark_summary.csv"
    json_path = out_dir / "sleep_benchmark_raw.json"
    meta_path = out_dir / "sleep_benchmark_meta.json"

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(SleepRunSummary.__annotations__.keys()),
        )
        writer.writeheader()
        for row in summaries:
            writer.writerow(row.__dict__)

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(raw_records, f, indent=2)

    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp_utc": utc_now(),
                "args": vars(args),
                "plans_selected": plans,
                "sleep_levels": sleep_levels,
                "rows_written": len(summaries),
                "skipped": skipped,
                "failures": failures,
                "csv_path": str(csv_path),
                "raw_json_path": str(json_path),
            },
            f,
            indent=2,
        )

    print(f"[INFO] Summary CSV: {csv_path}", flush=True)
    print(f"[INFO] Raw JSON:    {json_path}", flush=True)
    print(f"[INFO] Meta JSON:   {meta_path}", flush=True)
    print(f"[INFO] Rows written: {len(summaries)}", flush=True)
    if skipped:
        print(f"[INFO] Skipped models: {len(skipped)}", flush=True)
    if failures:
        print(f"[WARN] Failures: {len(failures)}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
