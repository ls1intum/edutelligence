# Why were not all requests successful in the first 5-LLM benchmark?

Run analyzed: `benchmarks/benchmark_results/20260610_235712_logos-sleep_workload_gsm8k_5llm`
(GSM8K workload, 5 models, scenario `logos-sleep`, 2026-06-10 20:36–21:57 UTC,
target `logos-test.aet.cit.tum.de`, max 64 concurrent, client timeout 600 s).

## Headline numbers

- **1319 requests total, 1255 successful (95.1 %), 64 failed.**
- The 64 failures decompose into four distinct classes (from
  `results_detailed.csv`):

| # | Class | Count | Models affected |
|---|---|---|---|
| 1 | Client-side 600 s timeout (`status_code=0`, ttlt ≈ 600 s) | 47 | **Qwen3.6-35B-A3B only** |
| 2 | DNS resolution failure (`[Errno 8] nodename nor servname provided`) | 8 | spread across 4 models |
| 3 | HTTP 503 `Failed to resolve execution context for model …` | 5 | Llama-3.1-8B ×3, gemma-3-12b, gemma-3-4b |
| 4 | Stream cut mid-response (HTTP 200 + `incomplete chunked read`) | 4 | Llama-3.1-8B ×2, Phi-4-reasoning ×2 |

## Class 1 — Qwen3.6-35B client timeouts (47, dominant)

These are **not** anomalies but the truncated tail of Qwen's normal latency
distribution in this run: the *successful* Qwen requests already had
**TTFT p50 ≈ 555 s and p95 ≈ 599 s** — i.e. the median first token arrived
nine minutes after submission, just under the 600 s client timeout. The 47
timeouts (spread over the whole hour, 20:46–21:47) are simply the slower half
of bursts crossing the wall.

Root cause: a 35B model on this cluster cannot be kept warm under 5-model
contention. Every Qwen burst pays eviction of other lanes plus a multi-minute
cold load, and queued requests accumulate behind it. Contributing factors at
the benchmarked commit (since fixed/identified):

- missing calibrated `max_model_len` caused lane crashes and reloads
  (fixed via calibration, deploy `8216c08e`),
- shared torch.compile cache could crash freshly spawned lanes
  ("Expected tensors only"), forcing restarts (fixed in `f00f699d`),
- `LOAD_FAILURE_COOLDOWN_SECONDS = 120 s` adds dead time after every failed
  load attempt.

What to change for the next run:

- raise the client timeout for large-model workloads
  (`--request-timeout-s`, default 600), or exclude/duplicate-weight the 35B
  model when the goal is switching behaviour rather than worst-case sizing;
- the client now records the exception class in the `error` column
  (previously httpx timeouts produced an *empty* error string, which is why
  these 47 rows were initially unexplained).

## Class 2 — DNS failures (8)

All eight fail within ~3 ms of submission with
`[Errno 8] nodename nor servname provided, or not known` — a client-side
(macOS) resolver hiccup on the benchmark host while resolving
`logos-test.aet.cit.tum.de` under 64-way connection concurrency. Nothing
reached Logos. If this repeats, retrying connect-phase errors (request not
yet sent, so statistically safe) or pinning the host in `/etc/hosts` on the
benchmark machine removes the noise.

## Class 3 — HTTP 503 context-resolution timeouts (5)

The orchestrator's per-request budget to produce a usable lane is
`_CONTEXT_RESOLVE_TIMEOUT_S = 180 s` (`pipeline.py:276`); with queue/
classification overhead these requests died after ~242–244 s. During heavy
Qwen eviction churn the planner could not give Llama/gemma a lane within the
budget (load-failure cooldowns + VRAM fully committed). These are the expected
failure mode of an overloaded planner — the fix list for class 1 reduces them
for free.

## Class 4 — mid-stream connection cuts (4)

Four requests got HTTP 200, streamed tokens, then the peer closed before the
final chunk (`incomplete chunked read`). Two (Llama, ttlt 3–5 s) coincide with
lane crash/restart; two (Phi-4-reasoning, ttlt 390 s / 480 s) look like a lane
being torn down (drain/eviction or crash) while still generating. Worth
watching in the next run — if Phi-4 long generations keep getting cut,
check the planner's drain logic against `requests_running > 0`.

## Tooling fixes that came out of this analysis

- `benchmarks/benchmark_logos.py`: exception class is now recorded in the
  `error` column (timeouts were logged as empty strings).
- `POST /logosdb/get_ollama_vram_stats` now supports
  `{"resolution": "second", "after_snapshot_id": N}` for ≥1 Hz VRAM polling
  during benchmarks (pair with `status_refresh_interval_seconds: 1` and
  `gpu_poll_interval: 1` in the workernode config).
- Lane "Unload" button / `POST /logosdb/providers/logosnode/lanes/delete`
  allows resetting lane state between benchmark scenarios.
