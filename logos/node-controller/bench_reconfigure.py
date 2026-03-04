#!/usr/bin/env python3
"""
Benchmark: measure actual model reload time after num_parallel reconfigure.

Tests the hypothesis that page-cache-warm reloads are near-instant for
model weights, with PCIe transfer being the dominant cost.

Scenarios:
  1. WARM switch: model actively loaded → reconfigure → measure reload
  2. COLD switch: drop page cache → reconfigure → measure reload (Linux only)
  3. Round-trip: 4x → 8x → 4x cycle time

Usage:
  python bench_reconfigure.py [--base-url http://localhost:8443] [--rounds 3]
"""

import argparse
import time
import json
import urllib.request
import urllib.error
import sys


API_KEY = "RANDOM_DEFAULT_KEY"
OLLAMA_URL = "http://localhost:11434"


def api(base: str, method: str, path: str, body: dict | None = None) -> tuple[dict, float]:
    """Make an API call, return (response_json, elapsed_seconds)."""
    url = f"{base}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {API_KEY}",
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


def wait_for_model_loaded(model: str, timeout: float = 60) -> float:
    """Poll /api/ps until the model appears (any size — size_vram=0 on CPU). Return seconds waited."""
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        try:
            req = urllib.request.Request(f"{OLLAMA_URL}/api/ps")
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


def ensure_model_loaded(base: str, model: str):
    """Make sure the model is loaded and warm by running a tiny generate."""
    print(f"  Warming model '{model}' with a generate call...")
    try:
        body = {"model": model, "prompt": "hi", "stream": False}
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp.read()
        print(f"  Model '{model}' is warm and serving.")
    except Exception as e:
        print(f"  Warning: generate call failed: {e}")


def get_current_config(base: str) -> dict:
    result, _ = api(base, "GET", "/config")
    return result


def reconfigure(base: str, updates: dict) -> tuple[dict, float]:
    """Call reconfigure and return (response, elapsed)."""
    return api(base, "POST", "/admin/ollama/reconfigure", updates)


def bench_warm_switch(base: str, model: str, from_parallel: int, to_parallel: int) -> dict:
    """
    Benchmark: model loaded at from_parallel → reconfigure to to_parallel.
    Page cache should be warm.
    """
    print(f"\n{'='*60}")
    print(f"WARM SWITCH: num_parallel {from_parallel} → {to_parallel}")
    print(f"{'='*60}")

    # Step 1: Set initial config
    print(f"\n[1] Setting num_parallel={from_parallel}...")
    resp, t_initial = reconfigure(base, {"num_parallel": from_parallel})
    print(f"    Reconfigure took {t_initial*1000:.0f}ms")
    if resp.get("details", {}).get("restarted"):
        print(f"    Container restarted. Waiting for model to load...")
        t_preload = wait_for_model_loaded(model, timeout=60)
        print(f"    Model loaded in {t_preload*1000:.0f}ms")
    else:
        print(f"    No restart needed (already at {from_parallel})")

    # Step 2: Ensure model is warm (run inference)
    ensure_model_loaded(base, model)

    # Step 3: Reconfigure to target
    print(f"\n[2] Switching num_parallel={from_parallel} → {to_parallel}...")
    t_start = time.perf_counter()

    resp, t_reconfig = reconfigure(base, {"num_parallel": to_parallel})
    t_api = time.perf_counter() - t_start
    print(f"    Reconfigure API returned in {t_reconfig*1000:.0f}ms")
    print(f"    Response: {resp.get('message', '')}")
    restarted = resp.get("details", {}).get("restarted", False)
    print(f"    Restarted: {restarted}")

    # Step 4: Wait for model to be loaded in VRAM
    if restarted:
        print(f"\n[3] Waiting for model to appear in VRAM...")
        t_model_load = wait_for_model_loaded(model, timeout=60)
        t_total = time.perf_counter() - t_start
        print(f"    Model loaded in VRAM: {t_model_load*1000:.0f}ms after API call")
        print(f"    Total end-to-end: {t_total*1000:.0f}ms")
    else:
        t_model_load = 0
        t_total = t_api
        print(f"    No restart — model already loaded")

    # Step 5: Verify model works
    print(f"\n[4] Verifying inference works at {to_parallel}x...")
    body = {"model": model, "prompt": "Say hello", "stream": False}
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
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
        "reconfigure_api_ms": round(t_reconfig * 1000),
        "model_reload_ms": round(t_model_load * 1000),
        "total_switch_ms": round(t_total * 1000),
        "first_inference_ms": round(t_inference * 1000),
        "restarted": restarted,
    }


def bench_round_trip(base: str, model: str, low: int, high: int, rounds: int) -> list[dict]:
    """Benchmark multiple round trips: low → high → low → high ..."""
    print(f"\n{'='*60}")
    print(f"ROUND TRIP: {low}x ↔ {high}x  ({rounds} cycles)")
    print(f"{'='*60}")

    results = []
    current = get_current_config(base).get("num_parallel", low)

    for i in range(rounds):
        print(f"\n--- Cycle {i+1}/{rounds} ---")

        # Go to low if not there
        if current != low:
            r = bench_warm_switch(base, model, current, low)
            results.append(r)
            current = low

        # low → high
        r = bench_warm_switch(base, model, low, high)
        results.append(r)
        current = high

        # high → low
        r = bench_warm_switch(base, model, high, low)
        results.append(r)
        current = low

    return results


def print_summary(results: list[dict]):
    """Print a summary table."""
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"{'Scenario':<30} {'Reconfig':>10} {'Reload':>10} {'Total':>10} {'1st Inf':>10}")
    print(f"{'-'*30} {'-'*10} {'-'*10} {'-'*10} {'-'*10}")
    for r in results:
        if not r["restarted"]:
            continue
        print(f"{r['scenario']:<30} {r['reconfigure_api_ms']:>8}ms {r['model_reload_ms']:>8}ms "
              f"{r['total_switch_ms']:>8}ms {r['first_inference_ms']:>8}ms")

    # Averages
    restarted = [r for r in results if r["restarted"]]
    if restarted:
        avg_total = sum(r["total_switch_ms"] for r in restarted) / len(restarted)
        avg_reload = sum(r["model_reload_ms"] for r in restarted) / len(restarted)
        avg_reconfig = sum(r["reconfigure_api_ms"] for r in restarted) / len(restarted)
        print(f"\n{'AVERAGE':<30} {avg_reconfig:>8.0f}ms {avg_reload:>8.0f}ms {avg_total:>8.0f}ms")


def main():
    parser = argparse.ArgumentParser(description="Benchmark num_parallel reconfigure speed")
    parser.add_argument("--base-url", default="http://localhost:8443", help="Node controller base URL")
    parser.add_argument("--model", default="qwen2.5:0.5b", help="Model to benchmark")
    parser.add_argument("--low", type=int, default=4, help="Low parallelism")
    parser.add_argument("--high", type=int, default=8, help="High parallelism")
    parser.add_argument("--rounds", type=int, default=3, help="Number of round-trip cycles")
    args = parser.parse_args()

    print(f"Node Controller: {args.base_url}")
    print(f"Ollama:          {OLLAMA_URL}")
    print(f"Model:           {args.model}")
    print(f"Parallelism:     {args.low}x ↔ {args.high}x")
    print(f"Rounds:          {args.rounds}")

    # Verify connectivity
    try:
        cfg = get_current_config(args.base_url)
        print(f"\nCurrent config: num_parallel={cfg.get('num_parallel')}, "
              f"preload_models={cfg.get('preload_models')}")
    except Exception as e:
        print(f"\nERROR: Cannot reach node controller at {args.base_url}: {e}")
        sys.exit(1)

    results = bench_round_trip(args.base_url, args.model, args.low, args.high, args.rounds)
    print_summary(results)

    # Dump raw JSON
    print(f"\nRaw results:")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
