#!/usr/bin/env python3
"""
Benchmark: qwen3:30b-a3b — Ollama vs vLLM (GGUF)
High-throughput scenario simulating concurrent student requests.

Tests: N=1, 4, 8, 16, 32 concurrent requests
Prompt: Realistic code-review task (educational use case)
"""
import asyncio
import time
import sys
import json
import os
import statistics
import httpx

PROMPT = (
    "/nothink\n"
    "Review this Python function for correctness and style. "
    "Provide specific feedback with line references:\n\n"
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
    "```\n\n"
    "Give 3 specific improvement suggestions."
)

# ~200 token response target
MAX_TOKENS = 200


async def single_request(
    client: httpx.AsyncClient,
    url: str,
    payload: dict,
    req_id: int,
) -> dict:
    """Fire one chat-completion request, measure latency + tokens."""
    t0 = time.perf_counter()
    first_token_time = None
    token_count = 0
    full_text = ""

    try:
        async with client.stream("POST", url, json=payload, timeout=300.0) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "") or ""
                reasoning = delta.get("reasoning", "") or delta.get("reasoning_content", "") or ""
                tok_text = content + reasoning
                if tok_text:
                    if first_token_time is None:
                        first_token_time = time.perf_counter()
                    token_count += 1
                    full_text += tok_text
    except Exception as e:
        return {"req_id": req_id, "error": str(e), "tokens": 0, "latency": 0, "ttft": 0}

    total = time.perf_counter() - t0
    ttft = (first_token_time - t0) if first_token_time else total
    return {
        "req_id": req_id,
        "tokens": token_count,
        "latency": total,
        "ttft": ttft,
        "tok_per_sec": token_count / total if total > 0 else 0,
    }


async def run_batch(
    url: str,
    model: str,
    concurrency: int,
    is_ollama: bool,
) -> dict:
    """Run a batch of concurrent requests."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.1,
        "stream": True,
    }
    # qwen3 thinking mode off for fair comparison
    if not is_ollama:
        # vLLM: use extra_body or just rely on temperature
        pass

    async with httpx.AsyncClient() as client:
        tasks = [
            single_request(client, url, payload, i)
            for i in range(concurrency)
        ]
        t_batch_start = time.perf_counter()
        results = await asyncio.gather(*tasks)
        t_batch_total = time.perf_counter() - t_batch_start

    errors = [r for r in results if "error" in r]
    ok = [r for r in results if "error" not in r]

    if not ok:
        return {
            "concurrency": concurrency,
            "errors": len(errors),
            "error_msgs": [e["error"] for e in errors[:3]],
        }

    total_tokens = sum(r["tokens"] for r in ok)
    latencies = [r["latency"] for r in ok]
    ttfts = [r["ttft"] for r in ok]
    per_req_tps = [r["tok_per_sec"] for r in ok]

    return {
        "concurrency": concurrency,
        "requests_ok": len(ok),
        "errors": len(errors),
        "total_tokens": total_tokens,
        "batch_time_s": round(t_batch_total, 2),
        "aggregate_tok_s": round(total_tokens / t_batch_total, 1),
        "avg_latency_s": round(statistics.mean(latencies), 2),
        "p50_latency_s": round(statistics.median(latencies), 2),
        "p95_latency_s": round(sorted(latencies)[int(len(latencies) * 0.95)], 2) if len(latencies) > 1 else round(latencies[0], 2),
        "avg_ttft_ms": round(statistics.mean(ttfts) * 1000, 0),
        "avg_tok_per_req_s": round(statistics.mean(per_req_tps), 1),
    }


async def warmup(url: str, model: str):
    """Send a single warmup request."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Say hello in one word."}],
        "max_tokens": 5,
        "temperature": 0,
        "stream": False,
    }
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(url, json=payload, timeout=300.0)
            r.raise_for_status()
            print(f"  Warmup OK: {r.status_code}")
        except Exception as e:
            print(f"  Warmup failed: {e}")


async def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("ollama", "vllm"):
        print("Usage: python bench_qwen3.py [ollama|vllm]")
        print("Env overrides: OLLAMA_URL, VLLM_URL")
        sys.exit(1)

    backend = sys.argv[1]
    concurrency_levels = [1, 4, 8, 16, 32]

    if backend == "ollama":
        url = os.environ.get("OLLAMA_URL", "http://localhost:11435/v1/chat/completions")
        model = "qwen3:30b-a3b"
        print(f"\n{'='*60}")
        print(f"BENCHMARK: qwen3:30b-a3b on OLLAMA")
        print(f"{'='*60}")
    else:
        url = os.environ.get("VLLM_URL", "http://localhost:8000/v1/chat/completions")
        model = "/tmp/qwen3-30b-a3b.gguf"
        print(f"\n{'='*60}")
        print(f"BENCHMARK: qwen3:30b-a3b on vLLM (GGUF)")
        print(f"{'='*60}")

    print(f"URL: {url}")
    print(f"Model: {model}")
    print(f"Max tokens: {MAX_TOKENS}")
    print(f"Concurrency levels: {concurrency_levels}")
    print(f"\nWarming up...")
    await warmup(url, model)

    all_results = []
    for n in concurrency_levels:
        print(f"\n--- N={n} concurrent requests ---")
        result = await run_batch(url, model, n, is_ollama=(backend == "ollama"))
        all_results.append(result)

        if "error_msgs" in result:
            print(f"  ALL FAILED: {result['error_msgs']}")
        else:
            print(f"  Batch time:     {result['batch_time_s']}s")
            print(f"  Aggregate:      {result['aggregate_tok_s']} tok/s")
            print(f"  Avg latency:    {result['avg_latency_s']}s")
            print(f"  Avg TTFT:       {result['avg_ttft_ms']}ms")
            print(f"  Per-req tok/s:  {result['avg_tok_per_req_s']}")
            print(f"  Errors:         {result['errors']}")

    print(f"\n{'='*60}")
    print(f"SUMMARY: {backend.upper()}")
    print(f"{'='*60}")
    print(f"{'N':>4s} {'Agg tok/s':>10s} {'Avg lat':>8s} {'P50 lat':>8s} {'P95 lat':>8s} {'TTFT ms':>8s} {'Errors':>6s}")
    print("-" * 56)
    for r in all_results:
        if "error_msgs" in r:
            print(f"{r['concurrency']:>4d} {'FAILED':>10s}")
        else:
            print(
                f"{r['concurrency']:>4d}"
                f" {r['aggregate_tok_s']:>10.1f}"
                f" {r['avg_latency_s']:>8.2f}"
                f" {r['p50_latency_s']:>8.2f}"
                f" {r['p95_latency_s']:>8.2f}"
                f" {r['avg_ttft_ms']:>8.0f}"
                f" {r['errors']:>6d}"
            )


if __name__ == "__main__":
    asyncio.run(main())
