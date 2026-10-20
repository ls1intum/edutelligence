"""Budget-admission leg: admission latency for a key with a budget and history.

The other legs use a key without a budget (see seed.sql), so the gateway
never runs its budget check there, and ``log_entry`` stays empty. This leg
uses the key from ``seed_budget.sql``: an application key with a key budget
limit and a month of direct-cloud history. Every budget-cache miss for that
key runs ``GatewayBudgetService.apiKeyBudgetUsage``, which sums the key's
month through ``log_entry_cost``. Concurrent requests of the same key wait
for that refresh. If the refresh is slow, the requests that arrived during
it finish together, late, and the long queries can starve the connection
pool that authentication needs.

What it measures:

- an idle baseline: sequential requests on the budget key before the load;
- a closed-loop load: ``CONCURRENCY`` workers, each sending non-streaming
  requests back to back for ``DURATION_S`` seconds. The default duration
  spans at least two budget-cache expiries, so the load sees the refresh;
- latency per time window, the status histogram (5xx = pool exhaustion or
  an upstream error), and the slowest requests;
- the budget refresh query itself, run in the database before and after the
  load (``docker exec <db> psql``). The gateway finalizes unpriced history in
  the background, so the "after" figure also shows how far that got.

- the time each request of the load spent in Logos itself, read back from its
  ``log_entry`` row: the whole request (arrival at the controller to the end
  of the response) minus the provider window (provider call to provider
  response). The fake upstream's fixed delay is the provider window, so this
  is the gateway's own cost: authentication, rate limit, budget check,
  reservation and relaying. It excludes the hop through Traefik.

No gate by default. With ``LOGOS_BENCH_GW_BUDGET_LOGOS_P50_MAX_MS`` or
``LOGOS_BENCH_GW_BUDGET_LOGOS_P99_MAX_MS`` set, the report flags a median or
p99 of the time in Logos above it;
``LOGOS_BENCH_GW_BUDGET_FAIL_ON_THRESHOLD=1`` also makes ``run_benchmark.py``
exit non-zero.

Environment (all optional, defaults in parentheses):
  LOGOS_BENCH_GW_BUDGET_API_KEY        (lg-bench-gw-budget-0000)
  LOGOS_BENCH_GW_BUDGET_API_KEY_ID     (502)    for the DB-side query
  LOGOS_BENCH_GW_BUDGET_CONCURRENCY    (16)
  LOGOS_BENCH_GW_BUDGET_DURATION_S     (2 x cache TTL + 10)
  LOGOS_BENCH_GW_BUDGET_BASELINE       (10)     sequential baseline requests
  LOGOS_BENCH_GW_BUDGET_WINDOW_S       (5)      width of a latency window
  LOGOS_BENCH_GW_BUDGET_LOGOS_P50_MAX_MS  (unset)  threshold on the median time in Logos
  LOGOS_BENCH_GW_BUDGET_LOGOS_P99_MAX_MS  (unset)  threshold on the p99 time in Logos
  LOGOS_BENCH_GW_BUDGET_FAIL_ON_THRESHOLD  (unset)  "1" = exit non-zero on a flag
  LOGOS_BENCH_GW_DB_CONTAINER          (logos-db)  Postgres container for the query timing
  LOGOS_GATEWAY_BUDGET_CACHE_TTL_SECONDS  (15)  informational; must match the webservice
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import time
from typing import Any, Dict, List, Optional

import gateway_client as gw
import httpx
from stats import summarize

# The gateway's key usage query (GatewayBudgetService.apiKeyBudgetUsage):
# stored prices summed straight from log_entry, only unpriced rows priced
# through log_entry_cost, plus the in-flight reservations.
_MONTH = (
    "le.timestamp_request >= CAST(date_trunc('month', NOW()) AS DATE)"
    " AND le.timestamp_request < CAST(date_trunc('month', NOW()) AS DATE) + INTERVAL '1 month'"
)
_BUDGET_QUERY = """
SELECT COALESCE((
    SELECT SUM(le.settled_cost_micro_cents)
    FROM log_entry le
    WHERE le.api_key_id = {key_id}
      AND le.cost_finalized
      AND le.result_status IN ('success', 'error', 'timeout')
      AND MONTH
), 0) + COALESCE((
    SELECT SUM(lec.cost_micro_cents)
    FROM log_entry_cost lec
    WHERE lec.log_entry_id IN (
        SELECT le.id
        FROM log_entry le
        WHERE le.api_key_id = {key_id}
          AND le.cost_finalized IS NOT TRUE
          AND le.result_status IN ('success', 'error', 'timeout')
          AND MONTH
    )
), 0) + COALESCE((
    SELECT SUM(le.settled_cost_micro_cents)
    FROM log_entry le
    WHERE le.api_key_id = {key_id}
      AND le.result_status IS NULL
      AND le.request_id LIKE 'gw-%'
      AND le.settled_cost_micro_cents IS NOT NULL
      AND le.settled_cost_micro_cents > 0
      AND MONTH
), 0);
""".replace("MONTH", _MONTH)

_UNFINALIZED_QUERY = """
SELECT COUNT(*) FROM log_entry
WHERE api_key_id = {key_id} AND result_status = 'success' AND NOT cost_finalized;
"""

# Per request of the load: the time in Logos (whole request minus the provider
# window), split into its three parts: admission (arrival to forwarding), the
# call (forwarding to the provider call) and the tail (provider response to
# the end of the response, i.e. delivery to the client and the settle).
_LOGOS_TIME_QUERY = """
WITH r AS (
    SELECT EXTRACT(EPOCH FROM ((le.timestamp_response - le.timestamp_request)
                               - (le.timestamp_provider_response - le.timestamp_provider_call))) * 1000 AS logos_ms,
           EXTRACT(EPOCH FROM (le.timestamp_forwarding - le.timestamp_request)) * 1000 AS admission_ms,
           EXTRACT(EPOCH FROM (le.timestamp_provider_call - le.timestamp_forwarding)) * 1000 AS call_ms,
           EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_provider_response)) * 1000 AS tail_ms
    FROM log_entry le
    WHERE le.api_key_id = {key_id}
      AND le.timestamp_request >= CAST('{since}' AS TIMESTAMPTZ)
      AND le.timestamp_request IS NOT NULL
      AND le.timestamp_forwarding IS NOT NULL
      AND le.timestamp_provider_call IS NOT NULL
      AND le.timestamp_provider_response IS NOT NULL
      AND le.timestamp_response IS NOT NULL
)
SELECT COUNT(*),
       array_to_string(percentile_cont(ARRAY[0.5, 0.95, 0.99]) WITHIN GROUP (ORDER BY logos_ms), ','),
       MAX(logos_ms),
       array_to_string(percentile_cont(ARRAY[0.5, 0.95, 0.99]) WITHIN GROUP (ORDER BY admission_ms), ','),
       MAX(admission_ms),
       array_to_string(percentile_cont(ARRAY[0.5, 0.95, 0.99]) WITHIN GROUP (ORDER BY call_ms), ','),
       MAX(call_ms),
       array_to_string(percentile_cont(ARRAY[0.5, 0.95, 0.99]) WITHIN GROUP (ORDER BY tail_ms), ','),
       MAX(tail_ms)
FROM r;
"""

_TIME_RE = re.compile(r"^Time: ([0-9.]+) ms", re.MULTILINE)


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)))


def _env_float_opt(name: str) -> Optional[float]:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else None


def cache_ttl_s() -> int:
    return _env_int("LOGOS_GATEWAY_BUDGET_CACHE_TTL_SECONDS", 15)


def budget_api_key() -> str:
    return os.environ.get("LOGOS_BENCH_GW_BUDGET_API_KEY", "lg-bench-gw-budget-0000")


def _psql(sql: str, timeout_s: float = 300.0) -> str:
    container = os.environ.get("LOGOS_BENCH_GW_DB_CONTAINER", "logos-db")
    out = subprocess.run(
        ["docker", "exec", "-i", container, "psql", "-U", "postgres", "-d", "logosdb", "-At"],
        input="\\timing on\n" + sql,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=True,
    )
    return out.stdout


def budget_query_snapshot(key_id: int) -> Dict[str, Any]:
    """Time the budget refresh query once, plus the key's unpriced backlog.

    Run directly in the database: the gateway does not expose how long its
    own refresh took, and the database figure is what every waiting request
    pays on a cache miss. Any failure (no docker, other container name) is
    reported, not raised — the HTTP measurements stand on their own.
    """
    try:
        query_out = _psql(_BUDGET_QUERY.format(key_id=key_id))
        times = _TIME_RE.findall(query_out)
        backlog_out = _psql(_UNFINALIZED_QUERY.format(key_id=key_id), timeout_s=60.0)
        backlog_lines = [ln for ln in backlog_out.splitlines() if ln.strip().isdigit()]
        return {
            "query_ms": float(times[0]) if times else None,
            "unfinalized_rows": int(backlog_lines[0]) if backlog_lines else None,
        }
    except Exception as exc:  # noqa: BLE001 — DB timing is optional context
        return {"query_ms": None, "unfinalized_rows": None, "error": repr(exc)[:300]}


def _db_now() -> Optional[str]:
    try:
        lines = [ln for ln in _psql("SELECT now();", timeout_s=30.0).splitlines() if ln and not ln.startswith("Time")]
        return lines[-1].strip() if lines else None
    except Exception:  # noqa: BLE001 — the time-in-Logos figure is then reported as missing
        return None


def logos_time(key_id: int, since: Optional[str]) -> Dict[str, Any]:
    """Percentiles of the time the load's requests spent in Logos (see the module docstring)."""
    if since is None:
        return {"n": 0, "error": "could not read the database clock"}
    try:
        out = _psql(_LOGOS_TIME_QUERY.format(key_id=key_id, since=since), timeout_s=120.0)
        row = next(ln for ln in out.splitlines() if "|" in ln)
        n, logos_pcts, logos_max, adm_pcts, adm_max, call_pcts, call_max, tail_pcts, tail_max = row.split("|")
        if int(n) == 0:
            return {"n": 0}

        def _summary(pcts: str, mx: str) -> Dict[str, float]:
            p50, p95, p99 = (float(v) for v in pcts.split(","))
            return {"p50_ms": p50, "p95_ms": p95, "p99_ms": p99, "max_ms": float(mx)}

        return {
            "n": int(n),
            "logos": _summary(logos_pcts, logos_max),
            "admission": _summary(adm_pcts, adm_max),
            "call": _summary(call_pcts, call_max),
            "tail": _summary(tail_pcts, tail_max),
        }
    except Exception as exc:  # noqa: BLE001 — reported, not raised
        return {"n": 0, "error": repr(exc)[:300]}


async def _worker(
    client: httpx.AsyncClient,
    url: str,
    headers: Dict[str, str],
    t_start: float,
    deadline: float,
    rows: List[Dict[str, Any]],
) -> None:
    while time.perf_counter() < deadline:
        sent_at = time.perf_counter() - t_start
        r = await gw.post_chat_completion(client, url, headers)
        rows.append(
            {
                "sent_at_s": sent_at,
                "total_ms": r.total_ms,
                "status": r.status_code,
                "ok": r.ok,
                "error": r.error,
            }
        )


def _windows(rows: List[Dict[str, Any]], window_s: int, duration_s: int) -> List[Dict[str, Any]]:
    out = []
    for start in range(0, max(duration_s, 1), window_s):
        in_window = [r for r in rows if start <= r["sent_at_s"] < start + window_s]
        ok_ms = [r["total_ms"] for r in in_window if r["ok"]]
        s = summarize(ok_ms)
        out.append(
            {
                "start_s": start,
                "requests": len(in_window),
                "failed": sum(1 for r in in_window if not r["ok"]),
                "p50_ms": s.get("p50_ms", 0.0),
                "p95_ms": s.get("p95_ms", 0.0),
                "max_ms": s.get("max_ms", 0.0),
            }
        )
    return out


async def run() -> Dict[str, Any]:
    concurrency = _env_int("LOGOS_BENCH_GW_BUDGET_CONCURRENCY", 16)
    ttl = cache_ttl_s()
    duration_s = _env_int("LOGOS_BENCH_GW_BUDGET_DURATION_S", 2 * ttl + 10)
    baseline_n = _env_int("LOGOS_BENCH_GW_BUDGET_BASELINE", 10)
    window_s = _env_int("LOGOS_BENCH_GW_BUDGET_WINDOW_S", 5)
    key_id = _env_int("LOGOS_BENCH_GW_BUDGET_API_KEY_ID", 502)
    p50_max_ms = _env_float_opt("LOGOS_BENCH_GW_BUDGET_LOGOS_P50_MAX_MS")
    p99_max_ms = _env_float_opt("LOGOS_BENCH_GW_BUDGET_LOGOS_P99_MAX_MS")

    url = f"{gw.gateway_url()}/v1/chat/completions"
    headers = {"Authorization": f"Bearer {budget_api_key()}", "Content-Type": "application/json"}
    # Generous: a slow refresh is exactly what this leg exists to observe, so
    # the client must not cut it off before the gateway answers.
    timeout = httpx.Timeout(180.0, connect=10.0)

    db_before = budget_query_snapshot(key_id)
    print(f"  [budget] refresh query before load: {db_before}")

    async with httpx.AsyncClient(timeout=timeout, limits=httpx.Limits(max_connections=concurrency + 4)) as client:
        probe = await gw.post_chat_completion(client, url, headers)
        if probe.status_code in (401, 403):
            return {
                "skipped": True,
                "reason": f"budget key rejected (HTTP {probe.status_code}) — run seed_budget.sql first",
            }

        baseline_ms: List[float] = []
        baseline_failures: List[str] = []
        for i in range(baseline_n):
            r = await gw.post_chat_completion(client, url, headers)
            if r.ok:
                baseline_ms.append(r.total_ms)
            else:
                baseline_failures.append(f"baseline {i}: {r.error}")

        rows: List[Dict[str, Any]] = []
        load_since = _db_now()
        t_start = time.perf_counter()
        deadline = t_start + duration_s
        await asyncio.gather(*(_worker(client, url, headers, t_start, deadline, rows) for _ in range(concurrency)))
        wall_s = time.perf_counter() - t_start

    db_after = budget_query_snapshot(key_id)
    print(f"  [budget] refresh query after load: {db_after}")
    in_logos = logos_time(key_id, load_since)
    print(f"  [budget] time in Logos: {in_logos}")

    ok_ms = [r["total_ms"] for r in rows if r["ok"]]
    status_counts: Dict[str, int] = {}
    for r in rows:
        key = str(r["status"]) if r["status"] is not None else "transport error"
        status_counts[key] = status_counts.get(key, 0) + 1
    n_5xx = sum(1 for r in rows if r["status"] is not None and r["status"] >= 500)
    load = summarize(ok_ms)
    slowest = sorted(rows, key=lambda r: r["total_ms"], reverse=True)[:5]

    threshold: Dict[str, Any] = {"p50_max_ms": p50_max_ms, "p99_max_ms": p99_max_ms, "exceeded": False}
    if p50_max_ms is not None or p99_max_ms is not None:
        if load.get("n", 0) and in_logos.get("n", 0):
            logos = in_logos["logos"]
            threshold["p50_exceeded"] = p50_max_ms is not None and logos["p50_ms"] > p50_max_ms
            threshold["p99_exceeded"] = p99_max_ms is not None and logos["p99_ms"] > p99_max_ms
            threshold["exceeded"] = threshold["p50_exceeded"] or threshold["p99_exceeded"]
        else:
            # No measured request means no p99 to hold against the limit; a
            # run where every request failed must not read as passing.
            threshold["exceeded"] = True
            threshold["reason"] = (
                "no successful requests" if not load.get("n", 0) else "no time in Logos could be measured"
            )

    print(
        f"  [budget] {len(rows)} requests in {wall_s:.1f}s, "
        f"p50={load.get('p50_ms', 0):.0f}ms p99={load.get('p99_ms', 0):.0f}ms max={load.get('max_ms', 0):.0f}ms, "
        f"5xx={n_5xx}"
    )

    return {
        "skipped": False,
        "concurrency": concurrency,
        "duration_s": duration_s,
        "cache_ttl_s": ttl,
        "wall_s": wall_s,
        "requests": len(rows),
        "ok": len(ok_ms),
        "failed": len(rows) - len(ok_ms),
        "n_5xx": n_5xx,
        "status_counts": status_counts,
        "baseline": summarize(baseline_ms),
        "baseline_failures": baseline_failures[:10],
        "load": load,
        "in_logos": in_logos,
        "windows": _windows(rows, window_s, duration_s),
        "window_s": window_s,
        "slowest": [
            {"sent_at_s": round(r["sent_at_s"], 2), "total_ms": round(r["total_ms"], 1), "status": r["status"]}
            for r in slowest
        ],
        "failure_samples": [r["error"] for r in rows if not r["ok"]][:10],
        "db_before": db_before,
        "db_after": db_after,
        "threshold": threshold,
    }


if __name__ == "__main__":  # pragma: no cover
    import json

    print(json.dumps(asyncio.run(run()), indent=2))
