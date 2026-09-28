"""Concurrency-ramp leg: how many held-open streaming requests the gateway
tolerates, where the limit comes from, and its behaviour at the limit.

Ramps concurrency in steps; each step fires ``n`` streaming
``POST /v1/chat/completions`` requests at once (``asyncio.gather``) and waits
for all of them to finish or fail. Stops a fixed number of steps after the
first one whose failure rate crosses the threshold — far enough to see
*how* it degrades (graceful backpressure vs. hangs/crashes), not so far that
a runaway client outlives the point of the test.

The known static ceiling (Spring's task-executor pool backing the streaming
response body: ``spring.task.execution.pool.max-size`` + ``queue-capacity``,
see ``application.properties``) is reported alongside the observed onset so
a reader can tell "matches the configured limit" from "something else caps
it first" without re-deriving the config by hand.

Steps are derived from that ceiling rather than hard-coded, because a fixed
ramp silently stops measuring anything the moment the stack changes: the
previous 8..256 default topped out below a *single* replica's admission
ceiling (64 + 200), and CI runs two — so the leg could never reach the onset
it exists to find. The default ramp now runs to 1.5x the aggregate ceiling of
the replicas actually behind Traefik.

Environment (all optional, defaults in parentheses):
  LOGOS_BENCH_GW_STEPS             (derived — see above; a comma-separated
                                    list overrides the derivation entirely)
  LOGOS_BENCH_GW_REPLICAS          (counted via docker compose; set this when
                                    the gateway under test is not the local
                                    compose stack)
  LOGOS_BENCH_GW_FAIL_THRESHOLD    (0.05)  fraction of a step's requests that
                                    may fail before the step counts as "past
                                    the limit"
  LOGOS_BENCH_GW_STEPS_PAST_LIMIT  (2)     how many more steps to run once
                                    a step has crossed the threshold
  LOGOS_GATEWAY_ASYNC_MAX_SIZE          (64)   informational only — must match
  LOGOS_GATEWAY_ASYNC_QUEUE_CAPACITY    (200)  the webservice's own config to
                                                mean anything in the report
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List

import gateway_client as gw
import httpx
from stats import summarize


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)))


def _env_float(name: str, default: float) -> float:
    return float(os.environ.get(name, str(default)))


def _replica_count() -> int:
    """Replicas serving the gateway, for sizing the ramp.

    Falls back to 1 rather than failing: this leg is also useful against a
    gateway that is not the local compose stack (no docker reachable, or a
    remote host), and there an under-sized ramp is a worse outcome than a
    ceiling reported for one replica — LOGOS_BENCH_GW_REPLICAS covers that
    case explicitly.
    """
    override = os.environ.get("LOGOS_BENCH_GW_REPLICAS")
    if override:
        return max(1, int(override))
    try:
        return len(gw.webservice_containers()) or 1
    except Exception:  # noqa: BLE001 — docker absent, not the local stack, ...
        return 1


def _steps(aggregate_ceiling: int) -> List[int]:
    raw = os.environ.get("LOGOS_BENCH_GW_STEPS")
    if raw:
        return [int(s) for s in raw.split(",") if s.strip()]
    # Up to 1.5x: the ceiling is approximate (max-size + queue-capacity is
    # what the executor admits, not counting requests already past it), so a
    # ramp that stops exactly at 1.0x can miss the onset by a handful of
    # requests. The step loop stops two steps after the onset anyway, so the
    # top of this list is only reached when nothing broke before it.
    fractions = (0.05, 0.125, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5)
    return sorted({max(8, round(aggregate_ceiling * f)) for f in fractions})


async def _run_step(client: httpx.AsyncClient, url: str, headers: Dict[str, str], n: int) -> Dict[str, Any]:
    results = await asyncio.gather(*(gw.stream_chat_completion(client, url, headers) for _ in range(n)))
    ok = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    fail_rate = len(failed) / n if n else 0.0
    error_samples = sorted({r.error for r in failed if r.error})[:5]
    return {
        "concurrency": n,
        "ok": len(ok),
        "failed": len(failed),
        "fail_rate": fail_rate,
        "ttfb_ms": summarize([r.ttfb_ms for r in ok if r.ttfb_ms is not None]),
        "total_ms": summarize([r.total_ms for r in results]),
        "error_samples": error_samples,
    }


async def run() -> Dict[str, Any]:
    url = f"{gw.gateway_url()}/v1/chat/completions"
    headers = gw.gateway_headers()
    fail_threshold = _env_float("LOGOS_BENCH_GW_FAIL_THRESHOLD", 0.05)
    steps_past_limit = _env_int("LOGOS_BENCH_GW_STEPS_PAST_LIMIT", 2)
    configured_max_size = _env_int("LOGOS_GATEWAY_ASYNC_MAX_SIZE", 64)
    configured_queue = _env_int("LOGOS_GATEWAY_ASYNC_QUEUE_CAPACITY", 200)
    replicas = _replica_count()
    per_replica_ceiling = configured_max_size + configured_queue
    aggregate_ceiling = per_replica_ceiling * replicas
    steps = _steps(aggregate_ceiling)
    print(
        f"  [concurrency] {replicas} replica(s) x (max-size {configured_max_size} + queue "
        f"{configured_queue}) = ~{aggregate_ceiling} admitted; steps {steps}"
    )

    step_results: List[Dict[str, Any]] = []
    onset_concurrency = None
    remaining_after_onset = steps_past_limit

    # Sized off the ramp, not a fixed 1000: a pool smaller than the top step
    # would queue requests in the client and the leg would measure httpx
    # instead of the gateway — and derived steps grow with the replica count.
    pool = max(1000, steps[-1] + 100)
    limits = httpx.Limits(max_connections=pool, max_keepalive_connections=pool)
    timeout = httpx.Timeout(120.0, connect=10.0)
    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        for n in steps:
            print(f"  [concurrency] step n={n} ...")
            step = await _run_step(client, url, headers, n)
            step_results.append(step)
            print(
                f"    ok={step['ok']} failed={step['failed']} fail_rate={step['fail_rate']:.1%} "
                f"ttfb p50={step['ttfb_ms'].get('p50_ms', 0):.0f}ms total p50={step['total_ms'].get('p50_ms', 0):.0f}ms"
            )
            if onset_concurrency is None and step["fail_rate"] > fail_threshold:
                onset_concurrency = n
                print(f"  [concurrency] onset of failures at n={n} (fail_rate > {fail_threshold:.0%})")
            elif onset_concurrency is not None:
                remaining_after_onset -= 1
                if remaining_after_onset <= 0:
                    break

    return {
        "steps": step_results,
        "onset_concurrency": onset_concurrency,
        "fail_threshold": fail_threshold,
        "configured_ceiling": {
            "spring_task_execution_pool_max_size": configured_max_size,
            "spring_task_execution_pool_queue_capacity": configured_queue,
            "replicas": replicas,
            "approx_admission_ceiling_per_replica": per_replica_ceiling,
            "approx_admission_ceiling": aggregate_ceiling,
        },
    }


if __name__ == "__main__":  # pragma: no cover
    import json

    print(json.dumps(asyncio.run(run()), indent=2))
