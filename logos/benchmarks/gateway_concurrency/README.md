# Gateway Concurrency & Failover Benchmark

Measures what the design doc for the SLO-restructure work (architecture
meeting 2026-09-18) asks for before the inference gateway (`logos-webservice`
`gateway/`) carries PROD traffic: how many streaming requests it can hold
open concurrently and where that limit comes from, the added latency of the
gateway hop, its behaviour at the concurrency limit, and whether killing one
of 2+ replicas under real load is visible to clients.

Companion to `../per_request_overhead`, which measures the *local* path
(orchestrator → workernode) with no concurrency. This benchmark is the
*cloud* path (webservice gateway → cloud provider) under concurrent
streaming load — different bottleneck (a bounded thread pool + queue vs. a
GPU lane), different tool.

## What is measured (and what is not)

- **Measured:** the webservice's own concurrency ceiling under held-open
  streaming responses (`spring.task.execution.pool.*`, see
  `application.properties`), added per-request latency vs. a direct call to
  the same fake upstream, behaviour once the ceiling is crossed (graceful
  backpressure vs. hangs/crashes), and — with 2+ replicas up — whether
  killing one is visible to clients under real concurrent load (a heavier,
  automated version of `../../scripts/gateway-failover-demo.sh`'s light
  polling check).
  The ramp's headline number is **peak gateway relay tasks**, not step size.
  Firing *n* requests at once does not mean *n* were ever concurrent: the
  fake upstream's completion lasts about a second, so the early streams
  close before the last ones are even admitted. The barrier that pins
  completions open lives in the fake upstream (`/_bench/step`,
  `/_bench/release`); the counter that reports the peak lives in each
  webservice replica (`GatewayRelayOccupancy` around the
  `StreamingResponseBody` callback, exposed at
  `/internal/gateway_relay_stats`). Counting at the upstream would
  over-count: `GatewayCloudForwarder.forward()` opens the upstream response
  before that executor task runs, so bytes can sit buffered in the socket
  without occupying a pool slot.
  A streaming request counts as successful only once its terminal
  `data: [DONE]` event arrives. The status line is written before the
  completion is relayed, so a stream cut off midway — what killing a
  replica under load produces — still arrives as `HTTP 200`; the failover
  leg classifies such a truncated stream as a connectivity failure.
- **Also measured (budget-admission leg):** admission latency for a key that
  *has* a budget and a month of history behind it — see
  [Budget admission](#budget-admission) below.
- **Not measured:** a real cloud provider's own throttling (the upstream is
  a fake, see below, on purpose), local/mixed-path routing through the
  orchestrator, rate-limit enforcement. The first three legs also leave the
  budget out (`seed.sql` sets it to NULL so it is not what caps
  concurrency there); the budget-admission leg covers it separately.
- **No PASS/FAIL gate.** This is the first version of this benchmark; there
  is no baseline yet to set a threshold against (see the CI workflow). The
  budget-admission leg can *flag* a p99 above an optional threshold.

## Components

| File | Role |
|---|---|
| `run_benchmark.py` | Director: starts the fake upstream, checks the gateway is reachable, runs all four legs, writes the report. Does **not** start `logos-webservice` itself — see Prerequisites. |
| `fake_cloud_upstream.py` | FastAPI app imitating an OpenAI-shaped `/v1/chat/completions` (streaming SSE + non-streaming), configurable per-token delay. Holds completions open under `/_bench/*` for the concurrency leg |
| `gateway_client.py` | Shared async request helpers used by all legs; aggregates per-replica relay stats |
| `load_generator.py` | Concurrency-ramp leg |
| `latency_diff.py` | Added-latency leg |
| `failover_under_load.py` | Failover-under-load leg (needs 2+ replicas) |
| `budget_admission.py` | Budget-admission leg (needs `seed_budget.sql`) |
| `seed.sql` | Benchmark data (team with **NULL** rate limits/budget, cloud provider pointed at the fake upstream) — idempotent |
| `seed_budget.sql` | Budget-leg data on top of `seed.sql`: application key **with** a budget limit, prices, and a month of `log_entry` history (default 200,000 rows, half unpriced) — idempotent |
| `stats.py` / `report.py` | Percentile statistics, JSON + Markdown report |
| `pr_comment.py` | Posts/updates one PR comment from the report — informational, no gate |

## Running locally

Prerequisites: Docker, `uv`, Python 3.13. Same Compose database the
webservice uses (`logos-db`) — do not seed a separate throwaway Postgres;
the gateway would not see that data.

```bash
cd logos

# 1. Bring up dependencies + one webservice replica (Liquibase migrates on
#    startup). Comment out the fixed 127.0.0.1:18082:8081 host publish under
#    logos-webservice: ports: first when you plan to scale — same caveat as
#    scripts/gateway-failover-demo.sh.
docker compose -f docker-compose.dev.yaml up -d --build \
  traefik logos-rate-gateway logos-db keycloak logos-webservice

# 2. Wait until that replica has finished migrating, then scale to 2.
#    Starting both against an empty DB races Liquibase's changelog-table
#    creation; see the CI workflow for the full readiness loop.
docker compose -f docker-compose.dev.yaml up -d --scale logos-webservice=2 logos-webservice

# 3. Seed the Compose database the webservice is actually using.
#    seed_budget.sql builds on seed.sql; the row count is a psql variable.
docker exec -i logos-db psql -U postgres -d logosdb \
  < benchmarks/gateway_concurrency/seed.sql
docker exec -i logos-db psql -U postgres -d logosdb -v bench_budget_rows=200000 \
  < benchmarks/gateway_concurrency/seed_budget.sql

# 4. Point the benchmark at Traefik
export LOGOS_BENCH_GW_URL=http://localhost:18081

# 5. Venv + run
uv venv benchmarks/gateway_concurrency/.venv
uv pip install --python benchmarks/gateway_concurrency/.venv/bin/python fastapi 'uvicorn[standard]' httpx
benchmarks/gateway_concurrency/.venv/bin/python benchmarks/gateway_concurrency/run_benchmark.py
```

Only 1 replica available (e.g. a quick local check)? Set
`LOGOS_BENCH_GW_SKIP_FAILOVER=1` — the other legs still run. Did not run
`seed_budget.sql`? Set `LOGOS_BENCH_GW_SKIP_BUDGET=1` (without it the leg
reports itself as skipped when the budget key is rejected).

## Budget admission

**Why.** The first three legs run with a key that has no budget, against
an empty `log_entry`. That hides one cost completely: for an application key
with a budget limit, a budget-cache miss sums the key's month of spend
through `log_entry_cost`, and every request of that key that misses the
cache waits for that sum. A row without a stored price is re-priced on every
read, so the refresh time grows with the key's month of traffic. On
production it reached about 50 s at 230,000 such rows. During that time
requests of the key finish together, late, and the long queries hold the
database connections that authentication needs (HTTP 500 after 30 s).

**What.** `seed_budget.sql` creates an application key (`id 502`,
`lg-bench-gw-budget-0000`) with a budget limit far above anything the run
can spend, token prices for the bench model, and a month of successful
direct-cloud history for the key. Psql variables:

| Variable | Default | Meaning |
|---|---|---|
| `bench_budget_rows` | `200000` | history rows for the key, spread from the start of the current month to now |
| `bench_budget_unfinalized` | `50` | percent of those rows left without a stored price (`cost_finalized = FALSE`) |

The leg (`budget_admission.py`) then:

1. times the budget refresh query once in the database (`docker exec <db> psql`),
   with the number of unpriced rows of the key;
2. sends a sequential idle baseline on the budget key;
3. runs `LOGOS_BENCH_GW_BUDGET_CONCURRENCY` (16) workers that send
   non-streaming requests back to back for `LOGOS_BENCH_GW_BUDGET_DURATION_S`
   (default: 2 × `LOGOS_GATEWAY_BUDGET_CACHE_TTL_SECONDS` + 10 s), so the load
   crosses at least one cache expiry (the gateway reloads an expired
   snapshot in the background, so no request should wait for the refresh);
4. times the refresh query again. The gateway finalizes unpriced history in
   the background, so the second figure shows how far that got;
5. reads back each load request's `log_entry` row and takes the time it spent
   in Logos: arrival at the controller to the end of the response, minus the
   provider window. That is the gateway's own cost without the fake
   upstream's fixed delay (and without the Traefik hop), split out into its
   admission part (authentication, rate limit, budget check, reservation).

The report shows baseline vs. load percentiles, the time in Logos, latency per
send-time window (a slow refresh shows as a window whose requests all finish
late together), the status histogram (5xx = pool exhaustion), and both query
timings.

**Threshold.** Set `LOGOS_BENCH_GW_BUDGET_LOGOS_P50_MAX_MS` and/or
`LOGOS_BENCH_GW_BUDGET_LOGOS_P99_MAX_MS` to flag a median or p99 of the time
in Logos above it in the report. The run still exits 0 unless
`LOGOS_BENCH_GW_BUDGET_FAIL_ON_THRESHOLD=1` is also set.

Standalone (stack and fake upstream already up):

```bash
cd benchmarks/gateway_concurrency
.venv/bin/python budget_admission.py
```

## Environment

See the module docstrings in `run_benchmark.py`, `gateway_client.py`,
`load_generator.py`, `latency_diff.py`, `failover_under_load.py`, and
`budget_admission.py` for the full list of tunables (concurrency steps, sample counts, durations, the
informational `LOGOS_GATEWAY_ASYNC_MAX_SIZE`/`_QUEUE_CAPACITY` used to
annotate the report against the webservice's actual config).
