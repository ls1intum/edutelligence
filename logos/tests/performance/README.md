# Performance Benchmarks

This benchmark pipeline replays workload CSVs against the live Logos `/v1/chat/completions` path and saves both per-request metrics and runtime state snapshots.

## Layout

- `tests/performance/workloads/explicit/10m/`
  Contains the short direct-model benchmark workload.
- `tests/performance/workloads/explicit/60m/`
  Contains the longer direct-model benchmark workload.
- `tests/performance/workloads/resource/10m/`
  Contains the short resource-mode benchmark workload.
- `tests/performance/workloads/resource/60m/`
  Contains the longer resource-mode benchmark workload.
- `tests/performance/results/explicit/10m/`
  Default output location for runs started from a `10m` workload.
- `tests/performance/results/explicit/60m/`
  Default output location for runs started from a `60m` workload.
- `tests/performance/results/resource/10m/`
  Default output location for short resource-mode runs.
- `tests/performance/results/resource/60m/`
  Default output location for long resource-mode runs.
- `tests/performance/run_api_workload.py`
  Replays the workload, waits for request logs, and writes all result artifacts.
- `tests/performance/test_scheduling_performance.sh`
  Docker-first wrapper for the benchmark runner.

## Current Workloads

- `tests/performance/workloads/explicit/10m/workload_explicit_local5_skewed_bursty_10m.csv`
  84 direct-model requests over 10 minutes.
- `tests/performance/workloads/explicit/60m/workload_explicit_local5_skewed_bursty_60m.csv`
  500 direct-model requests over 60 minutes.
- `tests/performance/workloads/resource/10m/workload_resource_local5_skewed_bursty_10m.csv`
  84 classification-mode requests over 10 minutes.
- `tests/performance/workloads/resource/60m/workload_resource_local5_skewed_bursty_60m.csv`
  500 classification-mode requests over 60 minutes.

The explicit files:
- route directly via the `"model"` field
- use the same skewed distribution across the 5 local models
- cluster similar requests into bursts so the same model gets hit repeatedly in short windows
- remain compatible with the current `/v1/chat/completions` benchmark path

The resource-mode files:
- omit `"model"` entirely so classification runs
- use system-prompt steering so initial classification lands on the intended local spread
- were checked against the live classifier with the local 5 plus `gpt-4.1-mini` and `gpt-4.1` allowed

## Running A Benchmark

Recommended:

```bash
./tests/performance/test_scheduling_performance.sh \
  --logos-key "<ROOT_LOGOS_KEY>" \
  --workload tests/performance/workloads/explicit/10m/workload_explicit_local5_skewed_bursty_10m.csv
```

60-minute run:

```bash
./tests/performance/test_scheduling_performance.sh \
  --logos-key "<ROOT_LOGOS_KEY>" \
  --workload tests/performance/workloads/explicit/60m/workload_explicit_local5_skewed_bursty_60m.csv \
  --latency-slo-ms 15000
```

10-minute resource-mode classification run:

```bash
./tests/performance/test_scheduling_performance.sh \
  --logos-key "<ROOT_LOGOS_KEY>" \
  --workload tests/performance/workloads/resource/10m/workload_resource_local5_skewed_bursty_10m.csv
```

60-minute resource-mode classification run:

```bash
./tests/performance/test_scheduling_performance.sh \
  --logos-key "<ROOT_LOGOS_KEY>" \
  --workload tests/performance/workloads/resource/60m/workload_resource_local5_skewed_bursty_60m.csv \
  --latency-slo-ms 15000
```

Custom output base:

```bash
./tests/performance/test_scheduling_performance.sh \
  --logos-key "<ROOT_LOGOS_KEY>" \
  --workload tests/performance/workloads/explicit/10m/workload_explicit_local5_skewed_bursty_10m.csv \
  --output tests/performance/results/explicit/10m/my_run.csv
```

Direct Python inside the server container:

```bash
docker compose exec logos-server python /app/tests/performance/run_api_workload.py \
  --logos-key "<ROOT_LOGOS_KEY>" \
  --workload /app/tests/performance/workloads/explicit/10m/workload_explicit_local5_skewed_bursty_10m.csv
```

## What Gets Saved

For a run with output base `tests/performance/results/explicit/10m/my_run.csv`, the runner writes:

- `tests/performance/results/explicit/10m/my_run_summary.csv`
  Aggregated latency and throughput summary.
- `tests/performance/results/explicit/10m/my_run_detailed.csv`
  One row per request. This is the main paired request/response file.
- `tests/performance/results/explicit/10m/my_run_runtime_samples.jsonl`
  Periodic runtime snapshots collected during the run.
- `tests/performance/results/explicit/10m/my_run_provider_vram.json`
  Provider VRAM history payload from the app.
- `tests/performance/results/explicit/10m/my_run_request_log_stats.json`
  Aggregated request-log stats for the run window.
- `tests/performance/results/explicit/10m/my_run_run_meta.json`
  Run metadata plus the exact output paths.
- `tests/performance/results/explicit/10m/my_run_detailed.png`
- `tests/performance/results/explicit/10m/my_run_detailed_client_duration.png`
- `tests/performance/results/explicit/10m/my_run_detailed_queue_processing.png`
- `tests/performance/results/explicit/10m/my_run_detailed_cumulative_success.png`

If you do not pass `--output`, the runner mirrors the workload folder under `tests/performance/results/` automatically.

## Where To Look

Use `*_detailed.csv` when you want request/response pairing and per-request numbers:

- request id and server request id
- request body and response body
- chosen provider and model
- TTFT
- total latency
- prompt, completion, and total tokens
- computed token-rate helpers
- queue depth and utilization at arrival
- queue wait, processing time, and scheduler total time
- cold-start flag
- load duration if the provider reports it

Use `*_runtime_samples.jsonl` when you want live scheduler and worker state during the run:

- connected providers
- tracked requests
- provider runtime signals
- full worker runtime snapshots for logosnode providers
- lane state, sleep state, active requests, backend queue metrics, and device information when available

Use `*_provider_vram.json` when you want VRAM and loaded-model history across the run window.

## Notes

- Use a root/admin `logos_key` for full artifacts. The extra runtime endpoints and request-log stats are root-only.
- The runner already sends normal `/v1/chat/completions` requests. The benchmark path is not a special internal fast path.
- Separate sleep and wake durations are not logged as dedicated request fields today. The benchmark captures:
- `load_duration_ms` when the provider reports it
- runtime snapshots showing whether lanes were `loaded`, `sleeping`, `cold`, or `starting`
- `cold_start`

## Classification Check

If you want to verify the resource-mode mapping before a live run:

```bash
docker compose cp tests/performance/analyze_workload_classification.py logos-server:/app/tests/performance/analyze_workload_classification.py
docker compose cp tests/performance/workloads/resource logos-server:/app/tests/performance/workloads/resource
docker compose exec logos-server python /app/tests/performance/analyze_workload_classification.py \
  --workload /app/tests/performance/workloads/resource/10m/workload_resource_local5_skewed_bursty_10m.csv \
  --allowed-model Qwen/Qwen2.5-Coder-7B-Instruct-AWQ \
  --allowed-model Qwen/Qwen2.5-Coder-14B-Instruct-AWQ \
  --allowed-model Qwen/Qwen2.5-7B-Instruct-AWQ \
  --allowed-model Qwen/Qwen2.5-14B-Instruct-AWQ \
  --allowed-model casperhansen/deepseek-r1-distill-llama-8b-awq \
  --allowed-model gpt-4.1-mini \
  --allowed-model gpt-4.1
```
