"""Shared async HTTP helpers for the gateway concurrency benchmark's legs.

Config is env vars only, matching ``per_request_overhead``'s convention —
no argparse, no yaml.

Environment (all optional, defaults in parentheses):
  LOGOS_BENCH_GW_URL           (http://localhost:18081)  gateway base URL (Traefik)
  LOGOS_BENCH_GW_UPSTREAM_URL  (http://localhost:9100)   fake cloud upstream, direct
  LOGOS_BENCH_GW_API_KEY       (lg-bench-gw-0000)
  LOGOS_BENCH_GW_MODEL         (bench-cloud-model)
  LOGOS_BENCH_COMPOSE_FILE     (docker-compose.dev.yaml, relative to the
                                logos/ repo root)
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

import httpx

_HERE = Path(__file__).resolve().parent
_REPO_LOGOS = _HERE.parents[1]  # .../logos


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def compose_file() -> Path:
    rel = os.environ.get("LOGOS_BENCH_COMPOSE_FILE", "docker-compose.dev.yaml")
    return (_REPO_LOGOS / rel).resolve()


def webservice_containers(path: Optional[Path] = None) -> List[str]:
    """Ids of the *running* logos-webservice replicas.

    --status=running, not every container compose knows about: a replica that
    crashed and is waiting on `restart: unless-stopped` still shows up in a
    plain `ps -q`, and both callers here care about replicas actually serving
    — the failover leg must not kill "one of two" and take out the only live
    one, and the concurrency ramp sizes its steps from how much admission
    capacity is really behind Traefik.
    """
    out = subprocess.run(
        ["docker", "compose", "-f", str(path or compose_file()), "ps", "-q", "--status=running", "logos-webservice"],
        cwd=str(_REPO_LOGOS),
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


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
    held_ms: float = 0.0


async def stream_chat_completion(
    client: httpx.AsyncClient,
    url: str,
    headers: Dict[str, str],
    on_open: Optional[Callable[[], Awaitable[None]]] = None,
    on_close: Optional[Callable[[], None]] = None,
) -> RequestResult:
    """One streaming POST /v1/chat/completions, consumed to the end.

    A held-open stream is what actually occupies a gateway executor-pool
    slot — a client that stopped at the first chunk would under-count
    concurrency held, not model it.

    ``on_open`` is awaited once the first byte of a 2xx response has arrived,
    i.e. exactly when the gateway has admitted this stream and is writing to
    it. Awaiting inside the read loop stops this client from draining the
    response, so the stream — and the executor slot behind it — stays held
    for as long as the callback takes to return. The concurrency leg uses
    that to keep every stream of a step open until the whole step has been
    admitted; the time spent there is reported as ``held_ms`` and excluded
    from ``total_ms``, which would otherwise measure the benchmark's own
    barrier rather than the gateway.

    ``on_close`` runs once the request is over, however it ended (success,
    error status, transport failure), so a caller counting streams in flight
    cannot leak a slot.
    """
    t0 = time.perf_counter()
    ttfb_ms: Optional[float] = None
    held_ms = 0.0
    try:
        async with client.stream("POST", url, headers=headers, json=chat_payload(stream=True)) as resp:
            status = resp.status_code
            ok = 200 <= status < 300
            async for _chunk in resp.aiter_bytes():
                if ttfb_ms is None:
                    ttfb_ms = (time.perf_counter() - t0) * 1000.0
                    if ok and on_open is not None:
                        hold_start = time.perf_counter()
                        await on_open()
                        held_ms = (time.perf_counter() - hold_start) * 1000.0
            total_ms = (time.perf_counter() - t0) * 1000.0 - held_ms
            return RequestResult(
                ok=ok,
                status_code=status,
                ttfb_ms=ttfb_ms,
                total_ms=total_ms,
                error=None if ok else f"HTTP {status}",
                held_ms=held_ms,
            )
    except Exception as exc:  # noqa: BLE001 — any transport failure is a benchmark data point, not a crash
        total_ms = (time.perf_counter() - t0) * 1000.0 - held_ms
        return RequestResult(
            ok=False, status_code=None, ttfb_ms=ttfb_ms, total_ms=total_ms, error=repr(exc), held_ms=held_ms
        )
    finally:
        if on_close is not None:
            on_close()


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
