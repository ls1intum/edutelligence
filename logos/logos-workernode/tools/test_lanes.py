#!/usr/bin/env python3
"""
Multi-lane parallelism test.

Spawns two Ollama processes on GPU 1:
  - Lane A: tinyllama @ num_parallel=1  (port 11440)
  - Lane B: gemma3:4b @ num_parallel=16 (port 11441)

Then fires 8 concurrent requests at each and compares wall-clock time.
"""

import asyncio
import os
import signal
import subprocess
import sys
import time

import httpx

OLLAMA_BIN = "/usr/local/bin/ollama"
MODELS_PATH = "/usr/share/ollama/.ollama/models"
GPU_DEVICE = "1"  # Pin to GPU 1 (16GB free)

LANE_A_PORT = 11440
LANE_A_MODEL = "tinyllama"
LANE_A_PARALLEL = 1

LANE_B_PORT = 11441
LANE_B_MODEL = "gemma3:4b"
LANE_B_PARALLEL = 16

PROMPT = "Write a short poem about the sea in exactly 4 lines."
NUM_REQUESTS = 8
READY_TIMEOUT = 60
PRELOAD_TIMEOUT = 120


def build_env(port: int, num_parallel: int) -> dict[str, str]:
    env = {
        **os.environ,
        "OLLAMA_HOST": f"0.0.0.0:{port}",
        "OLLAMA_NUM_PARALLEL": str(num_parallel),
        "OLLAMA_MAX_LOADED_MODELS": "1",
        "OLLAMA_KEEP_ALIVE": "10m",
        "OLLAMA_MODELS": MODELS_PATH,
        "OLLAMA_FLASH_ATTENTION": "1",
        "OLLAMA_KV_CACHE_TYPE": "q8_0",
        "OLLAMA_LLM_LIBRARY": "cuda_v12",
        "CUDA_VISIBLE_DEVICES": GPU_DEVICE,
    }
    return env


async def wait_ready(port: int, timeout: int = READY_TIMEOUT) -> bool:
    url = f"http://127.0.0.1:{port}/api/version"
    deadline = time.monotonic() + timeout
    delay = 0.2
    async with httpx.AsyncClient() as client:
        while time.monotonic() < deadline:
            try:
                r = await client.get(url, timeout=5.0)
                if r.status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 2.0)
    return False


async def preload(port: int, model: str) -> bool:
    url = f"http://127.0.0.1:{port}/api/generate"
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(url, json={"model": model}, timeout=PRELOAD_TIMEOUT)
            return r.status_code == 200
        except httpx.HTTPError as e:
            print(f"  Preload failed: {e}")
            return False


async def send_request(client: httpx.AsyncClient, port: int, model: str, idx: int) -> tuple[int, float, bool]:
    """Send one chat request. Returns (index, elapsed_seconds, success)."""
    url = f"http://127.0.0.1:{port}/api/chat"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "stream": False,
    }
    t0 = time.monotonic()
    try:
        r = await client.post(url, json=payload, timeout=300.0)
        elapsed = time.monotonic() - t0
        return idx, elapsed, r.status_code == 200
    except Exception as e:
        elapsed = time.monotonic() - t0
        print(f"  Request {idx} failed: {e}")
        return idx, elapsed, False


async def run_concurrent_test(port: int, model: str, num_parallel: int, n: int) -> list[tuple[int, float, bool]]:
    """Fire n concurrent requests and collect results."""
    print(f"\n{'='*60}")
    print(f"Testing {model} @ num_parallel={num_parallel} (port {port})")
    print(f"Sending {n} concurrent requests...")
    print(f"{'='*60}")

    async with httpx.AsyncClient() as client:
        t0 = time.monotonic()
        tasks = [send_request(client, port, model, i) for i in range(n)]
        results = await asyncio.gather(*tasks)
        wall_clock = time.monotonic() - t0

    successes = sum(1 for _, _, ok in results if ok)
    times = [t for _, t, ok in results if ok]

    print(f"\nResults for {model} (num_parallel={num_parallel}):")
    print(f"  Successes: {successes}/{n}")
    if times:
        print(f"  Min request time: {min(times):.2f}s")
        print(f"  Max request time: {max(times):.2f}s")
        print(f"  Avg request time: {sum(times)/len(times):.2f}s")
    print(f"  Wall clock (all {n} concurrent): {wall_clock:.2f}s")

    # Show completion timeline
    sorted_results = sorted(results, key=lambda x: x[1])
    print(f"\n  Completion timeline:")
    for idx, elapsed, ok in sorted_results:
        status = "OK" if ok else "FAIL"
        print(f"    Request {idx:2d}: {elapsed:6.2f}s [{status}]")

    return results


async def main():
    procs = []

    try:
        # --- Spawn Lane A ---
        print(f"\n[1/6] Spawning Lane A: {LANE_A_MODEL} @ num_parallel={LANE_A_PARALLEL} on port {LANE_A_PORT}...")
        env_a = build_env(LANE_A_PORT, LANE_A_PARALLEL)
        proc_a = subprocess.Popen(
            [OLLAMA_BIN, "serve"],
            env=env_a,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        procs.append(proc_a)
        print(f"  PID: {proc_a.pid}")

        # --- Spawn Lane B ---
        print(f"\n[2/6] Spawning Lane B: {LANE_B_MODEL} @ num_parallel={LANE_B_PARALLEL} on port {LANE_B_PORT}...")
        env_b = build_env(LANE_B_PORT, LANE_B_PARALLEL)
        proc_b = subprocess.Popen(
            [OLLAMA_BIN, "serve"],
            env=env_b,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        procs.append(proc_b)
        print(f"  PID: {proc_b.pid}")

        # --- Wait for ready ---
        print(f"\n[3/6] Waiting for Lane A to be ready...")
        if not await wait_ready(LANE_A_PORT):
            print("  FAILED — Lane A not ready")
            return
        print("  Lane A ready!")

        print(f"\n[4/6] Waiting for Lane B to be ready...")
        if not await wait_ready(LANE_B_PORT):
            print("  FAILED — Lane B not ready")
            return
        print("  Lane B ready!")

        # --- Preload models ---
        print(f"\n[5/6] Preloading {LANE_A_MODEL} on Lane A...")
        t0 = time.monotonic()
        ok = await preload(LANE_A_PORT, LANE_A_MODEL)
        print(f"  {'OK' if ok else 'FAILED'} ({time.monotonic()-t0:.1f}s)")

        print(f"\n[5/6] Preloading {LANE_B_MODEL} on Lane B...")
        t0 = time.monotonic()
        ok = await preload(LANE_B_PORT, LANE_B_MODEL)
        print(f"  {'OK' if ok else 'FAILED'} ({time.monotonic()-t0:.1f}s)")

        # Check VRAM
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,memory.used,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True
        )
        print(f"\n  GPU state after preload:\n  {result.stdout.strip()}")

        # --- Run concurrent tests ---
        print(f"\n[6/6] Running concurrency tests...")

        # Test Lane A (num_parallel=1): should be slow with concurrent requests
        results_a = await run_concurrent_test(LANE_A_PORT, LANE_A_MODEL, LANE_A_PARALLEL, NUM_REQUESTS)

        # Test Lane B (num_parallel=16): should handle concurrency much better
        results_b = await run_concurrent_test(LANE_B_PORT, LANE_B_MODEL, LANE_B_PARALLEL, NUM_REQUESTS)

        # --- Summary ---
        wall_a = max(t for _, t, _ in results_a)
        wall_b = max(t for _, t, _ in results_b)
        print(f"\n{'='*60}")
        print(f"SUMMARY")
        print(f"{'='*60}")
        print(f"  {LANE_A_MODEL} (parallel={LANE_A_PARALLEL}): {wall_a:.2f}s for {NUM_REQUESTS} requests")
        print(f"  {LANE_B_MODEL} (parallel={LANE_B_PARALLEL}): {wall_b:.2f}s for {NUM_REQUESTS} requests")
        if wall_a > 0 and wall_b > 0:
            # Normalise: gemma3 is slower per-token, so compare serial vs parallel within each model
            print(f"\n  Speedup from parallelism (Lane B):")
            avg_b = sum(t for _, t, ok in results_b if ok) / max(1, sum(1 for _, _, ok in results_b if ok))
            serial_estimate_b = avg_b * NUM_REQUESTS  # if processed sequentially
            print(f"    Estimated serial time (avg * {NUM_REQUESTS}): {serial_estimate_b:.2f}s")
            print(f"    Actual wall clock (parallel): {wall_b:.2f}s")
            if wall_b > 0:
                print(f"    Effective speedup: {serial_estimate_b / wall_b:.1f}x")

    finally:
        # --- Cleanup ---
        print("\nCleaning up processes...")
        for p in procs:
            try:
                p.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                pass
        # Give them a moment to die
        await asyncio.sleep(2)
        for p in procs:
            try:
                p.kill()
                p.wait(timeout=5)
            except Exception:
                pass
        print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
