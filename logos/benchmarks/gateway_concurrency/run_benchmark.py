"""Director of the gateway concurrency benchmark.

Unlike ``per_request_overhead``, this benchmark does **not** own the stack's
lifecycle — bringing up a Spring Boot service (and, for the failover leg,
2+ replicas behind Traefik) is squarely a `docker compose` job already
covered by ``docker-compose.dev.yaml`` / ``docker-compose.yaml`` and
``scripts/gateway-failover-demo.sh``; duplicating that as raw subprocesses
here would be a second, divergent way to do the same thing. Same philosophy
as ``e2e/tests/conftest.py``: start the stack yourself first, this script
attaches to it.

What this script *does* own: the fake cloud upstream (a throwaway process,
not part of the deployable stack) and the three measurement legs.

Prerequisites:
  1. Postgres migrated (Liquibase) and seeded: `psql "$DB_URL" -f seed.sql`
  2. The webservice stack up, e.g.:
     docker compose -f docker-compose.dev.yaml up -d --build --scale logos-webservice=2
  3. This script started from logos/benchmarks/gateway_concurrency/

Environment: see gateway_client.py, load_generator.py, latency_diff.py,
failover_under_load.py for the full list. Additionally:
  LOGOS_BENCH_GW_OUTPUT      (./reports)
  LOGOS_BENCH_GW_SKIP_FAILOVER  (set to "1" to skip the failover leg even
                                 when 2+ replicas are up — e.g. a quick local
                                 run against a single instance)
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import failover_under_load  # noqa: E402
import gateway_client as gw  # noqa: E402
import latency_diff  # noqa: E402
import load_generator  # noqa: E402
from report import write_reports  # noqa: E402


def _wait_http(url: str, what: str, timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    last_err = ""
    with httpx.Client() as probe:
        while time.monotonic() < deadline:
            try:
                probe.get(url, timeout=5.0)
                print(f"  [{what}] up")
                return
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)
                time.sleep(1.0)
    raise RuntimeError(f"{what} did not come up within {timeout_s:.0f}s (last: {last_err})")


def _check_gateway_reachable() -> None:
    """Allowlist, not a denylist: Traefik answers its own 404 as soon as the
    router exists but before any webservice replica is ready to take traffic
    (labels register at container start, well before the JVM finishes
    booting + migrating) — a "< 500" check would mistake that transient 404
    for a real webservice response.
    """
    url = f"{gw.gateway_url()}/v1/models"
    try:
        with httpx.Client() as probe:
            resp = probe.get(url, headers=gw.gateway_headers(), timeout=10.0)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"gateway not reachable at {gw.gateway_url()} ({exc}). Bring up the stack first, e.g.:\n"
            f"  docker compose -f docker-compose.dev.yaml up -d --build --scale logos-webservice=2"
        ) from exc
    if resp.status_code not in (200, 401, 403):
        raise RuntimeError(
            f"gateway at {gw.gateway_url()} answered HTTP {resp.status_code}, not a webservice response "
            f"(200/401/403) — is the stack fully up and seeded?"
        )
    print(f"  [gateway] reachable at {gw.gateway_url()} (HTTP {resp.status_code})")


def run() -> int:
    out_dir = Path(os.environ.get("LOGOS_BENCH_GW_OUTPUT", str(_HERE / "reports")))
    upstream_port = int(os.environ.get("LOGOS_BENCH_GW_UPSTREAM_PORT", "9100"))
    skip_failover = os.environ.get("LOGOS_BENCH_GW_SKIP_FAILOVER") == "1"

    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "fake_cloud_upstream.log"
    log_path.write_text("")

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["LOGOS_BENCH_GW_UPSTREAM_PORT"] = str(upstream_port)

    upstream_proc: Optional[subprocess.Popen] = None
    try:
        _check_gateway_reachable()

        upstream_proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "fake_cloud_upstream:app",
                "--app-dir",
                str(_HERE),
                "--host",
                "0.0.0.0",
                "--port",
                str(upstream_port),
                "--no-access-log",
                "--log-level",
                "warning",
            ],
            env=env,
            cwd=str(_HERE),
            stdout=open(log_path, "ab"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        _wait_http(f"{gw.upstream_url()}/health", "fake-cloud-upstream")

        import asyncio

        print("== latency diff ==")
        latency_result: Dict[str, Any] = asyncio.run(latency_diff.run())

        print("== concurrency ramp ==")
        concurrency_result: Dict[str, Any] = asyncio.run(load_generator.run())

        failover_result: Optional[Dict[str, Any]]
        if skip_failover:
            print("== failover (skipped: LOGOS_BENCH_GW_SKIP_FAILOVER=1) ==")
            failover_result = {"skipped": True, "reason": "LOGOS_BENCH_GW_SKIP_FAILOVER=1"}
        else:
            print("== failover under load ==")
            try:
                failover_result = asyncio.run(failover_under_load.run())
            except RuntimeError as exc:
                print(f"  [failover] skipped: {exc}")
                failover_result = None

        result = {
            "latency": latency_result,
            "concurrency": concurrency_result,
            "failover": failover_result,
            "env": {
                "gateway_url": gw.gateway_url(),
                "upstream_url": gw.upstream_url(),
                "model": gw.model_name(),
            },
        }
        paths = write_reports(result, str(out_dir))
        print(f"\n  report: {paths['md']}")
        return 0
    finally:
        if upstream_proc is not None and upstream_proc.poll() is None:
            try:
                os.killpg(os.getpgid(upstream_proc.pid), signal.SIGTERM)
                upstream_proc.wait(timeout=10)
            except (ProcessLookupError, PermissionError, subprocess.TimeoutExpired):
                try:
                    os.killpg(os.getpgid(upstream_proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass


if __name__ == "__main__":
    sys.exit(run())
