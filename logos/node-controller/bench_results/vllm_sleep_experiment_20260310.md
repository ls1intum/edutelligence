# vLLM Sleep/Wake Experiment (Levels 1 and 2)

## Date and Environment

- Run date (UTC): 2026-03-10
- Host GPUs: 2x Quadro RTX 5000 (16 GB each)
- vLLM: 0.17.0
- Benchmark harness: `bench_vllm_sleep.py` (added in this repo)
- Free disk before run: ~19 GB (`/dev/md0`, 96% used)

## Goal

Measure, for previously tested vLLM models:

1. VRAM before sleep
2. VRAM during sleep
3. VRAM after wake
4. Time to wake and respond to the first request

Sleep levels tested:

- Level 1: offload weights to CPU, discard KV cache
- Level 2: discard all GPU memory (weights + KV cache)

## Models From Previous vLLM Benchmarks

From historical benchmark files in this repo (`lane_benchmark_*.json/.csv`), the vLLM models were:

- `Qwen/Qwen2.5-32B-Instruct-AWQ`
- `Qwen/Qwen2.5-Coder-32B-Instruct-AWQ`
- `deepseek-ai/DeepSeek-R1-0528-Qwen3-8B`

Execution status in this run:

- Executed: `deepseek-ai/DeepSeek-R1-0528-Qwen3-8B`
- Not executed: both Qwen AWQ models (not present in local HF cache; only DeepSeek cache was available)

## Benchmark Command Used

```bash
cd edutelligence/logos/node-controller
.venv/bin/python bench_vllm_sleep.py \
  --models deepseek-ai/DeepSeek-R1-0528-Qwen3-8B \
  --repeats 1 \
  --sleep-levels 1,2 \
  --baseline-seconds 5 \
  --sleep-hold-seconds 8 \
  --recovery-seconds 5 \
  --sample-interval-seconds 0.5 \
  --per-request-timeout-seconds 180 \
  --wake-response-timeout-seconds 240
```

## Process

For each sleep level:

1. Start `vllm serve` with:
   - `--enable-sleep-mode`
   - `VLLM_SERVER_DEV_MODE=1` (enables `/sleep`, `/wake_up`, `/is_sleeping`)
2. Wait for readiness (`/health`, `/v1/models`).
3. Send warmup request (`/v1/chat/completions`).
4. Record pre-sleep VRAM (`nvidia-smi`).
5. Call `POST /sleep?level={1|2}&mode=wait`.
6. Verify sleeping via `GET /is_sleeping`.
7. Sample VRAM during sleep window.
8. Call `POST /wake_up`.
9. Verify not sleeping via `GET /is_sleeping`.
10. Send probe request until first success; record wake-to-first-response time.
11. Record post-wake VRAM.

## Results (DeepSeek-R1-0528-Qwen3-8B)

Source file:

- `bench_results/sleep_benchmark_20260310_113827/sleep_benchmark_summary.csv`

### Summary Table

| Sleep Level | VRAM Before Sleep (MB) | VRAM During Sleep Min/Avg/Max (MB) | VRAM After Wake (MB) | VRAM After First Response (MB) | Sleep API Time (ms) | Wake API Time (ms) | Wake -> First Response (ms) | First Response Latency (ms) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 24032 | 1588 / 1588 / 1588 | 22788 | 22788 | 10123.1 | 1252.9 | 533.4 | 533.2 |
| 2 | 22788 | 1588 / 1588 / 1588 | 22788 | 22788 | 736.1 | 258.7 | 531.6 | 531.5 |

### Per-GPU VRAM Snapshots (MB used)

| Sleep Level | Before Sleep | After Sleep | After Wake |
|---|---|---|---|
| 1 | [12016, 12016] | [794, 794] | [11394, 11394] |
| 2 | [11394, 11394] | [794, 794] | [11394, 11394] |

### Observations

- Both sleep levels reduced GPU usage to ~1.6 GB total (about 0.8 GB/GPU) during sleep.
- Level 1 had much longer sleep transition time (~10.1 s) than Level 2 (~0.74 s) in this run.
- Wake-to-first-response was ~0.53 s for both levels in this setup.
- After Level 1 wake, VRAM returned close to pre-sleep but stayed below the initial first baseline (`24032 -> 22788 MB`) after a single probe request.

## Historical Baseline Context (from existing lane benchmarks)

- Qwen Coder vLLM baseline VRAM in previous runs: ~`30804 MB` total (~`15402 MB/GPU`)
- DeepSeek vLLM baseline VRAM in previous runs:
  - ~`30360-30368 MB` total at `gpu_memory_utilization=0.9`
  - ~`24024-24032 MB` total at `gpu_memory_utilization=0.7` (latest runs)

## Artifacts

- Benchmark script: `bench_vllm_sleep.py`
- Run directory: `bench_results/sleep_benchmark_20260310_113827`
- Files:
  - `sleep_benchmark_summary.csv`
  - `sleep_benchmark_raw.json`
  - `sleep_benchmark_meta.json`
  - `deepseek-ai__deepseek-r1-0528-qwen3-8b.log`

## Related Incident Analysis

- Worker crash postmortem:
  - `bench_results/vllm_worker_crash_postmortem_20260310.md`
