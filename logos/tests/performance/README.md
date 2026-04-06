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
- `tests/performance/workloads/explicit/10m/workload_explicit_local4_no_coder14_bursty_200_10m.csv`
  200 direct-model requests over 10 minutes, excluding `Qwen/Qwen2.5-Coder-14B-Instruct-AWQ`.
- `tests/performance/workloads/explicit/10m/workload_explicit_local2_mistral_deepseek_bursty_200_10m.csv`
  200 direct-model requests over 10 minutes using `solidrust/Mistral-7B-Instruct-v0.3-AWQ` and `casperhansen/deepseek-r1-distill-llama-8b-awq`.
- `tests/performance/workloads/explicit/10m/workload_explicit_local2_mistral_deepseek_bursty_600_10m.csv`
  600 direct-model requests over 10 minutes using the same two-model family as the stored `500/10m` baseline, but spread across more same-model bursts.
- `tests/performance/workloads/explicit/10m/workload_explicit_local2_mistral_deepseek_bursty_2400_10m.csv`
  2400 direct-model requests over 10 minutes using the same two-model burst pattern family.
- `tests/performance/workloads/explicit/10m/workload_explicit_local2_mistral_deepseek_even_jittered_600_10m.csv`
  600 direct-model requests over 10 minutes with an even `300/300` split across `solidrust/Mistral-7B-Instruct-v0.3-AWQ` and `casperhansen/deepseek-r1-distill-llama-8b-awq`, evenly distributed in time with bounded jitter.
- `tests/performance/workloads/explicit/10m/workload_explicit_local2_mistral_deepseek_even_jittered_2400_10m.csv`
  2400 direct-model requests over 10 minutes with the same even time/model spread.
- `tests/performance/workloads/explicit/10m/workload_explicit_local3_even_random_600_10m.csv`
  600 direct-model requests over 10 minutes with an even `200/200/200` split across `solidrust/Mistral-7B-Instruct-v0.3-AWQ`, `casperhansen/deepseek-r1-distill-llama-8b-awq`, and `Qwen/Qwen2.5-Coder-7B-Instruct-AWQ`, using randomized interleaving instead of same-model bursts.
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

Each run is written into its own folder using the wrapper host's local timestamp:

- `tests/performance/results/.../YYYYMMDD_HHMMSS - experiment-name/`

For a run started at `20260329_180629` with `--output tests/performance/results/explicit/10m/my_run.csv`, the runner writes:

- `tests/performance/results/explicit/10m/20260329_180629 - my_run/summary.csv`
  Aggregated latency and throughput summary.
- `tests/performance/results/explicit/10m/20260329_180629 - my_run/detailed.csv`
  One row per request. This is the main paired request/response file.
- `tests/performance/results/explicit/10m/20260329_180629 - my_run/scenario_manifest.json`
  Exact scenario metadata used for the run, copied from the workload sidecar when available or inferred for legacy workloads.
- `tests/performance/results/explicit/10m/20260329_180629 - my_run/request_response.jsonl`
  Full untruncated request/response payload pairs plus timing fields.
- `tests/performance/results/explicit/10m/20260329_180629 - my_run/per_model_summary.csv`
  Per-model request counts plus `p50/p95/p99` TTFT, latency, queue wait, and processing metrics.
- `tests/performance/results/explicit/10m/20260329_180629 - my_run/latency_distribution.csv`
- `tests/performance/results/explicit/10m/20260329_180629 - my_run/ttft_distribution.csv`
- `tests/performance/results/explicit/10m/20260329_180629 - my_run/runtime_samples.jsonl`
  Periodic runtime snapshots collected during the run.
- `tests/performance/results/explicit/10m/20260329_180629 - my_run/provider_vram.json`
  Provider VRAM history payload from the app.
- `tests/performance/results/explicit/10m/20260329_180629 - my_run/request_log_stats.json`
  Aggregated request-log stats for the run window.
- `tests/performance/results/explicit/10m/20260329_180629 - my_run/run_meta.json`
  Run metadata plus the exact output paths.
- `tests/performance/results/explicit/10m/20260329_180629 - my_run/detailed.png`
- `tests/performance/results/explicit/10m/20260329_180629 - my_run/detailed_client_duration.png`
- `tests/performance/results/explicit/10m/20260329_180629 - my_run/detailed_queue_processing.png`
- `tests/performance/results/explicit/10m/20260329_180629 - my_run/detailed_cumulative_success.png`
- `tests/performance/results/explicit/10m/20260329_180629 - my_run/latency_distribution.png`
- `tests/performance/results/explicit/10m/20260329_180629 - my_run/latency_distribution.svg`
- `tests/performance/results/explicit/10m/20260329_180629 - my_run/ttft_distribution.png`
- `tests/performance/results/explicit/10m/20260329_180629 - my_run/ttft_distribution.svg`

If you do not pass `--output`, the runner still mirrors the workload folder under `tests/performance/results/`, but now each run gets its own timestamped experiment folder.

## Where To Look

Use `detailed.csv` when you want request/response pairing and per-request numbers:

- request id and server request id
- scenario name and arrival offset
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
- request, TTFT, and response timestamps in UTC

Use `request_response.jsonl` when you want the full untruncated payloads:

- exact request payload body
- exact response payload body
- timing fields and request ids
- provider/model identity
- error text without CSV truncation

Use `per_model_summary.csv` when you want model-by-model comparisons:

- request counts and success rate
- `p50/p95/p99` TTFT
- `p50/p95/p99` total latency
- `p50/p95/p99` queue wait
- `p50/p95/p99` processing time

Use `latency_distribution.csv` and `ttft_distribution.csv` when you want reproducible histogram bins for downstream analysis or your own charting.

Use `runtime_samples.jsonl` when you want live scheduler and worker state during the run:

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
- New workload generators also write a sidecar JSON next to each CSV with the scenario metadata used to produce it.

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
