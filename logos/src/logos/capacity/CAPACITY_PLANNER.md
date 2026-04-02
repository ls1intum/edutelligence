# Logos Capacity Planner

**Location:** `src/logos/capacity/`

The capacity planner is a background service that keeps GPU memory efficiently occupied across all connected worker nodes. It runs on a fixed 30-second cycle, decides which model lanes to wake, load, sleep, or stop, and validates that every action fits within physical GPU memory before executing it.

---

## Table of Contents

1. [Architecture overview](#1-architecture-overview)
2. [Demand tracking and scoring](#2-demand-tracking-and-scoring)
3. [Effective demand — the decision metric](#3-effective-demand--the-decision-metric)
4. [Lane lifecycle and states](#4-lane-lifecycle-and-states)
5. [Planner cycle — per-cycle pipeline](#5-planner-cycle--per-cycle-pipeline)
6. [Idle tier management](#6-idle-tier-management)
7. [Demand-based actions — wake and cold load](#7-demand-based-actions--wake-and-cold-load)
   - 7.1 [Why comparative demand instead of absolute thresholds](#71-why-comparative-demand-instead-of-absolute-thresholds)
   - 7.2 [The three-way decision tree](#72-the-three-way-decision-tree)
   - 7.3 [GPU-aware eviction set algorithm](#73-gpu-aware-eviction-set-algorithm)
   - 7.4 [Cold-load GPU placement](#74-cold-load-gpu-placement)
   - 7.5 [Capability seeding on empty workers](#75-capability-seeding-on-empty-workers)
8. [Demand-preemptive drain](#8-demand-preemptive-drain)
9. [Preemptive load-then-sleep](#9-preemptive-load-then-sleep)
10. [Request-time lane preparation](#10-request-time-lane-preparation)
11. [VRAM budget validation and the VRAM ledger](#11-vram-budget-validation-and-the-vram-ledger)
12. [Tensor-parallel topology](#12-tensor-parallel-topology)
13. [Additive vs declarative lane commands](#13-additive-vs-declarative-lane-commands)
14. [Concurrency model](#14-concurrency-model)
15. [Constants reference](#15-constants-reference)
16. [File reference](#16-file-reference)

---

## 1. Architecture overview

```
pipeline.py  ──record_request()──►  DemandTracker
                                          │ decay_all() every cycle
                                          ▼
                                   CapacityPlanner._run_cycle()
                                          │
                        ┌─────────────────┼─────────────────┐
                        ▼                 ▼                  ▼
               _compute_idle_      _compute_demand_   _compute_preemptive_
               actions()           actions()          sleep_actions()
                        │                 │                  │
                        └─────────────────┴─────────────────┘
                                          │
                                  _validate_vram_budget()
                                          │
                              _execute_action_with_confirmation()
                                          │
                                   LogosNodeFacade
                                   (add_lane / apply_lanes / wake / sleep / stop)
```

The planner never blocks the request path. It issues background decisions every 30 seconds. Urgent wake/load work driven by live requests is handled by the separate `prepare_lane_for_request()` fast path described in [section 10](#10-request-time-lane-preparation).

---

## 2. Demand tracking and scoring

**File:** [`demand_tracker.py`](demand_tracker.py)

Every time the pipeline routes a request to a model, it calls `DemandTracker.record_request(model_name)`. This increments an in-memory float score:

```
score[model] += 1.0        (normal)
score[model] += 1.5        (during burst: ≥5 requests in 10 seconds)
```

Burst scaling (`BURST_DEMAND_MULTIPLIER = 1.5`) provides super-linear amplification during high-traffic windows, making it harder for the planner to evict a model that is about to be hammered further.

**Latent demand** — if the scheduler's availability-penalty logic directs a request to a *different* model than what classification preferred, it calls `record_latent_demand()` which adds `0.5` (half-weight). This allows a model to build pressure and eventually justify a lane even when it is not currently available.

**Exponential decay** — once per planner cycle `decay_all()` multiplies every score by `DECAY_FACTOR = 0.95`. After N cycles with no new requests, a score of 1.0 decays to `0.95^N`. After ~140 cycles (~70 minutes at 30s/cycle) a score of 1.0 reaches the cleanup floor of `0.01` and is removed.

This means the score naturally reflects *recency-weighted* traffic volume: a model that got 20 requests an hour ago has a much lower score than one that got 5 requests 30 seconds ago.

Key methods:
- `record_request(model_name)` — `demand_tracker.py:36`
- `record_latent_demand(model_name)` — `demand_tracker.py:61`
- `decay_all()` — `demand_tracker.py:75`
- `get_ranked_models()` — `demand_tracker.py:101`
- `get_score(model_name)` — `demand_tracker.py:108`

---

## 3. Effective demand — the decision metric

**Method:** `_effective_demand(model_name, lane)` — `capacity_planner.py:784`

The raw demand score only captures *historical* traffic (with decay). It does not immediately see that a model has 12 requests queued right now. To bridge this gap, every decision in the planner uses **effective demand**:

```
effective_demand = score + QUEUE_WEIGHT × lane.queue_waiting
```

Where `QUEUE_WEIGHT = 0.25`. A model with score `0.8` and `8` requests currently queued has effective demand `0.8 + 0.25×8 = 2.8`.

**Why this matters:** consider two models under GPU pressure:
- Model A: score `3.0`, queue `0` → eff `3.0`
- Model B: score `0.5`, queue `16` → eff `4.5`

An absolute-threshold system would promote model A. The comparative effective-demand system correctly identifies that model B has a much larger current backlog and is the one starving.

Queue waiting is captured in `LaneSchedulerSignals.queue_waiting` which is the vLLM engine's reported backlog. It is only available for models that already have a lane; for models being cold-loaded from scratch, the queue component is zero and the score alone drives the decision.

---

## 4. Lane lifecycle and states

A **lane** is an independent model-serving process on a worker node. Each lane has two orthogonal state axes:

| Axis | States | Meaning |
|------|--------|---------|
| `runtime_state` | `cold`, `starting`, `loaded`, `running`, `sleeping`, `stopped`, `error` | Whether the process exists and is serving |
| `sleep_state` | `unsupported`, `awake`, `sleeping` | Whether vLLM KV cache has been released to GPU free pool |

**Sleep** (vLLM only) is the key memory optimization. When a vLLM lane sleeps:
- The KV cache blocks (~90% of VRAM) are released back to the GPU free pool
- The model weights stay in VRAM (~10% residual: `sleeping_residual_mb`)
- Wake time is ~2s instead of ~45s cold start
- The GPU sees `current_vram - sleeping_residual_mb` freed

The planner tracks per-lane idle duration (`_lane_idle_since`) and sleep duration (`_lane_sleep_since`) in `capacity_planner.py:122-127`.

---

## 5. Planner cycle — per-cycle pipeline

**Method:** `_run_cycle()` — `capacity_planner.py:212`

Each 30-second cycle executes in order:

1. **Stale VRAM reservation cleanup** — `VRAMLedger.cleanup_stale()`: removes any reservations that have been held for more than 10 minutes, a safety net for operations that crashed without releasing.

2. **Demand decay** — `DemandTracker.decay_all()`: multiplies all scores by 0.95.

3. **Prometheus gauge updates** — exports current scores via `DEMAND_SCORE` and `DEMAND_RAW_COUNT` labels.

4. **Cluster summary log** — `_log_cluster_summary()` at `capacity_planner.py:284`: prints a colored terminal overview with per-lane metrics (state, VRAM, active requests, queue depth, KV cache %, TTFT p95, demand score).

5. **Per-provider processing** (skips providers that haven't sent their first status report after connect):
   - `_update_idle_tracking()` — updates `_lane_idle_since` and `_lane_sleep_since`, cleans up lanes that disappeared, and completes/cancels demand-preemptive drains.
   - `_compute_idle_actions()` — generates `sleep_l1` / `sleep_l2` actions for lanes idle longer than the thresholds.
   - `_compute_demand_actions()` — generates `wake` / `load` actions using the comparative demand algorithm.
   - `_compute_demand_drain_actions()` — initiates graceful drains on busy lanes for starving models (side-effect only; no returned actions).
   - `_compute_preemptive_sleep_actions()` — generates `load` + immediate `sleep_l1` pairs for pre-warming stopped models.

6. **VRAM budget validation** — `_validate_vram_budget()`: runs the full action list through the VRAM ledger, dropping actions that would exceed physical memory.

7. **Serialized execution** — each validated action acquires its per-lane lock, then calls `_execute_action_with_confirmation()` which issues the command to the worker node facade and waits for the worker to confirm the state transition.

---

## 6. Idle tier management

**Method:** `_compute_idle_actions()` — `capacity_planner.py:1077`

The background planner never *stops* lanes proactively. It only *sleeps* them. Lane removal happens only when a live request or cold load actually needs VRAM (see section 10).

| Timer | Action | Condition |
|-------|--------|-----------|
| `IDLE_SLEEP_L1 = 300s` | `sleep_l1` | vLLM lane awake, no active requests for 5 minutes |
| `IDLE_SLEEP_L2 = 600s` | `sleep_l2` | vLLM lane already in L1 sleep for 10 further minutes |

Sleep L2 offloads the model weights from VRAM to CPU RAM (or disk), further reducing GPU residency at the cost of a longer wake time (~10-20s instead of ~2s).

The idle clock (`_lane_idle_since`) resets whenever a lane receives any request traffic. It also resets on wake, since a freshly-woken lane is counted as active at the moment it wakes.

---

## 7. Demand-based actions — wake and cold load

**Method:** `_compute_demand_actions()` — `capacity_planner.py:1221`

### 7.1 Why comparative demand instead of absolute thresholds

Earlier versions used fixed thresholds: `DEMAND_WAKE_THRESHOLD = 1.0`, `DEMAND_LOAD_THRESHOLD = 2.0`. This broke under high load: if every model accumulated scores well above the thresholds, the planner would thrash — evicting model A to load model B, then evicting model B next cycle to load model C, because all scores were "above the threshold".

The fix: **thresholds only apply when VRAM is freely available**. When eviction is required, the decision becomes comparative — the target model must outweigh the models it would displace by a safety margin (competitive ratio).

The floor thresholds (`DEMAND_WAKE_FLOOR = 0.5`, `DEMAND_LOAD_FLOOR = 1.0`) remain only as noise filters for the free-VRAM path. Practically, `DEMAND_LOAD_FLOOR = 1.0` means "one real request is enough to cold-load a model when VRAM is free". The competitive ratios prevent thrashing under contention.

### 7.2 The three-way decision tree

For each model with a non-zero demand score, in ranked order:

```
For model M with effective_demand = eff:

  (A) Find minimum eviction set to free required VRAM
       │
       ├── eviction_set = []   (no eviction needed — VRAM is free)
       │    └── act if eff ≥ FLOOR  (immediate; no competitive check)
       │
       ├── eviction_set = [lane1, lane2, ...]  (eviction required)
       │    └── act if eff > max(eviction scores) × COMPETITIVE_RATIO
       │         ├── YES → prepend eviction actions, then wake/load
       │         └── NO  → skip (M doesn't outweigh what it displaces)
       │
       └── eviction_set = None  (can't free enough VRAM at all)
            └── skip
```

**Wake path** uses `WAKE_COMPETITIVE_RATIO = 1.2`: target must beat the most-valued evicted model by 20%. This is lenient because a sleeping lane only costs its residual VRAM, so wakes are cheap.

**Cold load path** uses `LOAD_COMPETITIVE_RATIO = 1.5`: target must beat the most-valued evicted model by 50%. This is stricter because loading a cold model costs a full 30-90 second operation and the full model VRAM allocation.

**Empty worker** (`eviction_set = []` always): a worker with no lanes has no models to evict, so every in-demand model above the floor is loaded immediately. This is the "encourage adding new lanes" behavior.

### 7.3 GPU-aware eviction set algorithm

**Method:** `_find_eviction_set()` — `capacity_planner.py:834`

Worker nodes expose GPU devices as `tp1`, `tp2`, etc. (slot indices, not absolute GPU numbers). A TP=2 model with its weights split across GPUs {0, 1} holds `total_vram_mb / 2` on **each** of those GPUs. When it sleeps, it frees `(loaded_mb - residual_mb) / 2` on each GPU.

This matters because a model on GPUs {2, 3} cannot help load a model that needs to go onto GPUs {0, 1} — the freed VRAM is on the wrong physical chips.

The algorithm:

1. Compute `per_gpu_deficit[gpu_id] = max(0, per_gpu_needed × safety_margin - per_gpu_free[gpu_id])` for each GPU in `required_gpus`.

2. Build candidate list: idle lanes whose GPU devices overlap with `required_gpus`. Skip busy lanes (`active_requests > 0` or `queue_waiting > 0`) and lanes in load cooldown.

3. For each candidate, determine the freed VRAM it contributes **per GPU**:
   - `sleep_l1` (preferred): `(current_vram - residual_mb) / tp` per overlapping GPU
   - `stop` (fallback for already-sleeping lanes): `residual_mb / tp` per overlapping GPU

4. Sort candidates by `effective_demand` ascending — sacrifice the least-valued models first.

5. Greedy covering: pick candidates until `per_gpu_deficit[g] ≤ 0` for every required GPU.

6. Return the chosen set, or `None` if deficits cannot be fully covered.

The key insight: freed VRAM is split by TP count across the GPUs the lane occupies. Only overlapping GPUs count. A lane on disjoint GPUs is skipped entirely.

The `claimed_victims` set in `_compute_demand_actions` (line ~1270) prevents the same lane from being evicted twice in one cycle for two different competing loads.

### 7.4 Cold-load GPU placement

**Method:** `_pick_cold_load_placement()` — `capacity_planner.py:947`

A cold load needs `tp` GPUs. We don't know in advance which GPUs to use, so we try every combination of `tp` GPUs from all available GPUs:

```
for gpu_combo in combinations(all_gpu_ids, tp):
    per_gpu_deficit = { g: max(0, per_gpu_needed × margin - per_gpu_free[g]) for g in combo }
    eviction_set = _find_eviction_set(provider_id, gpu_combo, per_gpu_deficit, ...)
    if eviction_set is not None:
        record candidate (gpu_combo, eviction_set, max_victim_score)

return the candidate with lowest max_victim_score
```

By picking the placement whose eviction set has the **lowest maximum victim score**, we minimize the value of what we sacrifice. We'd rather evict a model with demand `0.2` than one with demand `2.0`, even if the VRAM numbers are similar.

Falls back to aggregate (non-per-GPU) accounting when no per-device VRAM info is available from the worker snapshot.

### 7.5 Capability seeding on empty workers

When `lanes = []` (worker connected but no models loaded), the main ranked-model loop already handles cold loads via the placement algorithm — `eviction_set` will always be empty on a worker with nothing loaded. The dedicated capability seeding block at `capacity_planner.py:1450` provides a fallback for the edge case where `_pick_cold_load_placement` returns `None` despite no contention (e.g. missing per-GPU device info). Any model with `eff ≥ DEMAND_LOAD_FLOOR` and capabilities declared by the worker is loaded immediately.

---

## 8. Demand-preemptive drain

**Methods:** `_compute_demand_drain_actions()` — `capacity_planner.py:1475`, `_should_initiate_drain()` — `capacity_planner.py:3015`

Eviction via `sleep_l1` or `stop` only works on **idle** lanes. If a high-demand model can't get VRAM because another model is actively serving requests, we must wait. The drain mechanism handles this gracefully:

1. A model M has demand ≥ `DRAIN_COMPETITIVE_RATIO × 2.0` but no usable lane and no VRAM.
2. The planner finds lane L of another model B that is actively serving and holds the required VRAM.
3. `_should_initiate_drain()` checks four conditions:
   - **Competitive demand**: `eff(M) > eff(B) × DRAIN_COMPETITIVE_RATIO` — M must be 2× more demanded than B. This high ratio prevents flip-flopping.
   - **Asymmetric cooldown**: newly cold-loaded lanes are protected for 30s (`DRAIN_MIN_COLD_LOADED_SECONDS`); freshly woken lanes for 8s (`DRAIN_MIN_WOKEN_SECONDS`). This prevents draining a lane that hasn't had time to serve a single batch.
   - **GPU overlap**: B must share at least one GPU with where M would go. Draining a lane on disjoint GPUs doesn't help.
   - **VRAM feasibility**: sleeping B must free enough VRAM to fit M.
4. If all four pass, `_initiate_drain()` marks lane B as cold (stops new request routing) and records it in `_draining_lanes`.
5. In the request path (`_ensure_request_capacity()`), when `_next_request_reclaim_action()` returns `None`, the reclaim loop checks `_find_draining_lane()` and awaits `_drain_lane()` — busy-waiting for B to drain naturally as its in-flight requests finish.
6. Drain timeout is `DRAIN_TIMEOUT_SECONDS = 60s`. If B doesn't drain in time, `_cancel_drain()` restores its routing.

The `DRAIN_COMPETITIVE_RATIO = 2.0` is intentionally high. At 1.2× or 1.5×, models with similar traffic levels would drain each other constantly. At 2×, a drain only fires when M is genuinely starving relative to B.

---

## 9. Preemptive load-then-sleep

**Method:** `_compute_preemptive_sleep_actions()` — `capacity_planner.py:1557`

**Problem:** a model was previously loaded, accumulated sleeping residual weights in GPU memory, but its lane was stopped. The next request pays full cold-start cost (~45s) instead of wake cost (~2s).

**Solution:** reload the model and immediately sleep it, so the next request pays only wake cost.

**Decision logic:**

1. Skip if `available_vram / total_vram < 0.20` (VRAM pressure guard — don't preemptively load when the GPU is almost full).

2. Candidates: stopped models with a known `sleeping_residual_mb > 0` and `engine == "vllm"`, sorted by demand score descending. Consider up to `PREEMPTIVE_SLEEP_MAX_MODELS = 3` per cycle.

3. **Pre-sleep idle awake neighbours**: before loading the candidate, collect all vLLM lanes that are awake with zero active requests and haven't yet reached the 5-minute idle threshold. These lanes are holding their full KV-cache allocation even though they're doing nothing. vLLM probes all free GPU memory at startup to decide how many KV blocks to allocate — an awake idle lane's KV pool will crowd out the new model's initialization even if the aggregate VRAM check passes. We emit `sleep_l1` for every such lane before the `load`.

4. Load cost uses `_estimate_action_vram()` (base + KV), not just base residency. After the load+sleep cycle, the net cost is just the sleeping residual, not the full model.

5. Guard: `(remaining_vram - residual) / total_vram ≥ 0.20` after the load settles.

6. Emit the sequence: `[sleep_l1 neighbours..., load, sleep_l1 candidate]`. The ordering ensures VRAM budget validation sees the freed space before the consumed space.

The `_preemptive_sleep_ready` set tracks lanes that were loaded by the preemptive path and haven't been slept yet, so the follow-up `sleep_l1` action can be emitted correctly.

---

## 10. Request-time lane preparation

**Method:** `prepare_lane_for_request()` — `capacity_planner.py:461`

This path runs synchronously with an incoming request, not in the background cycle. It is called when the scheduler selects a provider but the target lane is cold, sleeping, or absent.

### Flow

```
request arrives
       │
       ▼
_pick_request_target_lane()
       │
       ├── lane found, state = loaded/running
       │     └── _prepare_existing_lane() → immediate return (no-op)
       │
       ├── lane found, state = sleeping
       │     ├── check wake_failure_cooldown (15s after recent failed wake)
       │     ├── _ensure_request_capacity() — reclaim VRAM if needed
       │     └── execute wake action (timeout = max(caller_timeout, 30s))
       │
       └── no lane found
             └── _model_prepare_lock(provider_id, model_name)
                   │ (serializes concurrent requests for same model)
                   ├── re-check (another request may have loaded it)
                   └── _cold_load_for_request()
                         ├── _ensure_request_capacity() — reclaim VRAM
                         └── execute load action (timeout = max(caller_timeout, 180s))
```

### Per-model prepare lock

`_model_prepare_lock(provider_id, model_name)` at `capacity_planner.py:175` is an `asyncio.Lock` keyed by `(provider_id, model_name)`. Two concurrent requests for the same cold model are serialized: the first triggers the load, the second re-checks after acquiring the lock and finds the lane already loaded.

Two requests for *different* models proceed concurrently — different keys means different locks.

### VRAM reclaim loop

`_ensure_request_capacity()` at `capacity_planner.py:1765` loops until enough VRAM is available:

1. Check current available VRAM (ledger-aware, per-GPU if placement is known).
2. If sufficient, return `True`.
3. Call `_next_request_reclaim_action()` which picks the least-destructive idle lane to sleep or stop.
4. Execute the reclaim action and loop.
5. If no reclaim candidate is available, check for a pending drain (`_find_draining_lane`) and wait for it.
6. If still no VRAM, return `False` (request fails gracefully).

`_next_request_reclaim_action()` at `capacity_planner.py:1885` prefers `sleep_l1` over `stop`, prefers lanes on overlapping GPUs, and prefers the minimum set that satisfies the shortfall (`_best_reclaim_plan`).

### Wake timeout

`REQUEST_WAKE_TIMEOUT_SECONDS = 30.0`. vLLM sleep wakes typically complete in 1-5 seconds; 30s is a generous upper bound. A failed wake triggers `_mark_wake_failure()` which enforces a 15-second cooldown (`WAKE_FAILURE_COOLDOWN_SECONDS`) before the lane is retried.

---

## 11. VRAM budget validation and the VRAM ledger

**Files:** [`vram_ledger.py`](vram_ledger.py), **Method:** `_validate_vram_budget()` — `capacity_planner.py`

### Problem: concurrent check-then-act races

Without synchronization, two simultaneous load operations can both check available VRAM, both conclude there is room, and both proceed — OOM-killing each other. Standard asyncio cannot prevent this because an `await` between the check and the reservation allows another coroutine to run.

### Solution: synchronous atomic reserve

`VRAMLedger.try_reserve_atomic()` at `vram_ledger.py:138` performs the availability check and the reservation in a single synchronous method (no `await`). In a cooperative asyncio event loop, a synchronous method cannot be interrupted by another coroutine — the check and the commit are atomic.

```python
reservation_id = ledger.try_reserve_atomic(
    provider_id, lane_id, "load",
    vram_mb=estimated_mb,
    raw_available_mb=capacity.available_vram_mb,
    safety_margin=1.1,
    gpu_devices="0,1",
    per_gpu_free={0: 12000.0, 1: 11500.0},
)
# None = denied (not enough VRAM)
# str  = reservation_id, must be released when op completes
```

Reservations track GPU devices explicitly so per-GPU feasibility checks see in-flight operations on the same physical GPU.

### Stale reservation cleanup

Reservations are released when `_execute_action_with_confirmation()` returns (success or failure). As a safety net, `cleanup_stale(max_age_seconds=600)` runs at the top of every planner cycle and removes reservations older than 10 minutes.

### VRAM estimation

`_estimate_action_vram(action, profile, capacity)` distinguishes:
- **wake**: `loaded_mb - sleeping_residual_mb` (only the KV cache re-allocation)
- **load**: `base_residency_mb + kv_cache_estimate_mb` — `_estimate_model_loaded_vram()` + `_compute_kv_cache_bytes(profile)` both contribute. For TP > 1, add `TP_OVERHEAD_RATIO = 10%` for NCCL communication buffers and duplicated embedding/output layers.
- **sleep/stop**: negative cost (frees VRAM) — `_validate_vram_budget` accounts for freed VRAM when sleep and load actions are in the same batch.

---

## 12. Tensor-parallel topology

**Constant:** `TP_OVERHEAD_RATIO = 0.10` — `capacity_planner.py:95`

A TP=K model with total weight size W distributes W/K weights onto each of K GPUs but also allocates:
- NCCL ring buffers proportional to K
- Duplicate embedding and LM-head layers (not sharded)

The planner accounts for this by multiplying the load cost by `(1 + TP_OVERHEAD_RATIO)` for models with `tensor_parallel_size > 1`:

```python
if tp > 1:
    load_cost *= (1.0 + self.TP_OVERHEAD_RATIO)  # capacity_planner.py:1382
```

For VRAM deficit calculations, the total cost is then distributed evenly: `per_gpu_needed = load_cost / tp`. This ensures each individual GPU in the TP group has sufficient free memory, not just the aggregate.

GPU device IDs come from worker node status reports as `gpu_devices` fields on lanes and device snapshots. The planner parses them with `_parse_gpu_device_ids()` at `capacity_planner.py:1011` (comma-separated integers: `"0,1"` → `(0, 1)`).

---

## 13. Additive vs declarative lane commands

**Environment variable:** `LOGOS_USE_ADDITIVE_LOADS` (default: `true`)

The planner supports two modes for sending load commands to worker nodes:

| Mode | Command | Behavior |
|------|---------|---------|
| Additive (`true`) | `add_lane` | Adds a single new lane without touching existing lanes |
| Declarative (`false`) | `apply_lanes` | Sends the full desired state; worker reconciles additions and removals |

Additive mode is the default and is preferred because it is safe for concurrent multi-lane workers: two independent load operations can both issue `add_lane` without clobbering each other's state. Declarative mode requires careful state merging (`_build_desired_lane_set()`) to avoid races where one `apply_lanes` call removes a lane that was being added by a concurrent operation.

`_use_additive_loads` is checked in `_execute_action_with_confirmation()` when building the facade call.

---

## 14. Concurrency model

The planner runs as a single asyncio task (`capacity-planner`). All decisions within a planner cycle are single-threaded. Concurrent request-path calls (`prepare_lane_for_request`) introduce the following synchronization points:

| Mechanism | Location | Purpose |
|-----------|----------|---------|
| `_model_prepare_lock(provider_id, model_name)` | `capacity_planner.py:175` | Serializes cold loads for the same model; concurrent loads for different models remain parallel |
| `_lane_lock(provider_id, lane_id)` | `capacity_planner.py:2980` | Serializes all operations on a single lane (planner + request path cannot both operate on the same lane simultaneously) |
| `VRAMLedger.try_reserve_atomic()` | `vram_ledger.py:138` | Atomic check-and-reserve prevents double-booking of VRAM |
| `_inflight_desired` dict | `capacity_planner.py:145` | Tracks in-flight `apply_lanes` mutations so concurrent declarative calls build from fresh state |
| `_draining_lanes` dict | `capacity_planner.py:159` | Tracks active drains so the request path can await them instead of issuing conflicting commands |

The `DemandTracker` uses its own `threading.Lock` because demand recording happens from the pipeline, which may run in a different thread than the asyncio event loop.

---

## 15. Constants reference

All constants are defined as class variables on `CapacityPlanner` in `capacity_planner.py:59-104`.

| Constant | Value | Meaning |
|---------|-------|---------|
| `IDLE_SLEEP_L1` | 300s | Awake idle → sleep L1 |
| `IDLE_SLEEP_L2` | 600s | Sleep L1 idle → sleep L2 |
| `DEMAND_WAKE_FLOOR` | 0.5 | Minimum eff demand to wake when VRAM is free |
| `DEMAND_LOAD_FLOOR` | 1.0 | Minimum eff demand to cold load when VRAM is free |
| `WAKE_COMPETITIVE_RATIO` | 1.2 | Wake eviction: target must beat victims by 20% |
| `LOAD_COMPETITIVE_RATIO` | 1.5 | Load eviction: target must beat victims by 50% |
| `DRAIN_COMPETITIVE_RATIO` | 2.0 | Drain eviction: target must 2× outweigh victim |
| `QUEUE_WEIGHT` | 0.25 | Queue contribution to effective demand |
| `DRAIN_TIMEOUT_SECONDS` | 60s | Max wait for a lane to drain |
| `DRAIN_MIN_COLD_LOADED_SECONDS` | 30s | Cooldown: don't drain a freshly cold-loaded lane |
| `DRAIN_MIN_WOKEN_SECONDS` | 8s | Cooldown: don't drain a freshly woken lane |
| `GPU_CACHE_HIGH` | 85% | KV cache % above which reconfigure is considered |
| `VRAM_SAFETY_MARGIN` | 1.1 | 10% safety buffer on all VRAM estimates |
| `TP_OVERHEAD_RATIO` | 0.10 | 10% extra VRAM for TP > 1 NCCL buffers |
| `PREEMPTIVE_SLEEP_MIN_FREE_VRAM_RATIO` | 0.20 | Skip preemptive load if GPU < 20% free |
| `PREEMPTIVE_SLEEP_MAX_MODELS` | 3 | Max preemptive loads per cycle |
| `REQUEST_WAKE_TIMEOUT_SECONDS` | 30s | Max wait for a sleeping lane to wake at request time |
| `WAKE_FAILURE_COOLDOWN_SECONDS` | 15s | Skip lane after a failed wake for 15s |
| `LOAD_COOLDOWN_SECONDS` | 60s (env) | Don't evict a lane loaded in the last 60s |

`DemandTracker` constants (`demand_tracker.py:17-23`):

| Constant | Value | Meaning |
|---------|-------|---------|
| `DECAY_FACTOR` | 0.95 | Per-cycle score multiplier |
| `BURST_WINDOW_SECONDS` | 10s | Window for burst detection |
| `BURST_THRESHOLD` | 5 | Requests in window to trigger burst scaling |
| `BURST_DEMAND_MULTIPLIER` | 1.5 | Demand increment during a burst |
| `LATENT_DEMAND_WEIGHT` | 0.5 | Half-weight increment for latent demand |

---

## 16. File reference

| File | Role |
|------|------|
| [`capacity_planner.py`](capacity_planner.py) | Main planner class; all scheduling logic |
| [`demand_tracker.py`](demand_tracker.py) | Per-model exponential-decay demand scoring |
| [`vram_ledger.py`](vram_ledger.py) | Atomic VRAM reservation ledger; per-GPU tracking |
| [`../../../tests/unit/capacity/test_capacity_planner.py`](../../../tests/unit/capacity/test_capacity_planner.py) | Unit tests covering all major decision paths |
| [`../../../tests/smoke/test_capacity_planner_smoke.py`](../../../tests/smoke/test_capacity_planner_smoke.py) | End-to-end smoke tests against a live deployment |
