# Per-Request Forwarding Overhead Benchmark

Measures the overhead Logos adds to a request that is forwarded from the
orchestrator to a local workernode and back — scenario: **logosnode provider,
warm lane (model already loaded), no other running requests**, non-streaming
`POST /v1/chat/completions`. Headline metrics: p50 and p95 of via-Logos
latency minus the matching direct-lane percentile; goals are **< 1 ms p50**
and **< 20 ms p95**. Cloud providers
share the identical path up to the relay target, so the measured orchestrator
phases transfer; only the last network hop differs.

## What is measured (and what is not)

- **Measured:** every orchestrator phase (auth, setup, pipeline, context
  resolution, RPC round trip, response/DB block) via the env-gated perf trace
  (`LOGOS_PERF_TRACE=1`), plus worker phases (`LOGOS_WORKER_PERF_TRACE=1`,
  returned inside the `command_result` `perf` block). End-to-end latency from
  the client's point of view for both the Logos path and the direct baseline.
- **Under-estimated (no GPU host in CI):** the worker's `nvidia-smi` VRAM
  query and `/proc` host-RAM walk degrade to cheap no-ops because the fake
  lane reports `pid=None`. The optimizations (status TTL cache, no
  per-request status dirty-marking) remove most of that path from the hot
  path anyway, so the CI number stays meaningful; the phase table shows the
  remaining worker status-build cost (3 HTTP probes against the mock lane).
- **Not measured:** vLLM generation time (the mock lane answers instantly with
  a fixed ~1.5 KB body), TLS, multi-tenant concurrency, cold lanes.

## Components

| File | Role |
|---|---|
| `run_benchmark.py` | Director: starts mock lane + worker + orchestrator as subprocesses, runs warmup + interleaved measurement blocks, fetches perf traces, writes the report |
| `mock_lane.py` | FastAPI app imitating the vLLM endpoints the worker probes/relays to (`/v1/models`, `/metrics`, `/is_sleeping`, `/health`, `/v1/chat/completions`) |
| `worker_under_test.py` | Real `LaneManager` + real `LogosBridgeClient` (production auth + WebSocket), one warm `FakeLaneHandle` injected into `manager._handles` |
| `fake_lane_handle.py` | `ProcessHandle` reporting a RUNNING process with `pid=None`; the status probes are real HTTP calls against the mock lane |
| `seed.sql` | Benchmark data (developer + admin key, team with **NULL** rate limits, logosnode provider, model, token types) — idempotent |
| `stats.py` / `report.py` | Percentile statistics, JSON + Markdown report with p50/p95 goals |

## Running locally

Prerequisites: Docker (postgres:17), `uv`, Python 3.13.

```bash
# 1. Database (throwaway container on port 5433 — the dev stack owns 5432)
docker run -d --name logos-bench-db -e POSTGRES_PASSWORD=root \
  -e POSTGRES_DB=logosdb -p 5433:5432 postgres:17

# 2. Schema (Liquibase CLI bundles its own JRE; --search-path is a global option)
docker run --rm --add-host=host.docker.internal:host-gateway \
  -v "$PWD/logos/logos-webservice/src/main/resources:/resources" \
  liquibase/liquibase:4.28.0 --search-path=/resources migrate \
  --changelog-file=liquibase/changelog/master.xml \
  --url="jdbc:postgresql://host.docker.internal:5433/logosdb" \
  --username=postgres --password=root

# 3. Seed
docker exec -i logos-bench-db psql -U postgres -d logosdb \
  < logos/benchmarks/per_request_overhead/seed.sql

# 4. Venv (once)
cd logos/logos-orchestrator
ln -sfn ../../shared shared
uv venv .venv && uv pip install -q .
# The worker runs from the same venv (the director starts it as a
# subprocess); its checked-in gRPC gencode needs protobuf >= 6.30.
uv pip install -q -r ../logos-workernode/requirements.txt "protobuf>=6.30,<7"

# 5. Run (ports 8090/11436/50051/5433 must be free — the dev stack may hold some)
.venv/bin/python ../benchmarks/per_request_overhead/run_benchmark.py
```

Reports land in `logos/benchmarks/per_request_overhead/reports/` (`result.json`
+ `report.md` + per-process logs under `reports/run/`).

Tuning knobs (env): `LOGOS_BENCH_WARMUP` (50), `LOGOS_BENCH_SAMPLES_LOGOS`
(100), `LOGOS_BENCH_SAMPLES_DIRECT` (50), `LOGOS_BENCH_BLOCKS` (4),
`LOGOS_BENCH_NO_PERF_TRACE=1` (disable tracing to measure the tracer's own
cost), `HF_HOME`/`HF_HUB_OFFLINE` for the eager SentenceTransformer load at
orchestrator startup (the CI workflow caches the model).

## CI

`.github/workflows/logos_benchmark-overhead.yml` runs the same harness on
every PR (incl. leaving draft) touching `logos/**` or `shared/**`, against a
postgres:17 service + Liquibase migration. The job **fails** when p50 exceeds
1.5 ms or p95 exceeds 20 ms, and posts an idempotent comment with both
percentiles and the phase table.

## Notes

- The seed's team has **NULL** rate limits on purpose: the schema defaults are
  5 RPM / 10 000 TPM, which would turn the benchmark into a 429 machine after
  five requests.
- `LOGOS_DB_URL` is read at import time by the orchestrator; the director
  sets it in the subprocess environment before start.
- The benchmark's perf-trace endpoint (`/internal/perf_trace/{request_id}`)
  is only reachable with `LOGOS_INTERNAL_SECRET` set and is a no-op (empty
  store) unless `LOGOS_PERF_TRACE=1` — in production it stays disabled.
