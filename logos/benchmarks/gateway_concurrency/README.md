# Gateway Concurrency & Failover Benchmark

Measures what the design doc for the SLA-restructure work (architecture
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
- **Not measured:** a real cloud provider's own throttling (the upstream is
  a fake, see below, on purpose), local/mixed-path routing through the
  orchestrator, budget/rate-limit enforcement (the seed disables both so
  they are not what caps concurrency here).
- **No PASS/FAIL gate.** This is the first version of this benchmark; there
  is no baseline yet to set a threshold against (see the CI workflow).

## Components

| File | Role |
|---|---|
| `run_benchmark.py` | Director: starts the fake upstream, checks the gateway is reachable, runs all three legs, writes the report. Does **not** start `logos-webservice` itself — see Prerequisites. |
| `fake_cloud_upstream.py` | FastAPI app imitating an OpenAI-shaped `/v1/chat/completions` (streaming SSE + non-streaming), configurable per-token delay |
| `gateway_client.py` | Shared async request helpers used by all three legs |
| `load_generator.py` | Concurrency-ramp leg |
| `latency_diff.py` | Added-latency leg |
| `failover_under_load.py` | Failover-under-load leg (needs 2+ replicas) |
| `seed.sql` | Benchmark data (team with **NULL** rate limits/budget, cloud provider pointed at the fake upstream) — idempotent |
| `stats.py` / `report.py` | Percentile statistics, JSON + Markdown report |
| `pr_comment.py` | Posts/updates one PR comment from the report — informational, no gate |

## Running locally

Prerequisites: Docker, `uv`, Python 3.13.

```bash
cd logos

# 1. Database + schema (same as ../per_request_overhead/README.md steps 1-2)
docker run -d --name logos-bench-gw-db -e POSTGRES_PASSWORD=root \
  -e POSTGRES_DB=logosdb -p 5434:5432 postgres:17
docker run --rm --add-host=host.docker.internal:host-gateway \
  -v "$PWD/logos-webservice/src/main/resources:/resources" \
  liquibase/liquibase:4.28.0 --search-path=/resources migrate \
  --changelog-file=liquibase/changelog/master.xml \
  --url="jdbc:postgresql://host.docker.internal:5434/logosdb" \
  --username=postgres --password=root

# 2. Seed
docker exec -i logos-bench-gw-db psql -U postgres -d logosdb \
  < benchmarks/gateway_concurrency/seed.sql

# 3. Bring up the webservice stack (2 replicas — comment out the fixed
#    127.0.0.1:18082:8081 host publish under logos-webservice: ports: first,
#    same caveat as scripts/gateway-failover-demo.sh)
docker compose -f docker-compose.dev.yaml up -d --build --scale logos-webservice=2

# 4. Point the benchmark at that DB's webservice
export LOGOS_BENCH_GW_URL=http://localhost:18081

# 5. Venv + run
uv venv benchmarks/gateway_concurrency/.venv
uv pip install --python benchmarks/gateway_concurrency/.venv/bin/python fastapi 'uvicorn[standard]' httpx
benchmarks/gateway_concurrency/.venv/bin/python benchmarks/gateway_concurrency/run_benchmark.py
```

Only 1 replica available (e.g. a quick local check)? Set
`LOGOS_BENCH_GW_SKIP_FAILOVER=1` — the other two legs still run.

## Environment

See the module docstrings in `run_benchmark.py`, `gateway_client.py`,
`load_generator.py`, `latency_diff.py`, and `failover_under_load.py` for the
full list of tunables (concurrency steps, sample counts, durations, the
informational `LOGOS_GATEWAY_ASYNC_MAX_SIZE`/`_QUEUE_CAPACITY` used to
annotate the report against the webservice's actual config).
