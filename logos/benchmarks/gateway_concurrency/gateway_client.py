"""Shared async HTTP helpers for the gateway concurrency benchmark's legs.

Config is env vars only, matching ``per_request_overhead``'s convention —
no argparse, no yaml.

Environment (all optional, defaults in parentheses):
  LOGOS_BENCH_GW_URL           (http://localhost:18081)  gateway base URL (Traefik)
  LOGOS_BENCH_GW_UPSTREAM_URL  (http://localhost:9100)   fake cloud upstream, direct
  LOGOS_BENCH_GW_API_KEY       (lg-bench-gw-0000)
  LOGOS_BENCH_GW_MODEL         (bench-cloud-model)
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def gateway_url() -> str:
    return env("LOGOS_BENCH_GW_URL", "http://localhost:18081").rstrip("/")


def upstream_url() -> str:
    return env("LOGOS_BENCH_GW_UPSTREAM_URL", "http://localhost:9100").rstrip("/")


def api_key() -> str:
    return env("LOGOS_BENCH_GW_API_KEY", "lg-bench-gw-0000")


def model_name() -> str:
    return env("LOGOS_BENCH_GW_MODEL", "bench-cloud-model")


def chat_payload(*, stream: bool) -> Dict[str, Any]:
    return {
        "model": model_name(),
        "messages": [{"role": "user", "content": "Benchmark probe: reply with a short fixed answer."}],
        "stream": stream,
    }


@dataclass
class RequestResult:
    ok: bool
    status_code: Optional[int]
    ttfb_ms: Optional[float]
    total_ms: float
    error: Optional[str]


async def stream_chat_completion(client: httpx.AsyncClient, url: str, headers: Dict[str, str]) -> RequestResult:
    """One streaming POST /v1/chat/completions, consumed to the end.

    A held-open stream is what actually occupies a gateway executor-pool
    slot — a client that stopped at the first chunk would under-count
    concurrency held, not model it.
    """
    t0 = time.perf_counter()
    ttfb_ms: Optional[float] = None
    try:
        async with client.stream("POST", url, headers=headers, json=chat_payload(stream=True)) as resp:
            status = resp.status_code
            async for _chunk in resp.aiter_bytes():
                if ttfb_ms is None:
                    ttfb_ms = (time.perf_counter() - t0) * 1000.0
            total_ms = (time.perf_counter() - t0) * 1000.0
            ok = 200 <= status < 300
            return RequestResult(
                ok=ok, status_code=status, ttfb_ms=ttfb_ms, total_ms=total_ms, error=None if ok else f"HTTP {status}"
            )
    except Exception as exc:  # noqa: BLE001 — any transport failure is a benchmark data point, not a crash
        total_ms = (time.perf_counter() - t0) * 1000.0
        return RequestResult(ok=False, status_code=None, ttfb_ms=ttfb_ms, total_ms=total_ms, error=repr(exc))


async def post_chat_completion(client: httpx.AsyncClient, url: str, headers: Dict[str, str]) -> RequestResult:
    """One non-streaming POST /v1/chat/completions (used by the latency-diff leg)."""
    t0 = time.perf_counter()
    try:
        resp = await client.post(url, headers=headers, json=chat_payload(stream=False))
        total_ms = (time.perf_counter() - t0) * 1000.0
        ok = resp.status_code == 200
        return RequestResult(
            ok=ok,
            status_code=resp.status_code,
            ttfb_ms=total_ms,
            total_ms=total_ms,
            error=None if ok else f"HTTP {resp.status_code}: {resp.text[:200]}",
        )
    except Exception as exc:  # noqa: BLE001
        total_ms = (time.perf_counter() - t0) * 1000.0
        return RequestResult(ok=False, status_code=None, ttfb_ms=None, total_ms=total_ms, error=repr(exc))


def gateway_headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"}


def upstream_headers() -> Dict[str, str]:
    return {"Content-Type": "application/json"}
