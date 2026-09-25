"""Added-latency leg: what the gateway hop costs on top of the fake upstream.

Single-flight (not concurrent — that is the concurrency-ramp leg's job),
non-streaming, interleaved gateway/direct requests within each block so
runner-latency drift hits both series at the same moments and cancels in the
pooled percentile difference — same rationale as
``per_request_overhead/run_benchmark.py``.

Environment (all optional, defaults in parentheses):
  LOGOS_BENCH_GW_LATENCY_WARMUP   (10)
  LOGOS_BENCH_GW_LATENCY_SAMPLES  (60)  per series, per block
  LOGOS_BENCH_GW_LATENCY_BLOCKS   (3)
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List

import gateway_client as gw
import httpx
from stats import overhead_ms, summarize


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)))


async def run() -> Dict[str, Any]:
    warmup = _env_int("LOGOS_BENCH_GW_LATENCY_WARMUP", 10)
    samples = _env_int("LOGOS_BENCH_GW_LATENCY_SAMPLES", 60)
    blocks = _env_int("LOGOS_BENCH_GW_LATENCY_BLOCKS", 3)

    gateway_url = f"{gw.gateway_url()}/v1/chat/completions"
    upstream_url = f"{gw.upstream_url()}/v1/chat/completions"
    gateway_headers = gw.gateway_headers()
    upstream_headers = gw.upstream_headers()

    gateway_ms: List[float] = []
    direct_ms: List[float] = []
    failures: List[str] = []

    timeout = httpx.Timeout(30.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for i in range(warmup):
            r = await gw.post_chat_completion(client, gateway_url, gateway_headers)
            if not r.ok:
                failures.append(f"warmup {i}: {r.error}")

        for block in range(blocks):
            for i in range(samples):
                # Interleaved: one gateway, one direct, alternating — the
                # simplest interleave that still spreads both series evenly
                # across the block (samples-per-series are equal here, unlike
                # per_request_overhead's asymmetric logos/direct ratio).
                rg = await gw.post_chat_completion(client, gateway_url, gateway_headers)
                if rg.ok:
                    gateway_ms.append(rg.total_ms)
                else:
                    failures.append(f"block {block} gateway {i}: {rg.error}")
                rd = await gw.post_chat_completion(client, upstream_url, upstream_headers)
                if rd.ok:
                    direct_ms.append(rd.total_ms)
                else:
                    failures.append(f"block {block} direct {i}: {rd.error}")
            print(f"  [latency] block {block + 1}/{blocks}: gateway={len(gateway_ms)} direct={len(direct_ms)}")

    return {
        "overhead": overhead_ms(gateway_ms, direct_ms),
        "gateway": summarize(gateway_ms),
        "direct": summarize(direct_ms),
        "failures": failures[:20],
        "n_failures": len(failures),
    }


if __name__ == "__main__":  # pragma: no cover
    import json

    print(json.dumps(asyncio.run(run()), indent=2))
