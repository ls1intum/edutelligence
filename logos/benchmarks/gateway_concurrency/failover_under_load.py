"""Failover-under-load leg: kill one webservice replica mid-run under real
concurrent streaming load, not the light polling
``scripts/gateway-failover-demo.sh`` uses for its quick manual/ops check.

Requires >=2 ``logos-webservice`` containers already running under the
target compose file (this script does not own the stack's lifecycle, same
philosophy as ``e2e/tests/conftest.py`` — start it yourself first).

A fixed number of workers keep ``concurrency`` streaming requests in flight
for the whole run (each finishes and immediately starts another), one
replica is killed partway through, and every request is classified:
  - ok: HTTP 2xx
  - connectivity failure: connection error/timeout or HTTP 5xx — the only
    outcomes a live replica behind Traefik should not otherwise produce
  - other failure: any other non-2xx (would indicate a real bug, not a
    failover problem, given the seeded key is valid)

Environment (all optional, defaults in parentheses):
  LOGOS_BENCH_GW_FAILOVER_CONCURRENCY  (32)
  LOGOS_BENCH_GW_FAILOVER_DURATION_S   (30)
  LOGOS_BENCH_GW_FAILOVER_KILL_AFTER_S (10)
  LOGOS_BENCH_COMPOSE_FILE             (docker-compose.dev.yaml, relative to
                                         the logos/ repo root)
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List

import gateway_client as gw
import httpx

_HERE = Path(__file__).resolve().parent
_REPO_LOGOS = _HERE.parents[1]  # .../logos


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)))


def _compose_file() -> Path:
    rel = os.environ.get("LOGOS_BENCH_COMPOSE_FILE", "docker-compose.dev.yaml")
    return (_REPO_LOGOS / rel).resolve()


def _webservice_containers(compose_file: Path) -> List[str]:
    out = subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "ps", "-q", "logos-webservice"],
        cwd=str(_REPO_LOGOS),
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def _classify(results: List[gw.RequestResult]) -> Dict[str, Any]:
    ok = [r for r in results if r.ok]
    connectivity_failed = [r for r in results if not r.ok and (r.status_code is None or r.status_code >= 500)]
    other_failed = [r for r in results if not r.ok and r.status_code is not None and r.status_code < 500]
    max_total_ms = max((r.total_ms for r in results), default=0.0)
    return {
        "total": len(results),
        "ok": len(ok),
        "connectivity_failures": len(connectivity_failed),
        "other_failures": len(other_failed),
        "max_total_ms": max_total_ms,
        "connectivity_failure_samples": sorted({r.error for r in connectivity_failed if r.error})[:5],
    }


async def _worker(client: httpx.AsyncClient, url: str, headers: Dict[str, str], deadline: float, out: List) -> None:
    while time.monotonic() < deadline:
        out.append(await gw.stream_chat_completion(client, url, headers))


async def run() -> Dict[str, Any]:
    compose_file = _compose_file()
    containers = _webservice_containers(compose_file)
    if len(containers) < 2:
        raise RuntimeError(
            f"need >=2 logos-webservice replicas running under {compose_file} (found {len(containers)}). "
            f"Start with: docker compose -f {compose_file} up -d --scale logos-webservice=2"
        )
    kill_target = containers[0]

    concurrency = _env_int("LOGOS_BENCH_GW_FAILOVER_CONCURRENCY", 32)
    duration_s = _env_int("LOGOS_BENCH_GW_FAILOVER_DURATION_S", 30)
    kill_after_s = _env_int("LOGOS_BENCH_GW_FAILOVER_KILL_AFTER_S", 10)

    url = f"{gw.gateway_url()}/v1/chat/completions"
    headers = gw.gateway_headers()
    results: List[gw.RequestResult] = []

    print(
        f"  [failover] {concurrency} concurrent streams for {duration_s}s; "
        f"killing {kill_target[:12]} at t={kill_after_s}s"
    )

    limits = httpx.Limits(max_connections=concurrency + 10, max_keepalive_connections=concurrency + 10)
    timeout = httpx.Timeout(60.0, connect=10.0)
    start = time.monotonic()
    deadline = start + duration_s
    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        workers = [asyncio.create_task(_worker(client, url, headers, deadline, results)) for _ in range(concurrency)]

        async def _kill_at(delay: float) -> None:
            await asyncio.sleep(delay)
            print(f"  [failover] killing {kill_target[:12]} ...")
            subprocess.run(["docker", "kill", kill_target], check=True, capture_output=True)

        await asyncio.gather(*workers, _kill_at(kill_after_s))

    summary = _classify(results)
    summary["killed_container"] = kill_target[:12]
    summary["concurrency"] = concurrency
    summary["duration_s"] = duration_s
    summary["kill_after_s"] = kill_after_s
    summary["no_visible_impact"] = summary["connectivity_failures"] == 0
    print(
        f"  [failover] total={summary['total']} ok={summary['ok']} "
        f"connectivity_failures={summary['connectivity_failures']} other_failures={summary['other_failures']}"
    )
    return summary


if __name__ == "__main__":  # pragma: no cover
    import json

    print(json.dumps(asyncio.run(run()), indent=2))
