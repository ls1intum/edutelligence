"""Director of the per-request overhead benchmark (issue #980).

Process layout (all on 127.0.0.1):

  postgres:17            pre-existing Docker container (Liquibase migration
                         + seed.sql must have been applied first)
  mock lane              uvicorn mock_lane:app on LOGOS_BENCH_LANE_PORT
  worker under test      worker_under_test.py (real LaneManager + real
                         LogosBridgeClient, one warm FakeLaneHandle)
  orchestrator           uvicorn logos.main:app on LOGOS_BENCH_PORT

Protocol:
  1. wait until /internal/provider_status reports the provider connected
  2. warmup: WARMUP Logos-path requests (not measured)
  3. BLOCKS x ( SAMPLES_LOGOS measured Logos requests, each followed by the
     perf-trace fetch, then SAMPLES_DIRECT measured direct-baseline requests)
     — interleaved so common-mode runner drift cancels in the median
  4. report: overhead = median(Logos) - median(direct), phase table, verdict

Environment (all optional, defaults in parentheses):
  LOGOS_BENCH_DB_URL          (postgresql://postgres:root@127.0.0.1:5433/logosdb)
  LOGOS_BENCH_PORT            (8090)  orchestrator HTTP port
  LOGOS_BENCH_LANE_PORT       (11436) mock lane port
  LOGOS_BENCH_MODEL           (bench-local-model)
  LOGOS_BENCH_SHARED_KEY      (lg-worker-shared-0000)
  LOGOS_BENCH_API_KEY         (lg-bench-0000)
  LOGOS_BENCH_INTERNAL_SECRET (bench-internal-secret)
  LOGOS_BENCH_WARMUP          (50)
  LOGOS_BENCH_SAMPLES_LOGOS   (100)
  LOGOS_BENCH_SAMPLES_DIRECT  (50)
  LOGOS_BENCH_BLOCKS          (4)
  LOGOS_BENCH_OUTPUT          (logos/benchmarks/per_request_overhead/reports)
  LOGOS_BENCH_NO_PERF_TRACE   (set to "1" to disable perf tracing)
  HF_HOME / HF_HUB_OFFLINE    (inherited; see CI workflow for the HF cache)
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[2]  # .../edutelligence
_ORCH = _HERE.parents[1] / "logos-orchestrator"  # .../logos/logos-orchestrator

sys.path.insert(0, str(_HERE))

from report import FAIL_NS, GOAL_NS, verdict, write_reports  # noqa: E402
from stats import merge_phase_totals, overhead_ns, summarize  # noqa: E402


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    return int(_env(name, str(default)))


class _Proc:
    """A supervised subprocess with a short log tail on failure."""

    def __init__(self, name: str, argv: List[str], env: Dict[str, str], cwd: str, log: Path) -> None:
        self.name = name
        self.log = log
        self.proc = subprocess.Popen(
            argv,
            env=env,
            cwd=cwd,
            stdout=open(log, "ab"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    def alive(self) -> bool:
        return self.proc.poll() is None

    def stop(self) -> None:
        if not self.alive():
            return
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    def tail(self, lines: int = 40) -> str:
        try:
            content = self.log.read_text(errors="replace").splitlines()
            return "\n".join(content[-lines:])
        except OSError:
            return "<no log>"


def _wait_http(client: httpx.Client, url: str, what: str, timeout_s: float = 120.0) -> None:
    deadline = time.monotonic() + timeout_s
    last_err = ""
    while time.monotonic() < deadline:
        try:
            client.get(url, timeout=5.0)
            print(f"  [{what}] up")
            return
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            time.sleep(1.0)
    raise RuntimeError(f"{what} did not come up within {timeout_s:.0f}s (last: {last_err})")


def _wait_worker_connected(client: httpx.Client, orch: str, secret: str, provider_id: int, timeout_s: float = 180.0) -> None:
    """Poll /internal/provider_status until the bench worker is connected."""
    headers = {"Authorization": f"Bearer {secret}"}
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            resp = client.get(f"{orch}/internal/provider_status", headers=headers, timeout=5.0)
            if resp.status_code == 200:
                for provider in resp.json().get("providers", []):
                    if int(provider.get("provider_id", 0)) == provider_id and provider.get("connected"):
                        print(f"  [worker] connected (worker_id={provider.get('name')})")
                        return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1.0)
    raise RuntimeError(f"worker never connected to the orchestrator within {timeout_s:.0f}s")


def _bench_payload(model: str) -> Dict[str, Any]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": "Benchmark probe: reply with a short fixed answer."}],
        "stream": False,
    }


def run() -> int:
    db_url = _env("LOGOS_BENCH_DB_URL", "postgresql://postgres:root@127.0.0.1:5433/logosdb")
    orch_port = _env_int("LOGOS_BENCH_PORT", 8090)
    lane_port = _env_int("LOGOS_BENCH_LANE_PORT", 11436)
    model = _env("LOGOS_BENCH_MODEL", "bench-local-model")
    shared_key = _env("LOGOS_BENCH_SHARED_KEY", "lg-worker-shared-0000")
    api_key = _env("LOGOS_BENCH_API_KEY", "lg-bench-0000")
    secret = _env("LOGOS_BENCH_INTERNAL_SECRET", "bench-internal-secret")
    warmup = _env_int("LOGOS_BENCH_WARMUP", 50)
    samples_logos = _env_int("LOGOS_BENCH_SAMPLES_LOGOS", 100)
    samples_direct = _env_int("LOGOS_BENCH_SAMPLES_DIRECT", 50)
    blocks = _env_int("LOGOS_BENCH_BLOCKS", 4)
    out_dir = Path(_env("LOGOS_BENCH_OUTPUT", str(_HERE / "reports")))
    perf_enabled = _env("LOGOS_BENCH_NO_PERF_TRACE", "0") != "1"

    python = sys.executable or "python3"
    venv_python = _ORCH / ".venv" / "bin" / "python"
    if venv_python.exists():
        python = str(venv_python)

    orch = f"http://127.0.0.1:{orch_port}"
    lane = f"http://127.0.0.1:{lane_port}"

    work_dir = out_dir / "run"
    work_dir.mkdir(parents=True, exist_ok=True)
    for log_name in ("mock_lane", "worker", "orchestrator"):
        (work_dir / f"{log_name}.log").write_text("")

    base_env = dict(os.environ)
    base_env.update(
        {
            "PYTHONUNBUFFERED": "1",
            "LOGOS_BENCH_MODEL": model,
            "LOGOS_BENCH_SHARED_KEY": shared_key,
            "LOGOS_BENCH_LANE_PORT": str(lane_port),
            "LOGOS_BENCH_ORCHESTRATOR_URL": orch,
            "LOGOS_WORKER_PERF_TRACE": "1" if perf_enabled else "0",
            "HF_HUB_OFFLINE": os.environ.get("HF_HUB_OFFLINE", ""),
        }
    )

    procs: List[_Proc] = []
    result: Optional[Dict[str, Any]] = None
    try:
        # -- 1. mock lane -----------------------------------------------------
        mock = _Proc(
            "mock-lane",
            [python, "-m", "uvicorn", "mock_lane:app", "--app-dir", str(_HERE),
             "--host", "127.0.0.1", "--port", str(lane_port), "--no-access-log", "--log-level", "warning"],
            base_env, str(_HERE), work_dir / "mock_lane.log",
        )
        procs.append(mock)
        with httpx.Client() as probe:
            _wait_http(probe, f"{lane}/health", "mock-lane", 60.0)

        # -- 2. worker under test --------------------------------------------
        worker = _Proc(
            "worker",
            [python, str(_HERE / "worker_under_test.py")],
            base_env, str(_HERE), work_dir / "worker.log",
        )
        procs.append(worker)

        # -- 3. orchestrator --------------------------------------------------
        orch_env = dict(base_env)
        orch_env.update(
            {
                # src/ holds the non-packaged grpclocal package (same layout as
                # the Dockerfile: generated pb2 files live next to the proto).
                "PYTHONPATH": str(_ORCH / "src") + os.pathsep + orch_env.get("PYTHONPATH", ""),
                "LOGOS_DB_URL": db_url,
                "LOGOS_NODE_DEV_ALLOW_INSECURE_HTTP": "true",
                "LOGOS_PERF_TRACE": "1" if perf_enabled else "0",
                "LOGOS_INTERNAL_SECRET": secret,
                "LOGOS_CAPACITY_PLANNER_ENABLED": "false",
            }
        )
        orchestrator = _Proc(
            "orchestrator",
            [python, "-m", "uvicorn", "logos.main:app", "--host", "127.0.0.1",
             "--port", str(orch_port), "--no-access-log", "--log-level", "warning"],
            orch_env, str(_ORCH), work_dir / "orchestrator.log",
        )
        procs.append(orchestrator)
        with httpx.Client() as probe:
            _wait_http(probe, f"{orch}/docs", "orchestrator", 300.0)  # startup incl. eager classifier load
        with httpx.Client() as probe:
            _wait_worker_connected(probe, orch, secret, provider_id=1)

        # -- 4. measurement ---------------------------------------------------
        payload = _bench_payload(model)
        headers_logos = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        headers_trace = {"Authorization": f"Bearer {secret}"}

        logos_ns: List[int] = []
        direct_ns: List[int] = []
        traces: List[Dict[str, Any]] = []

        def _timed_post(client: httpx.Client, url: str, headers: Dict[str, str]) -> httpx.Response:
            t0 = time.perf_counter_ns()
            resp = client.post(url, headers=headers, json=payload)
            t1 = time.perf_counter_ns()
            return resp, t1 - t0

        with httpx.Client(timeout=httpx.Timeout(60.0, connect=5.0)) as client:
            # warmup: pools, connection pools, name caches
            for i in range(warmup):
                resp, _ = _timed_post(client, f"{orch}/v1/chat/completions", headers_logos)
                if resp.status_code != 200:
                    raise RuntimeError(f"warmup request {i} failed: {resp.status_code} {resp.text[:400]}")
            print(f"  [warmup] {warmup} requests OK")
            client.delete(f"{orch}/internal/perf_trace", headers=headers_trace)  # drop warmup traces

            for block in range(blocks):
                for i in range(samples_logos):
                    resp, dt = _timed_post(client, f"{orch}/v1/chat/completions", headers_logos)
                    if resp.status_code != 200:
                        raise RuntimeError(f"logos request failed: {resp.status_code} {resp.text[:400]}")
                    logos_ns.append(dt)
                    if perf_enabled:
                        request_id = resp.headers.get("X-Request-ID", "")
                        if request_id:
                            trace_resp = client.get(f"{orch}/internal/perf_trace/{request_id}", headers=headers_trace, timeout=5.0)
                            if trace_resp.status_code == 200:
                                traces.append(trace_resp.json())
                for i in range(samples_direct):
                    _, dt = _timed_post(client, f"{lane}/v1/chat/completions", {"Content-Type": "application/json"})
                    direct_ns.append(dt)
                print(f"  [block {block + 1}/{blocks}] logos={len(logos_ns)} direct={len(direct_ns)}")

        # -- 5. report ----------------------------------------------------------
        ov = overhead_ns(logos_ns, direct_ns)
        verdict_str = verdict(ov["overhead_ns"])
        result = {
            "scenario": "logosnode, warm lane, no concurrent requests, non-streaming POST /v1/chat/completions",
            "overhead": ov,
            "summary": {"logos": summarize(logos_ns), "direct": summarize(direct_ns)},
            "phases": merge_phase_totals([t.get("phases", {}) for t in traces]),
            "n_traces": len(traces),
            "verdict": verdict_str,
            "goal_ns": GOAL_NS,
            "fail_ns": FAIL_NS,
            "env": {
                "python": python,
                "orchestrator": orch,
                "mock_lane": lane,
                "db_url_host": db_url.split("@")[-1] if "@" in db_url else db_url,
                "perf_trace": perf_enabled,
            },
        }
        paths = write_reports(result, str(out_dir))
        print(f"\n  verdict: {verdict_str} — overhead p50 = {ov['overhead_ns'] / 1000.0:,.1f} µs "
              f"(goal < {GOAL_NS / 1000.0:,.0f} µs)")
        print(f"  logos p50    = {summarize(logos_ns)['p50_ns'] / 1000.0:,.1f} µs (n={len(logos_ns)})")
        print(f"  direct p50   = {summarize(direct_ns)['p50_ns'] / 1000.0:,.1f} µs (n={len(direct_ns)})")
        print(f"  report: {paths['md']}")
        return 0
    finally:
        for proc in reversed(procs):
            proc.stop()
        for proc in procs:
            if not proc.alive():
                print(f"  [{proc.name}] exited rc={proc.proc.returncode} — last log lines:")
                for line in proc.tail(25).splitlines():
                    print(f"    {line}")


if __name__ == "__main__":
    sys.exit(run())
