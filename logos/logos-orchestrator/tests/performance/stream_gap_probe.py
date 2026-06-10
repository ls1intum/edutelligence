"""Measure inter-chunk gaps of streaming responses through the Logos proxy.

Opens N concurrent streaming chat completions and records the arrival time
of every chunk. While the probe runs, load the statistics dashboard (or POST
/logosdb/request_log_stats) — before the threadpool offload fix, every
stream's inter-chunk gap jumped to the stats query duration; after the fix,
gaps stay at the upstream cadence.

Typical setup (see mock_sse_upstream.py for a deterministic backend):
    python tests/performance/stream_gap_probe.py \\
        --url http://localhost:8080/v1/chat/completions \\
        --logos-key <key> --model <model-name> --streams 3
"""

import argparse
import asyncio
import json
import statistics
import time

import httpx


async def probe_stream(client: httpx.AsyncClient, args, stream_idx: int) -> dict:
    gaps: list[tuple[float, float]] = []  # (offset_since_start, gap)
    start = time.monotonic()
    prev = start
    chunks = 0
    body = {
        "model": args.model,
        "messages": [{"role": "user", "content": "stream please"}],
        "stream": True,
    }
    headers = {"Authorization": f"Bearer {args.logos_key}"}
    async with client.stream("POST", args.url, json=body, headers=headers) as response:
        response.raise_for_status()
        async for _ in response.aiter_raw():
            now = time.monotonic()
            if chunks > 0:
                gaps.append((now - start, now - prev))
            prev = now
            chunks += 1
    return {"stream": stream_idx, "chunks": chunks, "gaps": gaps}


def report(results: list[dict], threshold: float) -> bool:
    ok = True
    for result in results:
        gap_values = [gap for _, gap in result["gaps"]]
        if not gap_values:
            print(f"stream {result['stream']}: no chunks received!")
            ok = False
            continue
        max_gap = max(gap_values)
        p99 = statistics.quantiles(gap_values, n=100)[98] if len(gap_values) >= 100 else max_gap
        print(
            f"stream {result['stream']}: chunks={result['chunks']} "
            f"max_gap={max_gap * 1000:.0f}ms p99={p99 * 1000:.0f}ms"
        )
        stalls = [(offset, gap) for offset, gap in result["gaps"] if gap > threshold]
        for offset, gap in stalls:
            print(f"  STALL at t+{offset:.1f}s: {gap * 1000:.0f}ms")
        if stalls:
            ok = False
    return ok


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8080/v1/chat/completions")
    parser.add_argument("--logos-key", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--streams", type=int, default=3)
    parser.add_argument(
        "--threshold", type=float, default=0.5, help="Report gaps above this many seconds as stalls"
    )
    args = parser.parse_args()

    async with httpx.AsyncClient(timeout=None) as client:
        results = await asyncio.gather(*(probe_stream(client, args, i) for i in range(args.streams)))

    ok = report(results, args.threshold)
    print("PASS: no stalls above threshold" if ok else "FAIL: stalls detected")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
