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
from typing import Any, Dict, List, Optional, Tuple

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
    sse_events: int = 0
    # None for non-streaming calls; False marks a 2xx response whose body
    # stopped before the terminal event, which is a failed completion no
    # matter what the status line said.
    stream_complete: Optional[bool] = None


_SSE_DONE = "[DONE]"


def _sse_events(buffer: str) -> Tuple[List[str], str]:
    """Split a decoded buffer into complete SSE events plus the leftover.

    Events are separated by a blank line and a chunk can cut one anywhere,
    so only whole events are returned; the tail stays in the buffer for the
    next chunk. Without this, a terminal event split across two chunks reads
    as a truncated stream.
    """
    normalized = buffer.replace("\r\n", "\n")
    parts = normalized.split("\n\n")
    return parts[:-1], parts[-1]


def _is_done(event: str) -> bool:
    return any(line.startswith("data:") and line[len("data:") :].strip() == _SSE_DONE for line in event.split("\n"))


async def stream_chat_completion(client: httpx.AsyncClient, url: str, headers: Dict[str, str]) -> RequestResult:
    """One streaming POST /v1/chat/completions, consumed to the end.

    A held-open stream is what actually occupies a gateway executor-pool
    slot — a client that stopped at the first chunk would under-count
    concurrency held, not model it.

    Success needs the terminal ``data: [DONE]`` event, not just a 2xx status.
    The status line is written before the completion is relayed, so a stream
    cut off midway — which is exactly what killing a replica under load
    produces — still arrives as ``HTTP 200``; counting that as ok would let
    the failover leg report no visible impact for a truncated answer.
    """
    t0 = time.perf_counter()
    ttfb_ms: Optional[float] = None
    buffer = ""
    events = 0
    saw_done = False
    try:
        async with client.stream("POST", url, headers=headers, json=chat_payload(stream=True)) as resp:
            status = resp.status_code
            http_ok = 200 <= status < 300
            async for chunk in resp.aiter_bytes():
                if ttfb_ms is None:
                    ttfb_ms = (time.perf_counter() - t0) * 1000.0
                if not http_ok:
                    continue  # drain the error body; it is not SSE
                buffer += chunk.decode("utf-8", errors="replace")
                complete, buffer = _sse_events(buffer)
                for event in complete:
                    if not event.strip():
                        continue
                    events += 1
                    if _is_done(event):
                        saw_done = True
            total_ms = (time.perf_counter() - t0) * 1000.0
            if not http_ok:
                error = f"HTTP {status}"
            elif not saw_done:
                error = f"stream ended without {_SSE_DONE} after {events} event(s)"
            else:
                error = None
            return RequestResult(
                ok=http_ok and saw_done,
                status_code=status,
                ttfb_ms=ttfb_ms,
                total_ms=total_ms,
                error=error,
                sse_events=events,
                stream_complete=saw_done,
            )
    except Exception as exc:  # noqa: BLE001 — any transport failure is a benchmark data point, not a crash
        total_ms = (time.perf_counter() - t0) * 1000.0
        return RequestResult(
            ok=False,
            status_code=None,
            ttfb_ms=ttfb_ms,
            total_ms=total_ms,
            error=repr(exc),
            sse_events=events,
            stream_complete=False,
        )


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


async def arm_upstream_step(client: httpx.AsyncClient, target: int, hold_timeout_s: float) -> None:
    """Arm the fake upstream's barrier for the next concurrency step.

    Measuring overlap at the upstream rather than in this process is the
    point: a gateway relay task lives exactly as long as the upstream
    response it is pumping, whereas a paused client proves only that httpx
    stopped reading — the gateway may already have buffered the whole small
    response and released the slot.
    """
    resp = await client.post(
        f"{upstream_url()}/_bench/step",
        json={"target": target, "hold_timeout_s": hold_timeout_s},
        timeout=10.0,
    )
    resp.raise_for_status()


async def upstream_step_stats(client: httpx.AsyncClient) -> Dict[str, Any]:
    resp = await client.get(f"{upstream_url()}/_bench/stats", timeout=10.0)
    resp.raise_for_status()
    return resp.json()


def gateway_headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"}


def upstream_headers() -> Dict[str, str]:
    return {"Content-Type": "application/json"}
