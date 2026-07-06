# Which parameters control model-switching speed?

This answers the benchmarking question "which parameter(s) are responsible for
how fast Logos switches a lane from one model to another". The switch timeline
has four phases — **decision → drain/unload → load/wake → ready** — and each
phase is paced by its own knobs.

## TL;DR

The dominant levers, in order of impact:

1. **Cold-load time of the model itself** (weights copy + torch.compile + CUDA
   graph capture) — minutes for large models; not a config knob, but the reason
   `LANE_LOAD_COMMAND_TIMEOUT_S` is 30 min.
2. **`cycle_seconds` (planner cadence, default 10 s)** — upper bound on how
   long a demand signal waits before the planner even decides. Queued requests
   tickle the planner early (`hint_capacity_needed`), so the effective decision
   latency for a queued request is usually < 1 s.
3. **`IDLE_SLEEP_L1` (120 s)** — how long a lane must idle before it is put to
   sleep. Directly controls how often a subsequent request pays the wake cost
   instead of hitting a hot lane.
4. **Competitive ratios + tenure** (`WAKE/LOAD/DRAIN_COMPETITIVE_RATIO`,
   `LANE_MIN_TENURE_SECONDS`) — anti-thrashing brakes. They intentionally
   *slow down* switching when demand is mixed; lowering them makes switching
   more eager but risks flip-flopping.
5. **Worker telemetry cadence** (`heartbeat_interval_seconds`,
   `status_refresh_interval_seconds`, `gpu_poll_interval`) — how quickly the
   planner *sees* state changes; it cannot react faster than it observes.

## Orchestrator: decision phase (capacity planner)

`logos-orchestrator/src/logos/capacity/capacity_planner.py`

| Parameter | Default | Effect on switching speed |
|---|---|---|
| `cycle_seconds` (ctor, line 228) | 10 s | Planner wakes at most this often. Queued requests fire an event-driven tickle, so reaction to *new* demand is near-instant; periodic effects (idle sleep) wait up to one cycle. |
| `IDLE_SLEEP_L1` (line 64) | 120 s | Idle time before sleep level 1 (frees KV cache, keeps weights). Shorter ⇒ VRAM is reclaimed sooner ⇒ next model loads faster, but more wake costs. |
| `IDLE_SLEEP_L2` (line 78) | 86 400 s | Effectively disabled — sleep level 2 would discard fast-wake state. |
| `TARGET_ACTION_COST_S` (line 107) | wake 2 s, load 90 s | Cost estimates used to *rank* candidate actions; bias which switch (wake vs. cold load) wins. |
| `VICTIM_ACTION_COST_S` (line 108) | sleep_l1 1 s, sleep_l2 1.5 s, stop 30 s | Estimated cost of evicting the victim lane. |
| `WAKE_COMPETITIVE_RATIO` (line 86) | 1.5 | Demand for the incoming model must beat the eviction set by 50 % before a wake-with-eviction happens. Higher ⇒ slower, more conservative switching. |
| `LOAD_COMPETITIVE_RATIO` (line 87) | 2.0 | Same, for cold loads (2×). |
| `DRAIN_COMPETITIVE_RATIO` (line 88) | 3.0 | Same, for draining a *busy* lane (3×) — prevents flip-flop. |
| `LANE_MIN_TENURE_SECONDS` (line 143) | 5 s | A freshly woken/loaded lane may not be drained for 5 s. |
| `LANE_COLD_WAITER_TENURE_SECONDS` (line 148) | 15 s | Extended tenure when a queued request triggered the wake. |
| `BUSY_DRAIN_POLL_SECONDS` (line 218) | 5 s | Poll interval while waiting for a busy victim lane to finish its requests. |
| `REQUEST_WAKE_TIMEOUT_SECONDS` (line 210) | 30 s | How long a request waits for a wake to complete before it is failed over. |
| `WAKE_FAILURE_COOLDOWN_SECONDS` (line 211) | 15 s | Retry suppression after a failed wake. |
| `LOAD_FAILURE_COOLDOWN_SECONDS` (line 216) | 120 s | Retry suppression after a structural load failure — a model that just failed cannot be retried for 2 min. |
| `LANE_LOAD_COMMAND_TIMEOUT_S` (line 136) | 1800 s | RPC timeout for a cold load; sized for large models (≥ 6 min load). |

Related: `logos-orchestrator/src/logos/pipeline/pipeline.py:276`
`_CONTEXT_RESOLVE_TIMEOUT_S = 180 s` — the per-request budget for the planner
to produce *any* usable lane. If contention or load failures exceed this, the
request fails with HTTP 503 "Failed to resolve execution context" (observed in
the first 5-LLM benchmark).

## Workernode: execution phase

`logos-workernode/logos_worker_node/` (`lane_manager.py`, `models.py`)

| Parameter | Default | Effect |
|---|---|---|
| `heartbeat_interval_seconds` (models.py:336) | 5 s | Liveness heartbeat → how fast the orchestrator notices a dead/alive worker. |
| `status_refresh_interval_seconds` (models.py:343) | 15 s | Periodic full runtime-status push on *idle* workers (state changes push immediately, checked every 1 s). Determines how quickly the planner sees VRAM/lane telemetry when nothing is changing. |
| `gpu_poll_interval` (models.py:263) | 5 s | nvidia-smi poll cadence — resolution of the VRAM numbers the planner budgets with. |
| `_RESTART_TIMEOUT` (lane_manager.py:39) | 90 s | Spawn + preload guard for lane (re)starts. |
| `_CRASH_RESTART_COOLDOWN_S` (lane_manager.py:48) | 30 s | Wait between crash-recovery attempts. |
| `_STUCK_DURATION_SECONDS` (lane_manager.py:289) | 60 s | No-token-progress threshold before a lane is declared stuck. |

The actual sleep→wake transition of a vLLM lane takes ~1–3 s (sleep level 1);
a cold start takes from ~30 s (small AWQ model) to several minutes (35B-class
models with torch.compile + CUDA graphs).

## Practical recipes

- **Benchmark "how fast can it switch"**: lower `IDLE_SLEEP_L1` (e.g. 30 s) to
  force frequent sleep/wake cycles, and set
  `status_refresh_interval_seconds: 1` + `gpu_poll_interval: 1` on the
  workernode so the telemetry (and the VRAM statistics, see
  `resolution: "second"` on `POST /logosdb/get_ollama_vram_stats`) tracks the
  switch at 1 Hz.
- **Make switching more eager** (lower latency, more thrash risk): reduce
  `WAKE_COMPETITIVE_RATIO` / `LOAD_COMPETITIVE_RATIO` and
  `LANE_MIN_TENURE_SECONDS`.
- **Make switching cheaper to observe**: the planner can only act on what the
  worker reports — on test nodes the telemetry intervals are the first thing
  to turn down.
