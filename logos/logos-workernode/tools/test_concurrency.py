"""
Concurrency test: compare wall-clock time for 8 concurrent requests
on Lane A (num_parallel=1) vs Lane B (num_parallel=16).
"""
import asyncio
import time
import httpx

PROMPT = "Count from 1 to 20."
NUM_PREDICT = 40
N_REQUESTS = 8

LANE_A = "http://127.0.0.1:11440"  # tinyllama, num_parallel=1
LANE_B = "http://127.0.0.1:11441"  # gemma3:4b, num_parallel=16


async def send_request(client: httpx.AsyncClient, url: str, model: str, req_id: int):
    """Send a single generate request, return (req_id, elapsed, token_count)."""
    payload = {
        "model": model,
        "prompt": PROMPT,
        "stream": False,
        "options": {"num_predict": NUM_PREDICT},
    }
    t0 = time.monotonic()
    resp = await client.post(f"{url}/api/generate", json=payload, timeout=120)
    elapsed = time.monotonic() - t0
    data = resp.json()
    tokens = data.get("eval_count", 0)
    return req_id, elapsed, tokens


async def run_batch(url: str, model: str, label: str):
    """Fire N_REQUESTS concurrently and report timing."""
    print(f"\n{'='*60}")
    print(f"  {label}  —  {N_REQUESTS} concurrent requests")
    print(f"  URL: {url}  Model: {model}")
    print(f"{'='*60}")

    # Warm-up: single request to ensure model is fully loaded
    async with httpx.AsyncClient() as client:
        _, warm_t, _ = await send_request(client, url, model, 0)
        print(f"  Warm-up: {warm_t:.2f}s")

    # Concurrent batch
    async with httpx.AsyncClient() as client:
        wall_start = time.monotonic()
        tasks = [send_request(client, url, model, i + 1) for i in range(N_REQUESTS)]
        results = await asyncio.gather(*tasks)
        wall_elapsed = time.monotonic() - wall_start

    for req_id, elapsed, tokens in sorted(results):
        print(f"  req {req_id:2d}: {elapsed:6.2f}s  ({tokens} tokens)")

    individual_times = [r[1] for r in results]
    total_tokens = sum(r[2] for r in results)
    print(f"  ──────────────────────────────────")
    print(f"  Wall-clock (all {N_REQUESTS}): {wall_elapsed:.2f}s")
    print(f"  Sum of individual:    {sum(individual_times):.2f}s")
    print(f"  Mean individual:      {sum(individual_times)/len(individual_times):.2f}s")
    print(f"  Total tokens:         {total_tokens}")
    print(f"  Throughput:           {total_tokens/wall_elapsed:.1f} tok/s (wall-clock)")
    return wall_elapsed


async def main():
    print("Concurrency test: num_parallel=1 vs num_parallel=16")
    print(f"Prompt: {PROMPT!r}  |  num_predict={NUM_PREDICT}  |  N={N_REQUESTS}")

    wall_a = await run_batch(LANE_A, "tinyllama", "Lane A — tinyllama @ num_parallel=1")
    wall_b = await run_batch(LANE_B, "tinyllama", "Lane B — tinyllama @ num_parallel=16")

    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    print(f"  Lane A wall-clock: {wall_a:.2f}s  (num_parallel=1)")
    print(f"  Lane B wall-clock: {wall_b:.2f}s  (num_parallel=16)")
    if wall_a > 0:
        print(f"  Ratio A/B:         {wall_a/wall_b:.2f}x")
    print()


if __name__ == "__main__":
    asyncio.run(main())
