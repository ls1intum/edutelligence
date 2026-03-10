#!/usr/bin/env python3
"""
Benchmark: measure actual model reload time after num_parallel reconfigure.

Tests the hypothesis that page-cache-warm reloads are near-instant for
model weights, with PCIe transfer being the dominant cost.

Scenarios:
  1. WARM switch: model actively loaded → reconfigure → measure reload
  2. COLD switch: drop page cache → reconfigure → measure reload (Linux only)
  3. Round-trip: 4x → 8x → 4x cycle time
    4. (New) Optional preload timing after reconfigure

Usage:
  python bench_reconfigure.py [--base-url http://localhost:8444] [--rounds 3]
"""

import argparse
import os
import time
import json
import urllib.request
import urllib.error
import sys


DEFAULT_API_KEY = "RANDOM_DEFAULT_KEY"


def api(
    base: str,
    api_key: str,
    method: str,
    path: str,
    body: dict | None = None,
) -> tuple[dict, float]:
    """Make an API call, return (response_json, elapsed_seconds)."""
    url = f"{base}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        result = json.loads(e.read()) if e.readable() else {"error": str(e)}
    elapsed = time.perf_counter() - t0
    return result, elapsed


def wait_for_model_loaded(ollama_url: str, model: str, timeout: float = 60) -> float:
    """Poll /api/ps until the model appears (any size — size_vram=0 on CPU). Return seconds waited."""
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        try:
            req = urllib.request.Request(f"{ollama_url}/api/ps")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            for m in data.get("models", []):
                # On CPU-only (macOS), size_vram is always 0. Check size > 0 instead.
                if m["name"] == model and m.get("size", 0) > 0:
                    return time.perf_counter() - t0
        except Exception:
            pass
        time.sleep(0.1)
    print(f"    WARNING: model '{model}' did not appear in /api/ps within {timeout}s")
    return time.perf_counter() - t0


def ensure_model_loaded(ollama_url: str, model: str) -> float | None:
    """Make sure the model is loaded and warm by running a tiny generate."""
    print(f"  Warming model '{model}' with a generate call...")
    t0 = time.perf_counter()
    try:
        body = {"model": model, "prompt": "hi", "stream": False}
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{ollama_url}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp.read()
        elapsed = time.perf_counter() - t0
        print(f"  Model '{model}' is warm and serving ({elapsed*1000:.0f}ms).")
        return elapsed
    except Exception as e:
        print(f"  Warning: generate call failed: {e}")
        return None


def get_current_config(base: str, api_key: str) -> dict:
    result, _ = api(base, api_key, "GET", "/config")
    return result


def reconfigure(base: str, api_key: str, updates: dict) -> tuple[dict, float]:
    """Call reconfigure and return (response, elapsed)."""
    return api(base, api_key, "POST", "/admin/ollama/reconfigure", updates)


def preload_model(base: str, api_key: str, model: str) -> tuple[dict, float]:
    """Call preload and return (response, elapsed)."""
    return api(base, api_key, "POST", "/admin/models/preload", {"model": model})


def bench_warm_switch(
    base: str,
    api_key: str,
    ollama_url: str,
    model: str,
    from_parallel: int,
    to_parallel: int,
    preload_after: bool,
) -> dict:
    """
    Benchmark: model loaded at from_parallel → reconfigure to to_parallel.
    Page cache should be warm.
    """
    print(f"\n{'='*60}")
    print(f"WARM SWITCH: num_parallel {from_parallel} → {to_parallel}")
    print(f"{'='*60}")

    # Step 1: Set initial config
    print(f"\n[1] Setting num_parallel={from_parallel}...")
    resp, t_initial = reconfigure(base, api_key, {"num_parallel": from_parallel})
    print(f"    Reconfigure took {t_initial*1000:.0f}ms")
    initial_restarted = resp.get("details", {}).get("restarted", False)
    before_preload_api = None
    t_preload = None
    if initial_restarted:
        if preload_after:
            print("    Process restarted. Preloading model...")
            _, before_preload_api = preload_model(base, api_key, model)
            print(f"    Preload API returned in {before_preload_api*1000:.0f}ms")
        print(f"    Waiting for model to load...")
        t_preload = wait_for_model_loaded(ollama_url, model, timeout=60)
        print(f"    Model loaded in {t_preload*1000:.0f}ms")
    else:
        print(f"    No restart needed (already at {from_parallel})")

    # Step 2: Ensure model is warm (run inference)
    warm_inference = ensure_model_loaded(ollama_url, model)

    # Step 3: Reconfigure to target
    print(f"\n[2] Switching num_parallel={from_parallel} → {to_parallel}...")
    t_start = time.perf_counter()

    resp, t_reconfig = reconfigure(base, api_key, {"num_parallel": to_parallel})
    t_api = time.perf_counter() - t_start
    print(f"    Reconfigure API returned in {t_reconfig*1000:.0f}ms")
    print(f"    Response: {resp.get('message', '')}")
    restarted = resp.get("details", {}).get("restarted", False)
    print(f"    Restarted: {restarted}")

    # Step 4: Preload model after restart (optional)
    preload_api = None
    preload_success = None
    if restarted:
        if preload_after:
            print(f"\n[3] Preloading model after reconfigure...")
            preload_resp, preload_api = preload_model(base, api_key, model)
            preload_success = bool(preload_resp.get("success"))
            print(f"    Preload API returned in {preload_api*1000:.0f}ms")
            if not preload_success:
                print(f"    Warning: preload failed: {preload_resp}")
        # Step 5: Wait for model to be loaded in VRAM
        print(f"\n[4] Waiting for model to appear in VRAM...")
        t_model_load = wait_for_model_loaded(ollama_url, model, timeout=60)
        t_total = time.perf_counter() - t_start
        print(f"    Model loaded in VRAM: {t_model_load*1000:.0f}ms after API call")
        print(f"    Total end-to-end: {t_total*1000:.0f}ms")
    else:
        t_model_load = 0
        t_total = t_api
        print(f"    No restart — model already loaded")

    # Step 6: Verify model works
    print(f"\n[5] Verifying inference works at {to_parallel}x...")
    body = {"model": model, "prompt": "Say hello", "stream": False}
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{ollama_url}/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=60) as r:
        gen_resp = json.loads(r.read())
    t_inference = time.perf_counter() - t0
    print(f"    First inference at {to_parallel}x: {t_inference*1000:.0f}ms")
    print(f"    Tokens: {gen_resp.get('eval_count', '?')}, "
          f"eval rate: {gen_resp.get('eval_count', 0) / max(gen_resp.get('eval_duration', 1) / 1e9, 0.001):.1f} tok/s")

    return {
        "scenario": f"warm_{from_parallel}x_to_{to_parallel}x",
        "before_reconfigure_ms": round(t_initial * 1000),
        "before_preload_api_ms": round(before_preload_api * 1000) if before_preload_api is not None else None,
        "before_model_reload_ms": round(t_preload * 1000) if t_preload is not None else None,
        "before_restarted": initial_restarted,
        "warm_inference_ms": round(warm_inference * 1000) if warm_inference is not None else None,
        "reconfigure_api_ms": round(t_reconfig * 1000),
        "preload_api_ms": round(preload_api * 1000) if preload_api is not None else None,
        "preload_success": preload_success,
        "model_reload_ms": round(t_model_load * 1000),
        "total_switch_ms": round(t_total * 1000),
        "first_inference_ms": round(t_inference * 1000),
        "restarted": restarted,
    }


def bench_round_trip(
    base: str,
    api_key: str,
    ollama_url: str,
    model: str,
    low: int,
    high: int,
    rounds: int,
    preload_after: bool,
) -> list[dict]:
    """Benchmark multiple round trips: low → high → low → high ..."""
    print(f"\n{'='*60}")
    print(f"ROUND TRIP: {low}x ↔ {high}x  ({rounds} cycles)")
    print(f"{'='*60}")

    results = []
    current = get_current_config(base, api_key).get("num_parallel", low)

    for i in range(rounds):
        print(f"\n--- Cycle {i+1}/{rounds} ---")

        # Go to low if not there
        if current != low:
            r = bench_warm_switch(base, api_key, ollama_url, model, current, low, preload_after)
            results.append(r)
            current = low

        # low → high
        r = bench_warm_switch(base, api_key, ollama_url, model, low, high, preload_after)
        results.append(r)
        current = high

        # high → low
        r = bench_warm_switch(base, api_key, ollama_url, model, high, low, preload_after)
        results.append(r)
        current = low

    return results


def print_summary(results: list[dict]):
    """Print a summary table."""
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(
        f"{'Scenario':<30} {'Warm':>8} {'Reconf':>8} {'Preld':>8} "
        f"{'Reload':>8} {'Total':>8} {'1stInf':>8}"
    )
    print(f"{'-'*30} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
    for r in results:
        if not r["restarted"]:
            continue
        warm_ms = r.get("warm_inference_ms")
        warm_display = f"{warm_ms}ms" if warm_ms is not None else "n/a"
        preload_ms = r.get("preload_api_ms")
        preload_display = f"{preload_ms}ms" if preload_ms is not None else "n/a"
        print(
            f"{r['scenario']:<30} {warm_display:>8} {r['reconfigure_api_ms']:>6}ms "
            f"{preload_display:>8} {r['model_reload_ms']:>6}ms "
            f"{r['total_switch_ms']:>6}ms {r['first_inference_ms']:>6}ms"
        )

    # Averages
    restarted = [r for r in results if r["restarted"]]
    if restarted:
        def _avg(values: list[int]) -> float | None:
            return sum(values) / len(values) if values else None

        avg_total = _avg([r["total_switch_ms"] for r in restarted])
        avg_reload = _avg([r["model_reload_ms"] for r in restarted])
        avg_reconfig = _avg([r["reconfigure_api_ms"] for r in restarted])
        avg_warm = _avg([r["warm_inference_ms"] for r in restarted if r.get("warm_inference_ms") is not None])
        avg_preload = _avg([r["preload_api_ms"] for r in restarted if r.get("preload_api_ms") is not None])
        avg_first = _avg([r["first_inference_ms"] for r in restarted])

        def _fmt(value: float | None) -> str:
            return f"{value:.0f}ms" if value is not None else "n/a"

        print(
            f"\n{'AVERAGE':<30} {_fmt(avg_warm):>8} {_fmt(avg_reconfig):>8} "
            f"{_fmt(avg_preload):>8} {_fmt(avg_reload):>8} {_fmt(avg_total):>8} {_fmt(avg_first):>8}"
        )


def main():
    parser = argparse.ArgumentParser(description="Benchmark num_parallel reconfigure speed")
    parser.add_argument("--base-url", default="http://localhost:8444", help="Node controller base URL")
    parser.add_argument("--model", default="qwen2.5:0.5b", help="Model to benchmark")
    parser.add_argument("--low", type=int, default=4, help="Low parallelism")
    parser.add_argument("--high", type=int, default=8, help="High parallelism")
    parser.add_argument("--rounds", type=int, default=3, help="Number of round-trip cycles")
    parser.add_argument("--api-key", default=os.environ.get("API_KEY", DEFAULT_API_KEY), help="Controller API key")
    parser.add_argument("--ollama-url", default=os.environ.get("OLLAMA_URL"), help="Ollama base URL")
    parser.add_argument("--no-preload", action="store_true", help="Skip preload after reconfigure")
    args = parser.parse_args()

    print(f"Node Controller: {args.base_url}")
    print(f"Ollama:          {args.ollama_url or '(auto)'}")
    print(f"Model:           {args.model}")
    print(f"Parallelism:     {args.low}x ↔ {args.high}x")
    print(f"Rounds:          {args.rounds}")
    print(f"Preload:         {'off' if args.no_preload else 'on'}")

    # Verify connectivity
    try:
        cfg = get_current_config(args.base_url, args.api_key)
        print(f"\nCurrent config: num_parallel={cfg.get('num_parallel')}, "
              f"preload_models={cfg.get('preload_models')}")
    except Exception as e:
        print(f"\nERROR: Cannot reach node controller at {args.base_url}: {e}")
        sys.exit(1)

    ollama_port = int(cfg.get("port", 11435))
    ollama_url = args.ollama_url or f"http://localhost:{ollama_port}"
    print(f"Ollama URL:      {ollama_url}")

    results = bench_round_trip(
        args.base_url,
        args.api_key,
        ollama_url,
        args.model,
        args.low,
        args.high,
        args.rounds,
        not args.no_preload,
    )
    print_summary(results)

    # Dump raw JSON
    print(f"\nRaw results:")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
