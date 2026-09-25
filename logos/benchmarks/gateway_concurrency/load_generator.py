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

Environment (all optional, defaults in parentheses):
  LOGOS_BENCH_GW_STEPS             (8,16,32,48,64,96,128,192,256)
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


def _steps() -> List[int]:
    raw = os.environ.get("LOGOS_BENCH_GW_STEPS", "8,16,32,48,64,96,128,192,256")
    return [int(s) for s in raw.split(",") if s.strip()]


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

    step_results: List[Dict[str, Any]] = []
    onset_concurrency = None
    remaining_after_onset = steps_past_limit

    limits = httpx.Limits(max_connections=1000, max_keepalive_connections=1000)
    timeout = httpx.Timeout(120.0, connect=10.0)
    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        for n in _steps():
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
            "approx_admission_ceiling": configured_max_size + configured_queue,
        },
    }


if __name__ == "__main__":  # pragma: no cover
    import json

    print(json.dumps(asyncio.run(run()), indent=2))
