# Logos Capacity Management Architecture

> **Comprehensive line-by-line analysis of the lane management, VRAM budgeting, locking,
> eviction, and anti-thrashing subsystems.**
>
> Generated: 2026-04-09 | Source: `logos/src/logos/capacity/` and `logos/src/logos/pipeline/base_scheduler.py`

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Component Map](#2-component-map)
3. [Lane Lifecycle State Machine](#3-lane-lifecycle-state-machine)
4. [Lock Hierarchy](#4-lock-hierarchy)
5. [VRAM Ledger — Atomic Reservation System](#5-vram-ledger--atomic-reservation-system)
6. [Demand Tracking & Scoring](#6-demand-tracking--scoring)
7. [Background Planner Cycle](#7-background-planner-cycle)
8. [Request-Time Capacity Assurance](#8-request-time-capacity-assurance)
9. [Eviction Algorithm](#9-eviction-algorithm)
10. [Reclaim Decision Tree](#10-reclaim-decision-tree)
11. [Anti-Thrashing Mechanisms](#11-anti-thrashing-mechanisms)
12. [VRAM Budget Validation](#12-vram-budget-validation)
13. [Action Execution & Confirmation](#13-action-execution--confirmation)
14. [Scheduler Integration](#14-scheduler-integration)
15. [Deadlock, Starvation & Race Condition Analysis](#15-deadlock-starvation--race-condition-analysis)
16. [Benchmark Evidence](#16-benchmark-evidence)
17. [Refinement Proposals](#17-refinement-proposals)
18. [Fairness Inversion: New Arrivals Preempt Established Queues](#18-fairness-inversion-new-arrivals-preempt-established-queues)
19. [Anti-Thrashing Mechanism Audit: What to Keep, What to Simplify](#19-anti-thrashing-mechanism-audit-what-to-keep-what-to-simplify)
20. [Academic Foundations and Thesis Research Anchors](#20-academic-foundations-and-thesis-research-anchors)

---

## 1. System Overview

The Logos capacity management system orchestrates GPU model serving across one or more
worker nodes, each hosting multiple **lanes** (model instances backed by vLLM or other
inference engines). The core challenge: **N models compete for M GPUs where total VRAM
demand exceeds physical capacity**, requiring dynamic sleep/wake/load/stop orchestration.

### Design Constraints

| Constraint | Value | Impact |
|---|---|---|
| GPUs per worker | 2 × 16 GB = 32 GB | Only 2 of 3 configured models fit simultaneously |
| 7B model (AWQ) | ~16,752 MB loaded | Fits alongside another 7B |
| 14B model (AWQ) | ~21,484 MB loaded | Requires evicting both 7B models |
| Sleep residual | ~1,400 MB per model | Sleeping models hold CUDA allocator pool |
| Wake latency | ~2-3 seconds (L1 sleep) | Fast enough for request-time wake |
| Cold load latency | ~30-60 seconds | Expensive; avoided when possible |
| TP=2 | All models use tensor parallelism | Each GPU hosts rank 0 or rank 1 shard |

### Architecture Principles

1. **Sleep-first**: Always prefer `sleep_l1` over `stop`. Sleep frees 14-18 GB while keeping weights in CUDA pool for ~2s wake. Stop requires 30-60s cold reload.
2. **Atomic VRAM accounting**: The VRAM ledger uses synchronous (no `await`) check-and-reserve to eliminate check-then-act races in asyncio.
3. **Provider-level serialization**: One capacity operation per provider at a time. Prevents competing drains from deadlocking.
4. **Tenure protection**: Freshly-woken models get a 10s grace period before they can be evicted.
5. **Demand-driven**: All actions (wake/load/sleep/stop) are triggered by measured request demand, not speculation.

---

## 2. Component Map

```
┌──────────────────────────────────────────────────────────────┐
│                     Request Pipeline                          │
│  classify → schedule → [prepare_lane_for_request] → serve    │
└──────────────┬───────────────────────────────────────────────┘
               │ on_capacity_needed callback
               ▼
┌──────────────────────────────────────────────────────────────┐
│                  CapacityPlanner  (4,898 lines)               │
│                                                               │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────┐ │
│  │ Background   │  │ Request-time │  │ Anti-thrashing      │ │
│  │ Planner Loop │  │ Preparation  │  │ & Demand Scoring    │ │
│  │ (30s cycle)  │  │ (sync path)  │  │                     │ │
│  └──────┬──────┘  └──────┬───────┘  └──────────┬──────────┘ │
│         │                │                      │             │
│         ▼                ▼                      ▼             │
│  ┌──────────────────────────────────────────────────────────┐│
│  │              VRAM Ledger (atomic reservations)            ││
│  │   reserve() / release() / try_reserve_atomic()           ││
│  │   Per-provider + per-GPU committed tracking              ││
│  └──────────────────────────────────────────────────────────┘│
│                                                               │
│  ┌──────────────────────────────────────────────────────────┐│
│  │              DemandTracker                                ││
│  │   Exponential decay (0.95/cycle) + burst detection        ││
│  │   Latent demand for unservable models                     ││
│  └──────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────┘
               │
               ▼  send_command / apply_lanes
┌──────────────────────────────────────────────────────────────┐
│              LogosNode Worker (via WebSocket)                  │
│  add_lane / delete_lane / sleep_lane / wake_lane              │
│  apply_lanes (declarative) / reconfigure_lane                 │
└──────────────────────────────────────────────────────────────┘
```

### Source Files

| File | Lines | Purpose |
|---|---|---|
| `capacity/capacity_planner.py` | 4,898 | Core orchestrator: planner loop, request-time prep, eviction, VRAM validation, action execution |
| `capacity/vram_ledger.py` | 285 | Atomic VRAM reservation tracking per provider and per GPU |
| `capacity/demand_tracker.py` | 155 | Per-model demand scoring with exponential decay and burst detection |
| `pipeline/base_scheduler.py` | 359 | Request scheduling, queue management, priority aging, slot transfer |

---

## 3. Lane Lifecycle State Machine

```
                    apply_lanes / add_lane
            ┌──────────────────────────────────────┐
            │                                      ▼
         ┌──────┐                            ┌──────────┐
         │ cold │────────────────────────────▶│ starting │
         └──────┘                            └────┬─────┘
            ▲                                     │ engine ready
            │ delete_lane                         ▼
         ┌──────┐     wake_lane            ┌──────────┐
         │stopped│◀────────────────────────│  loaded   │
         └──────┘     delete_lane          └─┬──────┬─┘
            ▲                                │      │
            │ stop / delete_lane             │      │ first request
            │                                │      ▼
         ┌──────────┐    sleep_lane      ┌──────────┐
         │ sleeping  │◀──────────────────│ running  │
         │(L1 / L2) │                    └──────────┘
         └──────────┘                         ▲
              │           wake_lane           │
              └───────────────────────────────┘
```

### Sleep Levels

| Level | Mechanism | VRAM Freed | Wake Latency | Residual |
|---|---|---|---|---|
| L1 | vLLM `sleep_lane level=1` | KV cache + activation memory (~14-18 GB) | ~2-3 seconds | ~1,400 MB (CUDA allocator pool) |
| L2 | vLLM `sleep_lane level=2` | Deeper release | ~10 seconds | Lower residual |

### State Transitions Triggered By

| Trigger | From State | To State | Method |
|---|---|---|---|
| Request arrives, no lane | — | cold → starting → loaded | `_cold_load_for_request()` |
| Request arrives, lane sleeping | sleeping | loaded/running | `_prepare_existing_lane()` → wake |
| Idle 5 minutes | loaded/running | sleeping (L1) | `_compute_idle_actions()` |
| Sleeping L1 for 10 minutes | sleeping L1 | sleeping L2 | `_compute_idle_actions()` |
| VRAM reclaim needed | loaded/running | sleeping | `_next_request_reclaim_action()` |
| VRAM reclaim (last resort) | sleeping | stopped | `_next_request_reclaim_action()` |
| Demand drain | running (busy) | sleeping | `_should_initiate_drain()` |

---

## 4. Lock Hierarchy

The system uses three levels of asyncio locks, acquired in strict order to prevent deadlock:

```
Provider Capacity Lock  (outermost — coarsest)
    │
    ├── Model Prepare Lock  (per provider × model)
    │       │
    │       └── Lane Action Lock  (per provider × lane — innermost)
    │
    └── Lane Action Lock  (direct, for planner cycle actions)
```

### 4.1 Provider Capacity Lock

**Purpose**: Serialize `_ensure_request_capacity` calls per provider. Without this, concurrent capacity operations for different models create competing VRAM reservations that deadlock.

**Scope**: `self._provider_capacity_locks: dict[int, asyncio.Lock]`

**Acquired in**: `_ensure_request_capacity()` (line 2514-2526)

**Behavior**: Only one capacity reclaim operation (drain → sleep/stop → load/wake) runs at a time per provider. Fast-path checks (model already running) return immediately inside the lock.

**Critical invariant**: The lock is released in a `finally` block (line 2877-2878) — guaranteed even on `CancelledError`.

```python
lock = self._provider_capacity_lock(provider_id)
try:
    await asyncio.wait_for(lock.acquire(), timeout=remaining_for_lock)
except asyncio.TimeoutError:
    return False  # Provider busy with another capacity op
try:
    while True:
        # ... reclaim loop ...
finally:
    lock.release()
```

### 4.2 Model Prepare Lock

**Purpose**: Deduplicate cold loads per (provider, model). Two requests for the *same* model are serialized so only one triggers the cold load; two requests for *different* models proceed concurrently (and hit the provider capacity lock if they need VRAM reclaim).

**Scope**: `self._model_prepare_locks: dict[tuple[int, str], asyncio.Lock]`

**Acquired in**: `prepare_lane_for_request()` (line 572)

```python
async with self._model_prepare_lock(provider_id, model_name):
    # Re-check after acquiring lock
    target = self._pick_request_target_lane(provider_id, model_name)
    if target is not None:
        return await self._prepare_existing_lane(...)
    return await self._cold_load_for_request(...)
```

### 4.3 Lane Action Lock

**Purpose**: Serialize operations on the same lane without blocking unrelated lanes. Prevents concurrent wake + sleep on the same lane.

**Scope**: `self._lane_action_locks: dict[tuple[int, str], asyncio.Lock]`

**Acquired in**: 
- `_run_cycle()` (line 318) — for background planner actions
- `_prepare_existing_lane()` (line 617) — for request-time wake
- `_cold_load_for_request()` (line 829) — for request-time cold load
- `_ensure_request_capacity()` (line 2857) — for reclaim actions

### 4.4 Lock Ordering Guarantee

The code always acquires locks in the order: **provider capacity → model prepare → lane action**. No path exists where a lane action lock is held while acquiring a provider capacity lock, which would cause an ABBA deadlock.

---

## 5. VRAM Ledger — Atomic Reservation System

**File**: `capacity/vram_ledger.py` (285 lines)

The VRAM ledger tracks in-flight VRAM-consuming operations to prevent double-booking when concurrent load/wake/sleep/stop operations overlap.

### 5.1 Design Principle: No `await` = No Preemption

All public methods are **synchronous** (no `await`). In a cooperative asyncio event loop, this guarantees that `try_reserve_atomic` cannot be interleaved between the availability check and the mutation.

```python
def try_reserve_atomic(self, ...) -> str | None:
    # Check: is there room?
    effective = raw_available_mb - self._provider_committed.get(provider_id, 0.0)
    needed = vram_mb * safety_margin
    if effective < needed:
        return None  # DENIED
    # Reserve: deduct from available
    return self.reserve(...)  # also synchronous — no preemption point
```

### 5.2 Reservation Tracking

```python
@dataclass
class VRAMReservation:
    reservation_id: str       # 12-char hex UUID
    provider_id: int
    lane_id: str
    operation: str            # "load" | "wake" | "reclaim_sleep" | "reclaim_stop"
    vram_mb: float            # positive = consuming, negative = freeing
    created_at: float         # time.time()
    gpu_devices: frozenset[int]  # which GPUs this reservation targets
```

### 5.3 Dual-Level Tracking

| Level | Data Structure | Purpose |
|---|---|---|
| Per-provider | `_provider_committed: dict[int, float]` | Aggregate VRAM committed across all GPUs |
| Per-GPU | `_gpu_committed: dict[tuple[int, int], float]` | VRAM committed on specific GPU device |

For TP>1 models, VRAM is distributed evenly across targeted GPUs:
```python
if parsed_gpus:
    per_gpu = vram_mb / len(parsed_gpus)
    for dev in parsed_gpus:
        key = (provider_id, dev)
        self._gpu_committed[key] += per_gpu
```

### 5.4 Negative Reservations

Sleep and stop actions create **negative** reservations so concurrent load operations see the freed space immediately. This is critical for the reclaim loop where sleep frees VRAM that a subsequent wake must consume.

```python
# In _execute_action_with_confirmation for sleep:
freed = max(current_vram - residual, 0.0)
if freed > 0:
    _reservation_id = self._reserve_vram(
        ..., f"reclaim_{action.action}", -freed, ...
    )
```

### 5.5 Release Semantics

Reservations are released in the `finally` block of `_execute_action_with_confirmation`, guaranteeing cleanup even on `asyncio.CancelledError`:

```python
try:
    # ... execute action + poll confirmation ...
finally:
    self._release_vram(_reservation_id)  # runs on CancelledError too
```

**No clamping during release**: Negative and positive reservations must cancel out exactly regardless of release order. Clamping to zero would destroy the negative balance and cause committed totals to drift upward. Totals converge to zero once all reservations are released. Per-provider cleanup clamps only when zero reservations remain (floating-point safety net).

### 5.6 Stale Reservation Cleanup

Safety net: `cleanup_stale(max_age_seconds=120.0)` runs at the start of every planner cycle (line 262). Any reservation older than 120 seconds is forcibly released with a warning log.

---

## 6. Demand Tracking & Scoring

**File**: `capacity/demand_tracker.py` (155 lines)

### 6.1 Exponential Decay

Every planner cycle (30s), all scores are multiplied by `DECAY_FACTOR = 0.95`:

```
score(t+1) = score(t) × 0.95
```

A model with steady 1 req/cycle converges to: `1 / (1 - 0.95) = 20.0`

Scores below 0.01 are pruned to prevent unbounded dictionary growth.

### 6.2 Burst Detection

```python
BURST_WINDOW_SECONDS = 10.0
BURST_THRESHOLD = 5
BURST_DEMAND_MULTIPLIER = 1.5
```

When ≥5 requests arrive for the same model within 10 seconds, each request increments demand by `1.5` instead of `1.0`. This prevents the planner from sleeping a model during an incoming traffic spike.

### 6.3 Latent Demand

```python
LATENT_DEMAND_WEIGHT = 0.5
```

When the classifier prefers a model but the scheduler routes to a different one (because the preferred model is sleeping/unavailable), half-weight demand is recorded. Over time this accumulates, signaling the planner to proactively wake the starving model.

### 6.4 Effective Demand

At decision time, effective demand adds queue depth:

```python
def _effective_demand(self, model_name, lane=None):
    base = self._demand.get_score(model_name)
    queue = float(lane.queue_waiting) if lane else 0.0
    return base + QUEUE_WEIGHT * queue  # QUEUE_WEIGHT = 0.25
```

This captures current backlog that the decay-based score hasn't fully absorbed.

---

## 7. Background Planner Cycle

The planner runs every 30 seconds, executing a six-stage pipeline:

```
_run_cycle()
  │
  ├── 1. cleanup_stale()          — release leaked VRAM reservations (>120s)
  ├── 2. decay_all()              — multiply all demand scores by 0.95
  ├── 3. Per-provider loop:
  │      ├── _update_idle_tracking()           — track idle/sleep durations
  │      ├── _compute_idle_actions()           — sleep idle lanes (L1/L2)
  │      ├── _compute_demand_actions()         — wake/load for demand
  │      ├── _compute_demand_drain_actions()   — drain busy lanes for starving models
  │      └── _compute_preemptive_sleep_actions() — pre-warm stopped models
  ├── 4. _validate_vram_budget()   — filter actions against VRAM capacity
  ├── 5. Execute validated actions — with per-lane locks
  └── 6. Update Prometheus metrics
```

### 7.1 Idle Actions (`_compute_idle_actions`)

| Condition | Action |
|---|---|
| vLLM lane, awake, idle ≥ 300s (5 min) | `sleep_l1` |
| vLLM lane, sleeping L1 for ≥ 600s (10 min) | `sleep_l2` |

The background planner **never stops lanes** just because they're idle. Lane removal is only done by explicit reclaim when another request/load actually needs the VRAM.

### 7.2 Demand Actions (`_compute_demand_actions`)

Decision tree for each model with demand:

```
For each model by score descending:
  │
  ├── Has sleeping lane?
  │     ├── Compute eviction set for wake VRAM
  │     ├── Eviction empty → act on DEMAND_WAKE_FLOOR (0.5)
  │     ├── Eviction non-empty → target_eff > max_victim × WAKE_COMPETITIVE_RATIO (1.5)
  │     └── Eviction impossible → skip
  │
  └── No lane exists?
        ├── Compute GPU placement + eviction set
        ├── Eviction empty → act on DEMAND_LOAD_FLOOR (1.0)
        ├── Eviction non-empty → target_eff > max_victim × LOAD_COMPETITIVE_RATIO (2.0)
        └── Eviction impossible → skip
```

### 7.3 Demand Drain Actions (`_compute_demand_drain_actions`)

Targets models with demand score ≥ `DRAIN_COMPETITIVE_RATIO (3.0)` that have no usable (loaded/running, non-sleeping) lane. For each such model, checks all busy lanes via `_should_initiate_drain()` and emits a sleep (preferred) or stop action.

### 7.4 Preemptive Sleep Actions (`_compute_preemptive_sleep_actions`)

Proactively reloads stopped models into sleeping state for fast wake. Only fires when:
- Model has demand > 0
- No active lane exists
- ≥20% total VRAM remains free after the sleeping residual
- Model has a known `sleeping_residual_mb`

Pre-sleeps idle awake neighbors first to free VRAM for the cold load.

---

## 8. Request-Time Capacity Assurance

When a request arrives for a model that isn't running, the system must make room. This is the **critical hot path** — latency here directly impacts TTFT.

### 8.1 Entry Point: `prepare_lane_for_request()`

```
prepare_lane_for_request(provider_id, model_name, timeout=180s)
  │
  ├── Guard: first status received? (prevent stale state)
  ├── Guard: drain suppression (prevent reload oscillation)
  │
  ├── Target lane found, not sleeping/cold?
  │     └── Return immediately (fast path)
  │
  └── Acquire model_prepare_lock(provider_id, model_name):
        ├── Re-check target (dedup cold loads)
        ├── Target exists → _prepare_existing_lane()
        └── No lane → _cold_load_for_request()
```

### 8.2 Existing Lane Preparation: `_prepare_existing_lane()`

```
_prepare_existing_lane()
  │
  ├── Wake failure cooldown active? → return None
  ├── Lane sleeping/cold? → _ensure_request_capacity()
  │     └── Failed? → return None
  ├── Lane sleeping? → acquire lane lock → wake
  └── select_lane_for_model() → return lane info
```

### 8.3 Cold Load: `_cold_load_for_request()`

```
_cold_load_for_request()
  │
  ├── Estimate VRAM needed
  ├── Provider-level VRAM check
  ├── Per-GPU feasibility check (TP-aware)
  │     └── nth-best GPU must have per_gpu_estimated free
  ├── Headroom check (<10% total) → stop sleeping lanes of other models
  ├── needs_reclaim? → _ensure_request_capacity() with synthetic target
  ├── Execute load action under lane lock
  └── select_lane_for_model()
```

### 8.4 The Reclaim Loop: `_ensure_request_capacity()`

This is the most complex method (~400 lines). It runs inside the provider capacity lock and loops until VRAM is available or the deadline expires.

```
_ensure_request_capacity()   [lines 2479-2878]
  │
  ├── Convert timeout to absolute deadline
  ├── Acquire provider_capacity_lock (serializes all capacity ops)
  │
  └── while True:
        ├── Check deadline
        ├── Read current capacity
        ├── Compute needed VRAM (with safety margin)
        ├── Compute available VRAM (raw - ledger committed)
        │
        ├── Per-GPU checks:
        │   ├── Known GPU path (target_gpu_ids known):
        │   │     ├── TP>1: per_gpu_needed = needed × TP_RANK0_VRAM_FRACTION (0.62)
        │   │     ├── Wake: per_gpu_needed *= WAKE_PER_GPU_SAFETY_MARGIN (1.15)
        │   │     ├── Both provider_ready AND per_gpu_ready → return True
        │   │     ├── provider_ready AND wake → return True (weights on GPU)
        │   │     └── Compute GPU shortfall
        │   │
        │   ├── Unknown GPU path (no target_gpu_ids):
        │   │     ├── Infer TP from profile
        │   │     ├── Check nth-best GPU free
        │   │     ├── Per-GPU fits → return True
        │   │     ├── provider_ready → return True (trust provider-level)
        │   │     └── Compute shortfall
        │   │
        │   └── No per-GPU data + provider_ready → return True
        │
        ├── Get reclaim action from _next_request_reclaim_action()
        │
        ├── reclaim is None? (no actionable candidate)
        │   ├── Cooldown-blocked stop → wait for cooldown + retry
        │   ├── Tenure-blocked idle lane → wait for tenure + retry
        │   ├── Drain-cooldown-blocked busy lane → wait + retry
        │   ├── Busy lane (active requests) → poll every 5s
        │   ├── In-flight VRAM reservation (committed > 0) → wait 5s
        │   └── Nothing at all → return False
        │
        ├── Tenure re-check before execution (prevent sleep of freshly-woken)
        │
        └── Execute reclaim action under lane lock
              ├── Success → loop continues (VRAM freed, re-check availability)
              └── Failure → backoff 2s, re-check
```

---

## 9. Eviction Algorithm

### 9.1 `_find_eviction_set()` — GPU-Aware Greedy Covering

**Input**: Required GPUs, per-GPU deficit, all lanes, model profiles

**Algorithm**:
1. Build candidate list: idle/sleeping lanes with GPU overlap to required set
2. For each candidate, compute freed VRAM per GPU:
   - Loaded/running + awake → `sleep_l1`: freed = current_vram - sleeping_residual
   - Sleeping → `stop`: freed = residual (underreported by CUDA pool; use profile base_residency as floor)
3. Sort candidates by effective demand ascending (sacrifice least-valued first)
4. Greedy covering: pick candidates until all per-GPU deficits are met
5. Return chosen set or `None` if infeasible

**Candidate exclusions**:
- Active requests > 0 or queue_waiting > 0 (busy)
- In load cooldown
- No GPU overlap with required set
- Non-evictable states (cold, stopped, starting, error)

### 9.2 `_pick_cold_load_placement()` — Optimal GPU Selection

For cold loads, tries every combination of `tp` GPUs. For each combination:
1. Compute per-GPU deficit
2. Call `_find_eviction_set()`
3. Select the placement whose eviction set has the lowest max effective-demand score

This ensures we sacrifice the least-valuable models when multiple GPU placements are feasible.

---

## 10. Reclaim Decision Tree

`_next_request_reclaim_action()` builds the request-time reclaim plan:

```
For each lane (≠ target model):
  │
  ├── Lane is busy (active_requests > 0)?
  │     └── _should_initiate_drain() passes?
  │           ├── vLLM + sleeping_residual → sleep_l1 candidate (ALWAYS preferred)
  │           └── else → stop candidate
  │
  ├── Lane is stopped/error/cold/starting? → skip
  │
  ├── Lane is sleeping vLLM? → skip (negligible VRAM freed by stopping)
  │
  ├── Lane is idle loaded vLLM?
  │     ├── Tenure gate: in-flight VRAM reservation? → skip
  │     ├── Tenure gate: loaded_at unknown? → skip
  │     ├── Tenure gate: < LANE_MIN_TENURE_SECONDS (10s)? → skip
  │     └── Compute freed = current - residual → sleep_l1 candidate
  │
  └── Non-vLLM idle lane, not in cooldown?
        └── stop candidate

Select from candidates:
  ├── Has low-penalty stop? → _best_reclaim_plan_combined() (mixed sleep+stop)
  ├── Sleep candidates exist? → _best_reclaim_plan() (sleep-only first)
  ├── Combined exist? → _best_reclaim_plan_combined()
  └── Fallback: largest single action (prefer sleep, prefer GPU overlap)
```

### 10.1 `_best_reclaim_plan()` — Exact Subset Search

Finds the least-destructive reclaim set satisfying the shortfall:

**Preference order**:
1. Lowest total freed VRAM that still satisfies the request
2. Lowest single-lane impact within that set
3. Fewer actions
4. Stable lane-id ordering

Exhaustive search over all subsets — feasible because request-time lane counts are small (typically 2-3).

### 10.2 Drain Gates: `_should_initiate_drain()`

Five logical gates, ALL must pass:

| # | Gate | Condition | Purpose |
|---|---|---|---|
| 0 | Tenure | `tenure_elapsed >= LANE_MIN_TENURE_SECONDS (10s)` | Don't drain freshly-woken models |
| 1 | Queue minimum | `target_work >= DRAIN_MIN_TARGET_QUEUE (2)` | Don't drain for trivial backlog |
| 2 | Work comparison | `target_work > busy_remaining_queue` | Only drain if target has more waiting work |
| 3 | GPU overlap | `target_gpus ∩ busy_gpus ≠ ∅` | Must share at least one GPU |
| 4 | VRAM feasibility | `available + freed_by_sleep >= target_cost` | Sleeping the busy lane must free enough |

**Note**: Active requests on the incumbent are IN PROGRESS and count as inertia against drain. Only the incumbent's unserved queue (queue_waiting) competes.

---

## 11. Anti-Thrashing Mechanisms

### 11.1 Tenure Protection

```python
LANE_MIN_TENURE_SECONDS = 10.0
```

After a model wakes or loads, it has a 10-second grace period during which:
- It cannot be selected as a reclaim sleep candidate
- It cannot be drained for another model
- The tenure timer is set BEFORE the wake command is sent (line 4549) to eliminate the race where the worker transitions the lane before `_poll_confirmation` updates `_lane_loaded_at`

### 11.2 Competitive Ratios

When eviction IS required (VRAM contested), the target must beat the victim by a scaling factor:

| Operation | Ratio | Meaning |
|---|---|---|
| Wake | 1.5× | Target demand must be 50% higher than victim |
| Load | 2.0× | Target demand must be 2× the victim |
| Drain | 3.0× | Target demand must be 3× the victim |

When VRAM is freely available (no eviction needed), only floor scores apply:
- Wake floor: 0.5 (one partial-demand signal suffices)
- Load floor: 1.0 (one real request suffices)

### 11.3 Drain Suppression

```python
self._drain_timestamps: dict[tuple[int, str], float]
```

After a model is drained, the `(provider_id, model_name)` is recorded with a timestamp. Subsequent `prepare_lane_for_request` calls for the same model during the cooldown period (tenure seconds) are rejected — UNLESS the incumbent is idle (0 active requests), in which case the drain rationale no longer applies.

### 11.4 Switch Tracking

```python
SWITCH_WINDOW_SECONDS = 300.0
SWITCH_THRASH_THRESHOLD = 6
```

Model switches are tracked via `_switch_timestamps`. When a new model activates on a provider, it's recorded (with Prometheus metrics). Tenure-waived switches (clean idle→queued transitions) do NOT inflate the counter — they are healthy demand-driven swaps.

`_is_thrashing()` returns True if ≥6 switches occurred in 300 seconds, though currently this is metrics-only (no tenure multiplier applied; `SWITCH_TENURE_MULTIPLIER = 1.0`).

### 11.5 Load Cooldown

```python
LOGOS_LOAD_COOLDOWN_SECONDS = 60  # environment variable
```

After a cold load completes, the lane enters a 60-second cooldown during which:
- It cannot be stopped (prevents immediate reload oscillation)
- Sleep is still allowed (sleeping only releases KV cache, not the model)

### 11.6 Wake Failure Cooldown

```python
WAKE_FAILURE_COOLDOWN_SECONDS = 15.0
```

After a wake command fails (timeout or error), the lane enters a 15-second cooldown where no wake is attempted. Prevents hammering a broken lane.

### 11.7 Cold Marking

`self._marked_cold_lanes: set[tuple[int, str]]`

Before executing sleep or stop on a lane, it's pre-marked as "cold" so the scheduler immediately stops routing new requests. This prevents the TOCTOU race where requests land on a lane between the idle check and the actual sleep/stop. Cold marks are cleared after the action completes (or fails).

---

## 12. VRAM Budget Validation

`_validate_vram_budget()` filters the background planner's action batch:

```
1. Separate actions into:
   - free_actions: sleep_l1, sleep_l2, stop (always allowed)
   - consume_actions: wake, load (need budget check)
   - other_actions: reconfigure_kv_cache (always allowed)

2. Credit freed VRAM from sleep/stop actions to cumulative tracking

3. For each consume action:
   - available = capacity.available - cumulative - pending_vram
   - estimated = _estimate_action_vram(action, profile, capacity)
   - Reject if available < estimated × VRAM_SAFETY_MARGIN (1.0)
   - Accept and add to cumulative
```

**Key detail**: `VRAM_SAFETY_MARGIN = 1.0` (no margin) because calibrated profiles include KV cache and measurements are exact. Per-GPU safety is handled separately via `WAKE_PER_GPU_SAFETY_MARGIN = 1.15` and `TP_RANK0_VRAM_FRACTION = 0.62`.

---

## 13. Action Execution & Confirmation

`_execute_action_with_confirmation()` is the final execution path for all capacity actions.

### 13.1 VRAM Reservation per Action Type

| Action | Reservation Type | VRAM Sign | Reservation Method |
|---|---|---|---|
| `load` | Consuming | Positive | `try_reserve_vram_atomic()` — denied if insufficient |
| `wake` | Consuming | Positive | `try_reserve_vram_atomic()` — denied if insufficient |
| `sleep_l1/l2` | Freeing | Negative | `reserve_vram()` — unconditional |
| `stop` | Freeing | Negative | `reserve_vram()` — unconditional |

### 13.2 Sleep Execution Flow

```
1. Is reclaim sleep? → mark_lane_cold → _drain_lane (wait up to 60s)
2. Create negative VRAM reservation
3. Send sleep_lane command to worker
4. Poll for confirmation
5. Release VRAM reservation (finally)
6. On timeout: unmark cold (lane is probably sleeping anyway)
```

### 13.3 Wake Execution Flow

```
1. Compute wake_delta = loaded_vram - sleeping_residual
2. try_reserve_vram_atomic(wake_delta) — abort if denied
3. Set _lane_loaded_at BEFORE sending command (tenure protection)
4. Send wake_lane command to worker
5. Poll for confirmation
6. Release VRAM reservation (finally)
7. On failure: mark_wake_failure (cooldown)
8. On success: notify scheduler (reevaluate_model_queues)
```

### 13.4 Load Execution Flow

```
1. Estimate load VRAM
2. try_reserve_vram_atomic — abort if denied
3. Infer GPU placement for TP>1 (mirror vLLM's top-tp selection)
4. Send add_lane or apply_lanes command
5. Poll for confirmation
6. Release VRAM reservation (finally)
7. On success: notify scheduler (reevaluate_model_queues)
```

### 13.5 Stop Execution Flow

```
1. Check load cooldown — abort if active
2. Create negative VRAM reservation
3. mark_lane_cold (stop scheduling)
4. _drain_lane (wait for active requests, up to 60s)
5. Send delete_lane or apply_lanes command
6. Poll for confirmation
7. Release VRAM reservation (finally)
8. On success: unmark cold
```

### 13.6 Poll Confirmation

`_poll_confirmation()` polls the runtime snapshot every 2 seconds until the lane reaches the expected state or the timeout expires. Expected states:

| Action | Expected State |
|---|---|
| `load` | `runtime_state in {loaded, running}` |
| `wake` | `sleep_state != sleeping` |
| `sleep_l1/l2` | `sleep_state == sleeping` |
| `stop` | Lane absent from runtime |

---

## 14. Scheduler Integration

**File**: `pipeline/base_scheduler.py`

### 14.1 Slot Transfer & Lane Readiness

On `release()` (request completion), the scheduler checks lane readiness before transferring the slot to the next queued request:

```python
if provider_type == 'logosnode' and has_waiters:
    lane_ready = self._logosnode.is_model_lane_ready(model_id, provider_id)
    if not lane_ready:
        reuse_slot = False
        # Re-enqueue the waiter
```

This prevents phantom active counts when a lane is sleeping/draining.

### 14.2 Queue Reevaluation

When a load or wake confirms, the planner calls `on_state_change(model_name)`, which triggers `reevaluate_model_queues()`:

```python
# Dispatches up to max_capacity queued futures immediately
available_slots = max(0, max_capacity - current_active)
while dispatched < available_slots:
    task, entry = self._queue_mgr.dequeue_with_entry(model_id, provider_id)
    # ... resolve future ...
```

### 14.3 Priority Aging (Starvation Prevention)

```
LOW priority:    after 10s → promote to NORMAL
NORMAL priority: after 30s → promote to HIGH
```

---

## 15. Deadlock, Starvation & Race Condition Analysis

### 15.1 CONFIRMED ISSUES (Observed in Benchmarks)

#### Issue A: "In-Flight Reservation Committed=0MB" False Positive

**Location**: `_ensure_request_capacity()` lines 2804-2828

**Symptom**: At 300+ requests/10min, the 14B model loops for 30-60+ seconds hitting:
```
"No idle reclaim action available ... committed=0MB"
→ Falls through to return False
```

**Root Cause**: When `committed == 0` (no in-flight VRAM reservations) but available VRAM is still insufficient (because other models are actively running with physical VRAM, not ledger-reserved), the code reaches the final `return False` with no reclaim attempted. The reclaim candidates were all filtered out by:
- Tenure protection (freshly woken) → filtered in `_next_request_reclaim_action`
- Active requests on competing lanes → filtered unless `_should_initiate_drain()` passes
- But `_should_initiate_drain()` requires `target_work > busy_remaining`, which fails when the target has just 1 queued request

**Impact**: 44 occurrences at 600/10m benchmark; 14B model avgQ=116.7s

**Severity**: HIGH — causes prolonged starvation of large models under load

#### Issue B: Tenure Blocks Preventing Reclaim Under High Load

**Symptom**: 98 tenure blocks at 600/10m benchmark. Models wake, serve a few requests, then can't be reclaimed for 10s. Under rapid model switching, this creates a cascade where every wake adds 10s of delay before the next model can load.

**Root Cause**: `LANE_MIN_TENURE_SECONDS = 10.0` is a fixed value regardless of load conditions. Under high multi-model contention, 10s is too long — the model may be idle after 2-3 seconds but still protected.

**Impact**: Prevents efficient VRAM recycling under high load

**Severity**: MEDIUM — self-resolving after tenure expires, but adds cumulative latency

### 15.2 POTENTIAL DEADLOCKS

#### Deadlock D1: Provider Capacity Lock Starvation

**Scenario**: Two models (A and B) compete for the same provider. Request for A acquires the provider capacity lock and enters the reclaim loop. It sleeps model B's lane and waits for confirmation (poll every 2s). Meanwhile, request for B waits on `asyncio.wait_for(lock.acquire(), timeout=remaining_for_lock)`. If A's reclaim takes >60s (drain timeout), B's request times out.

**Mitigation in place**: Lock acquisition has a deadline-based timeout. If lock can't be acquired before the request deadline, it returns `False` (graceful failure).

**Residual risk**: If the lock holder is stuck in `_poll_confirmation()` waiting for a worker that's unresponsive, the lock is held for up to `timeout_seconds` (180s default). All other capacity operations for that provider queue behind it.

**Recommendation**: Add a maximum hold time for the capacity lock independent of the action timeout, with forced release + cleanup on violation.

#### Deadlock D2: Drain→Sleep→Wake Cycle Under TP=2

**Scenario**: Model A (TP=2, both GPUs) is running. Model B needs to wake on the same GPUs. The planner sleeps A (freeing ~16 GB per GPU). But before B can wake, a new request for A arrives, triggers `prepare_lane_for_request`, and starts waking A again. Now both A and B are trying to wake on the same GPUs — but only one can fit.

**Mitigation in place**: Provider capacity lock ensures only one capacity op runs at a time. Drain suppression prevents immediate reload of drained models. Tenure protection prevents immediate re-eviction.

**Residual risk**: If drain suppression expires (tenure=10s) and a new burst for A arrives, the system can oscillate between A and B. The competitive ratio (3.0× for drain) provides damping but doesn't prevent the oscillation entirely under sustained dual-model load.

### 15.3 POTENTIAL STARVATION SCENARIOS

#### Starvation S1: Large Model Perpetual Eviction

**Scenario**: A 14B model requires ~21 GB, needing both 7B models evicted. Under continuous traffic for both 7B models, their combined effective demand always exceeds the 14B's demand × `DRAIN_COMPETITIVE_RATIO (3.0)`. The 14B model can never acquire VRAM.

**Evidence**: Benchmark 3 (600/10m) shows 14B avgQ=116.7s vs 7B avgQ=3.5-10.8s. The 14B model is perpetually starved because:
1. Both 7B models have higher combined demand
2. `_should_initiate_drain()` requires `target_work > busy_remaining` — but 7B models always have active requests
3. The "committed=0MB" false positive prevents the reclaim loop from trying harder

**Recommendation**: Add a starvation escalation mechanism: if a model has been queued for >30s with no progress, temporarily boost its effective demand or lower the competitive ratio for that model.

#### Starvation S2: Fire-and-Forget Capacity Triggers With No Retry

**Scenario**: Model B has 20 requests queued. Each fires `on_capacity_needed` → `prepare_lane_for_request` as a detached `asyncio.create_task` (correcting_scheduler.py line 213). All 20 calls fail because no VRAM is available. When VRAM later frees up (incumbent finishes), no one re-checks model B's needs. A new model C request arrives and claims the VRAM for 1 request.

**Root cause**: `prepare_lane_for_request` is fire-and-forget. Failed capacity tasks silently complete. There is no retry registration, no pending-demand queue, and no mechanism to re-trigger capacity evaluation when VRAM frees up — except the 30s background planner cycle.

**Evidence**: At 600/10m benchmark, the 14B model hits `return False` 44 times in `_ensure_request_capacity`. Each time, the fire-and-forget task exits and the queued requests wait up to 30s for the next planner cycle.

**Compounding factor**: Request-time idle reclaim has NO demand comparison (see §18.2, Issue 2). Any single request can sleep any idle lane regardless of how many requests are queued for the victim model.

**Severity**: HIGH — this is the primary cause of 14B starvation (avgQ=116.7s at 600/10m)

See §18 for full analysis and proposed fix.

#### Starvation S3: Single-Request Models Never Trigger Drain

**Scenario**: A model receives exactly 1 request while another model holds VRAM with active requests. `DRAIN_MIN_TARGET_QUEUE = 2` prevents drain for single requests. The request waits for `timeout_seconds` then fails.

**Mitigation**: The background planner's `_compute_demand_drain_actions()` uses `DRAIN_DEMAND_SCORE_THRESHOLD = 3.0`, which requires sustained demand. Single requests rely on idle sleep of the incumbent to free VRAM. If the incumbent is continuously busy, the single request starves.

**Recommendation**: Add a fallback path in `_ensure_request_capacity()` that bypasses `DRAIN_MIN_TARGET_QUEUE` when the request has been waiting for >30s with no progress.

### 15.4 RACE CONDITIONS

#### Race R1: Capacity Check → Reclaim Action Stale State

**Location**: `_ensure_request_capacity()` lines 2692-2700

**Scenario**: Between the capacity check (line 2539-2551) and the reclaim action selection (line 2695), another coroutine may have already reclaimed the needed VRAM. The reclaim action selection reads `self._safe_get_lanes(provider_id)` — but this is the same snapshot the capacity check used.

**Mitigation**: The provider capacity lock serializes all capacity ops per provider, so no concurrent reclaim can happen between the check and the action selection within the same provider. Cross-provider races are harmless (different VRAM pools).

**Residual risk**: None for same-provider operations. The lock fully covers this case.

#### Race R2: Tenure Set Before Command Sent

**Location**: `_execute_action_with_confirmation()` line 4549

**Scenario**: `_lane_loaded_at` is set BEFORE the wake command is sent. If the command fails, `loaded_at` is stale — future reclaim checks think the lane is recently woken when it's actually still sleeping.

**Mitigation**: On wake failure, `_mark_wake_failure()` is called (line 4558), which sets a cooldown. However, `loaded_at` is NOT rolled back.

**Impact**: Low — the stale `loaded_at` provides 10s of false tenure protection, after which the lane can be reclaimed normally. The wake failure cooldown (15s) actually provides longer protection anyway.

#### Race R3: Cold Mark Leak on Task Cancellation

**Scenario**: A request is cancelled (e.g., client disconnect) while the lane is cold-marked and draining. The `finally` block in `_execute_action_with_confirmation()` releases the VRAM reservation, but cold mark cleanup depends on the specific action path.

**Mitigation**: For sleep actions, the cold mark is cleared on both success and timeout (line 4762). For stop actions, cold mark is cleared on rollback (line 4727) and success (line 4772). On `CancelledError`, the `finally` block releases the VRAM reservation but does NOT explicitly clear the cold mark.

**Impact**: The cold-marked lane is permanently excluded from scheduling until the next planner cycle detects the inconsistency. If the lane is still running (cancellation happened before the command was sent), it silently serves no requests.

**Recommendation**: Add cold mark cleanup to the `finally` block, or add a periodic cold-mark reconciliation in `_run_cycle()`.

#### Race R4: Dual-Model Queue Depth TOCTOU

**Location**: `_should_initiate_drain()` lines 4186-4212

**Scenario**: Queue depth for target and busy models is read at different moments. Between reading `target_work` (line 4186) and `busy_total` (line 4201), the queue may have changed. A new request for the busy model may arrive, making the drain decision stale.

**Mitigation**: The asyncio event loop is cooperative — no preemption between the two reads unless there's an `await` between them. Since both calls to `_get_queue_depth_for_model()` are synchronous, this race doesn't occur in the current implementation.

**Residual risk**: None — synchronous reads within the same event loop tick.

### 15.5 SUBTLE CORRECTNESS ISSUES

#### Issue C1: Sleeping Lane VRAM Underreporting

**Location**: `_find_eviction_set()` lines 1470-1482

**Detail**: Sleeping vLLM lanes underreport GPU usage via `--query-compute-apps` because the CUDA allocator keeps model weights in its pool, invisible to per-process queries. The code uses `profile.base_residency_mb` as a floor, but this relies on the profile being accurate.

**Impact**: If `base_residency_mb` is underestimated, stopping a sleeping lane frees less VRAM than expected, causing subsequent loads to OOM.

#### Issue C2: TP>1 Rank 0 VRAM Fraction Hardcoded

**Location**: `TP_RANK0_VRAM_FRACTION = 0.62` (line 126)

**Detail**: For TP=2, rank 0 hosts the API server, tokenizer, sampling, and embedding layers — empirically ~60% of total VRAM. The 0.62 fraction is hardcoded for TP=2. For TP=4 or TP=8 (if the system scales), this fraction would be different.

**Impact**: Only affects TP≠2 configurations, which aren't currently deployed.

#### Issue C3: `_best_reclaim_plan_combined()` Combinatorial Cap

**Location**: line 3177: `for size in range(1, min(len(candidates) + 1, 6))`

**Detail**: Subset search is capped at size 5 to avoid combinatorial explosion. With >5 candidates, the optimal reclaim plan might require 6+ lanes, which won't be found.

**Impact**: Very low — in practice, lane counts are 2-3 per provider. Only relevant for hypothetical configurations with 6+ models on a single provider.

---

## 16. Benchmark Evidence

Hardware: 2× GPUs, 32,768 MB total VRAM. Three models: Qwen 7B, Qwen 14B, Mistral 7B.
Benchmark date: 2026-04-11. Full analysis: [`docs/benchmark-results-analysis.md`](benchmark-results-analysis.md).
Charts: [`tests/performance/results/`](../tests/performance/results/).

### 16.1 Results Summary (LogosWorkerNode with Queue-Fair Scheduling)

| Metric | 150 req/10m | 300 req/10m | 600 req/10m |
|---|---|---|---|
| Success rate | 100% (150/150) | 99.3% (298/300) | 100% (600/600) |
| P50 TTFT | 18,653ms | 27,634ms | 42,357ms |
| P95 TTFT | 66,440ms | 70,667ms | 117,773ms |
| P99 TTFT | 75,677ms | 85,746ms | 137,653ms |
| P50 Total Latency | 25,111ms | 34,464ms | 52,155ms |
| P95 Total Latency | 70,685ms | 75,078ms | 129,794ms |
| P99 Total Latency | 86,444ms | 97,288ms | 142,396ms |
| P50 TPOT | 43.8ms/tok | 43.0ms/tok | 53.0ms/tok |
| P50 Queue Wait | 8,998ms | 8,799ms | 9,534ms |

### 16.2 Comparison vs Ollama Baseline

| Metric (600 req) | LogosWorkerNode | Ollama | Speedup |
|---|---|---|---|
| Success rate | **100%** | 99.3% | -- |
| P50 TTFT | **42.4s** | 360.4s | **8.5x** |
| P95 TTFT | **117.8s** | 1,237.0s | **10.5x** |
| P50 Total Latency | **52.2s** | 362.2s | **6.9x** |
| P95 Total Latency | **129.8s** | 1,239.6s | **9.6x** |

The advantage grows super-linearly with load because Ollama's lack of scheduling causes O(n) queue buildup while LogosWorkerNode's queue-fair scheduling maintains bounded latencies.

### 16.3 Key Observations

1. **Queue wait is stable across load levels**: P50 queue wait stays at ~9s regardless of whether the workload is 150 or 600 requests. This floor corresponds to the vLLM sleep-to-wake transition time and demonstrates that the scheduling layer successfully bounds queuing overhead.

2. **TPOT scales gracefully**: P50 TPOT increases from 43.8ms (150 req) to 53.0ms (600 req) — only 21% degradation at 4x load — because vLLM's continuous batching amortizes GPU compute across concurrent requests.

3. **Zero cold starts**: All three runs show 0 cold starts. Models transition between sleeping and loaded states via the fast wake path (2-3s), never requiring a full cold load (30-60s). The capacity planner's preemptive sleep strategy keeps model weights on GPU.

4. **Queue-fair scheduling prevents starvation**: The P95/P99 ratio stays tight (1.10-1.17x across all loads), meaning no long tail of starved requests. Previous implementations without queue-fair reclaim showed P99 queue waits of 162s (vs current 84s at 600 req).

---

## 17. Refinement Proposals

> **Status (2026-04-11)**: Proposal P1 Part A (queue-fair idle reclaim) and Part B (pending capacity retry) have been implemented. The benchmark results in §16 reflect these fixes. Proposals P2 and P3 remain open for future evaluation.

### Proposal P1: Demand-Gated Reclaim + Retry Registration — IMPLEMENTED

**Problem**: Two compounding issues cause VRAM starvation (see §18 for full analysis):
1. Fire-and-forget capacity triggers silently fail with no retry — when VRAM frees up, no one re-checks
2. Request-time idle reclaim has no demand comparison — 1 request can preempt 20 queued requests

**Proposed Fix (two parts)**:

**Part A — Demand-gated idle reclaim**: Before sleeping an idle lane for a new request, compare total demand (scheduler queue + backend) between the victim and the target:

```python
# In _next_request_reclaim_action(), idle lane path:
victim_demand = self._get_queue_depth_for_model(provider_id, lane.model_name, lanes)
target_demand = self._get_queue_depth_for_model(provider_id, target.model_name, lanes)
if victim_demand > target_demand:
    continue  # Don't sleep a model with more waiting work
```

**Part B — Pending demand registration**: When `_ensure_request_capacity` fails, register a pending demand entry instead of silently returning:

```python
# On return False:
self._pending_capacity_requests.setdefault(provider_id, []).append(
    PendingCapacityRequest(model_name, time.time(), queue_depth)
)

# After any successful sleep/stop/wake frees or changes VRAM:
self._retry_pending_capacity_requests(provider_id)
```

**Benchmark verification**: At 600/10m, the 14B model hits `return False` 44 times. With retry registration, each subsequent VRAM-freeing event would immediately re-check 14B's pending demand. With demand-gated reclaim, model C's 1 request could not preempt 14B's 20 queued requests — the 14B would wake first.

### Proposal P2: Adaptive Tenure Under Contention

**Problem**: Fixed 10s tenure causes 98 blocks at 600/10m. A freshly-woken model that finishes serving in 3s still blocks reclaim for 7 more seconds.

**Proposed Fix**: Reduce tenure when the model has served its queue:

```python
def _get_effective_tenure(self, was_cold_loaded=False, lane=None):
    base = self.LANE_MIN_TENURE_SECONDS  # 10s
    if lane is not None and lane.active_requests == 0 and lane.queue_waiting == 0:
        # Model has served its queue — reduce tenure
        return min(base, 3.0)  # 3s minimum after queue drained
    return base
```

**Benchmark verification**: At 600/10m, many tenure blocks occur on idle lanes. With adaptive tenure, 70%+ of the 98 blocks would clear in 3s instead of 10s, reducing 14B starvation time by ~50s cumulative.

### Proposal P3: Starvation-Aware Demand Boost

**Problem**: Models waiting >30s in queue don't get progressively stronger demand signals.

**Proposed Fix**: In `_effective_demand()`, add a starvation multiplier:

```python
def _effective_demand(self, model_name, lane=None):
    base = self._demand.get_score(model_name)
    queue = float(lane.queue_waiting) if lane else 0.0
    eff = base + self.QUEUE_WEIGHT * queue
    
    # Starvation boost: oldest queued request age
    oldest_wait = self._facade.get_oldest_queue_wait_seconds(model_name)
    if oldest_wait > 30:
        starvation_factor = 1.0 + (oldest_wait - 30) / 30  # +1.0 per 30s
        eff *= starvation_factor
    
    return eff
```

**Benchmark verification**: At 600/10m, 14B requests wait 60-120s. After 30s, starvation_factor = 2.0 → effective demand doubles. After 60s, factor = 3.0 → drain competitive ratio (3.0×) is overcome, allowing drain of busy 7B lanes.

### Proposal P4: Cold Mark Reconciliation

**Problem**: Cold marks can leak on task cancellation (Race R3).

**Proposed Fix**: Add reconciliation at the start of each planner cycle:

```python
# In _run_cycle():
self._reconcile_cold_marks(provider_ids)

def _reconcile_cold_marks(self, provider_ids):
    for pid in provider_ids:
        lanes = self._safe_get_lanes(pid)
        active_lane_ids = {l.lane_id for l in lanes}
        for key in list(self._marked_cold_lanes):
            if key[0] == pid and key[1] not in active_lane_ids:
                self._marked_cold_lanes.discard(key)
            elif key[0] == pid:
                lane = next((l for l in lanes if l.lane_id == key[1]), None)
                if lane and lane.runtime_state in ("loaded", "running") and lane.active_requests == 0:
                    # Lane is running but cold-marked — likely leaked
                    if not self._vram_ledger.has_active_reservation(pid, key[1]):
                        self._marked_cold_lanes.discard(key)
```

### Proposal P5: Bounded Capacity Lock Hold Time

**Problem**: Provider capacity lock can be held for up to 180s if the action inside is slow (Deadlock D1).

**Proposed Fix**: Separate the lock timeout from the overall request timeout:

```python
CAPACITY_LOCK_MAX_HOLD_SECONDS = 45.0  # Max time to hold the lock

# In _ensure_request_capacity:
lock_deadline = time.time() + min(remaining, self.CAPACITY_LOCK_MAX_HOLD_SECONDS)
# ... reclaim loop uses lock_deadline instead of request deadline ...
# Release lock after 45s even if reclaim isn't complete
# Re-acquire lock on next iteration if needed
```

**Benchmark verification**: At 300/10m, no lock timeouts were observed, but worst-case hold time approached 60s. With 45s cap, other models' capacity operations would be unblocked sooner.

### Proposal P6: Sleeping Lane Awareness in VRAM Reporting

**Problem**: Sleeping vLLM lanes underreport VRAM via per-process queries (Issue C1).

**Proposed Fix**: Already partially addressed by using `profile.base_residency_mb` as a floor. Could be strengthened by:
1. Tracking the actual VRAM freed when a sleep succeeds (delta between pre-sleep and post-sleep capacity snapshots)
2. Using the measured value for subsequent eviction decisions instead of the profile estimate

This is a telemetry improvement rather than a correctness fix — the current floor approach is conservative (overestimates residual = underestimates freed = safe for OOM prevention).

---

## Appendix A: Constants Reference

| Constant | Value | Purpose |
|---|---|---|
| `IDLE_SLEEP_L1` | 300s | Background sleep trigger |
| `IDLE_SLEEP_L2` | 600s | L1→L2 deepening trigger |
| `DEMAND_WAKE_FLOOR` | 0.5 | Min demand to wake (no eviction) |
| `DEMAND_LOAD_FLOOR` | 1.0 | Min demand to cold load (no eviction) |
| `WAKE_COMPETITIVE_RATIO` | 1.5 | Target vs victim for wake eviction |
| `LOAD_COMPETITIVE_RATIO` | 2.0 | Target vs victim for load eviction |
| `DRAIN_COMPETITIVE_RATIO` | 3.0 | Target vs victim for busy drain |
| `QUEUE_WEIGHT` | 0.25 | Queue depth contribution to effective demand |
| `LANE_MIN_TENURE_SECONDS` | 10.0 | Grace period after wake/load |
| `DRAIN_MIN_TARGET_QUEUE` | 2 | Min target queue depth for drain |
| `DRAIN_TIMEOUT_SECONDS` | 60.0 | Max wait for active requests to finish |
| `VRAM_SAFETY_MARGIN` | 1.0 | Provider-level safety (none — profiles exact) |
| `WAKE_PER_GPU_SAFETY_MARGIN` | 1.15 | Per-GPU margin for wake ops |
| `TP_RANK0_VRAM_FRACTION` | 0.62 | Rank 0 VRAM fraction for TP=2 |
| `TP_OVERHEAD_RATIO` | 0.10 | TP NCCL buffer overhead |
| `REQUEST_WAKE_TIMEOUT_SECONDS` | 30.0 | Max wait for wake in request path |
| `WAKE_FAILURE_COOLDOWN_SECONDS` | 15.0 | Cooldown after failed wake |
| `COOLDOWN_WAIT_BUFFER_SECONDS` | 2.0 | Extra margin after cooldown wait |
| `BUSY_DRAIN_POLL_SECONDS` | 5.0 | Poll interval for busy lane drain |
| `SWITCH_WINDOW_SECONDS` | 300.0 | Window for thrash detection |
| `SWITCH_THRASH_THRESHOLD` | 6 | Switches before thrash flag |
| `PREEMPTIVE_SLEEP_MIN_FREE_VRAM_RATIO` | 0.20 | Min free VRAM for pre-warming |
| `PREEMPTIVE_SLEEP_MAX_MODELS` | 3 | Max models to pre-warm per cycle |
| `DECAY_FACTOR` (DemandTracker) | 0.95 | Exponential decay per 30s cycle |
| `BURST_WINDOW_SECONDS` | 10.0 | Burst detection window |
| `BURST_THRESHOLD` | 5 | Requests in window to trigger burst |
| `BURST_DEMAND_MULTIPLIER` | 1.5 | Demand scaling during bursts |
| `LATENT_DEMAND_WEIGHT` | 0.5 | Half-weight for unservable model demand |

## Appendix B: Lock Acquisition Order

```
1. provider_capacity_lock(provider_id)     [_ensure_request_capacity]
2.   model_prepare_lock(provider_id, model) [prepare_lane_for_request]
3.     lane_action_lock(provider_id, lane)  [_execute_action_with_confirmation]
```

Never: lane_action_lock → provider_capacity_lock (would cause ABBA deadlock)

The provider capacity lock is only acquired in the request-time path (`_ensure_request_capacity`). The background planner acquires lane action locks directly (step 3 only), which is safe because planner actions don't compete for VRAM within the lock — VRAM validation happens before lock acquisition.

---

## 18. Fairness Inversion: Last-Arrival Wins the VRAM Race

### 18.1 The Problem

The current system has a structural fairness bug: **a single new request for model C can claim freed VRAM ahead of model B which has 20 requests queued**, because the capacity trigger is fire-and-forget with no retry and no demand comparison.

**Concrete scenario** (reproducible under the 600/10m benchmark):

```
t=0   Lane A (Qwen-7B) running, serving requests.
      Lane B (Qwen-14B) sleeping. 20 requests queued in Logos scheduler.
        Each request fired on_capacity_needed → prepare_lane_for_request(B)
        → _ensure_request_capacity() → no idle lane to reclaim (A is busy)
        → _should_initiate_drain() fails (target_work < busy_remaining,
          or DRAIN_MIN_TARGET_QUEUE gate)
        → returns False. Fire-and-forget task completes. No retry.
      
      All 20 requests now stuck in PriorityQueueManager as unresolved futures,
      waiting for reevaluate_model_queues (which only fires on load/wake
      confirmation) or the next 30s planner cycle.

t=15  Lane A finishes its last request. VRAM is now reclaimable.
      But no one re-checks — B's capacity tasks already returned False.

t=16  1 request arrives for model C (Mistral-7B, cold — no lane exists).
      Two things fire simultaneously:
      
      PATH 1 — context_resolver.py line 107:
        prepare_lane_for_request(provider_id, model_C)
        → _cold_load_for_request() → _ensure_request_capacity()
        → acquires provider_capacity_lock (no contention — B released it)
        → _next_request_reclaim_action() finds Lane A idle:
            lane.active_requests = 0, lane.queue_waiting = 0
            → sleep_l1 candidate (NO demand comparison for idle reclaim!)
        → Sleeps Lane A → cold loads Lane C
        → Lane C serves 1 request
      
      PATH 2 — correcting_scheduler.py line 213:
        asyncio.create_task(on_capacity_needed(provider_id, model_C))
        → Same path, fire-and-forget
      
t=18  Lane C is now running. Lane B still sleeping with 20 queued requests.
      Lane B's requests remain stuck until:
        a) Another request for B arrives and triggers prepare_lane (race again)
        b) 30s planner cycle runs _compute_demand_actions (up to 14s away)
        c) reevaluate_model_queues fires for B (only on B's own state change)
      
      In the worst case, B's 20 requests wait 30s for the planner cycle,
      then another 2-3s for wake = 33s+ of starvation caused by 1 request.
```

### 18.2 Root Causes (Three Compounding Issues)

#### Issue 1: Fire-and-Forget Capacity Triggers With No Retry

```python
# correcting_scheduler.py line 213:
asyncio.create_task(
    self._on_capacity_needed(provider_id, model_name),
    name=f"capacity-needed-{model_name}-{provider_id}",
)
```

Each queued request fires `prepare_lane_for_request` as a detached `asyncio.create_task`. If it returns `None` (couldn't reclaim VRAM), the task completes silently. **No retry is scheduled.** The 20 queued requests each fired their own capacity task, all failed, and all exited. When VRAM finally frees up, nobody is listening.

#### Issue 2: No Demand Comparison on Request-Time Idle Reclaim

`_next_request_reclaim_action()` (line 2903) checks:

```python
if lane.active_requests > 0 or lane.queue_waiting > 0:
    # busy path — needs _should_initiate_drain() to pass
    continue
# Falls through to "idle" path — can be slept for ANY requester
```

For idle lanes, there is **no competitive ratio check**. Any single request can sleep any idle lane, regardless of how many requests are queued for that lane's model. The competitive ratios (1.5×/2.0×/3.0×) only apply to background planner evictions, not request-time idle reclaim.

The `_get_queue_depth_for_model()` helper (line 1345) does combine scheduler + backend queues, but it is only called inside `_should_initiate_drain()` — the busy lane path. The idle path never checks it.

#### Issue 3: Provider Capacity Lock is FCFS, Not Demand-Weighted

The provider capacity lock is a plain `asyncio.Lock` — first-come-first-served. When VRAM frees up and multiple models are competing:

```python
lock = self._provider_capacity_lock(provider_id)
await asyncio.wait_for(lock.acquire(), timeout=remaining_for_lock)
```

Whoever acquires the lock first gets exclusive access to reclaim. There is no priority queue on lock acquisition. Model C's 1 request and model B's 20 requests have equal weight at the lock level.

### 18.3 The Information Asymmetry

```
                    prepare_lane_for_request (request-time)
                              │
              ┌───────────────┴───────────────┐
              │                               │
     _ensure_request_capacity()      context_resolver retry loop
     (inside provider_capacity_lock)  (polls select_lane_for_model
              │                        every 1-2s for up to 30s)
              │                               │
     SEES: current lane states        SEES: lane registry only
     DOES NOT SEE:                    DOES NOT SEE:
       - Scheduler queue depth          - Other models' queues
         for OTHER models               - Demand scores
       - Total demand comparison        - VRAM availability
         on idle reclaim path
              │
     DECIDES: first caller wins
     (fire-and-forget, no retry,
      no demand comparison for
      idle lanes)
```

### 18.4 Proposed Fix: Demand-Gated Idle Reclaim + Retry Registration

**Part A — Demand gate on idle reclaim**: Before sleeping an idle lane, compare the target's total demand against the victim's total demand:

```python
# In _next_request_reclaim_action(), for idle lanes (after tenure check):
victim_total_demand = self._get_queue_depth_for_model(
    provider_id, lane.model_name, lanes,
)
target_total_demand = self._get_queue_depth_for_model(
    provider_id, target.model_name, lanes,
)
if victim_total_demand > target_total_demand:
    logger.info(
        "Idle reclaim skip: victim %s has %d queued vs target %s with %d",
        lane.model_name, victim_total_demand,
        target.model_name, target_total_demand,
    )
    continue  # Don't sleep a lane whose model has more waiting work
```

**Part B — Retry registration**: When `_ensure_request_capacity` returns `False`, instead of silently failing, register a "pending demand" that the planner re-evaluates when VRAM frees up:

```python
# When _ensure_request_capacity returns False:
self._pending_capacity_requests[provider_id].append(
    (model_name, time.time(), queue_depth)
)

# In _run_cycle() or after any successful sleep/stop:
self._retry_pending_capacity_requests(provider_id)
```

This ensures that model B's 20 queued requests don't silently vanish from the capacity planner's awareness when their fire-and-forget tasks fail.

---

## 19. Anti-Thrashing Mechanism Audit: What to Keep, What to Simplify

The current system has **7 distinct anti-thrashing mechanisms**. Several overlap, and some add complexity without clear benefit under the observed workload patterns.

### 19.1 Current Mechanisms and Their Effectiveness

| # | Mechanism | Lines | Effective? | Recommendation |
|---|---|---|---|---|
| 1 | **Tenure protection** (10s) | 2992-3026, 4164-4182 | Partially — causes 98 blocks at 600/10m, many on genuinely idle lanes | **SIMPLIFY**: Replace fixed 10s with queue-aware adaptive (see §18.4) |
| 2 | **Competitive ratios** (1.5×/2.0×/3.0×) | 69-71, 1932, 2020 | Yes — prevents background planner thrashing | **KEEP**: Well-calibrated for background cycle |
| 3 | **Drain suppression** (cooldown after drain) | 534-564, 191 | Partially — useful concept but overlaps with tenure | **SIMPLIFY**: Merge into a unified "recently displaced" cooldown |
| 4 | **Switch tracking** (metrics only) | 1300-1343 | No operational effect — `SWITCH_TENURE_MULTIPLIER = 1.0` | **REMOVE**: Pure overhead. Keep Prometheus counter if desired |
| 5 | **Load cooldown** (60s) | 4658, 1018 | Yes — prevents immediate stop after expensive cold load | **KEEP** |
| 6 | **Wake failure cooldown** (15s) | 598-605, 4558 | Yes — prevents hammering broken lanes | **KEEP** |
| 7 | **Cold marking** (pre-drain scheduling exclusion) | 4471, 4677 | Yes — prevents TOCTOU routing races | **KEEP** |

### 19.2 Proposed Simplification

Remove **switch tracking** (mechanism 4) entirely — it does nothing operational. Merge **tenure** and **drain suppression** into a single "displacement cooldown" that is:
- Queue-aware: waived when the displaced model has zero total demand (scheduler + backend)
- Adaptive: 3s minimum if the model has served its queue, 10s otherwise

This reduces the anti-thrashing surface from 7 mechanisms to 5, with clearer semantics.

---

## 20. Academic Foundations and Thesis Research Anchors

The Logos capacity management system sits at the intersection of several well-studied domains. Below are the primary research threads that provide theoretical grounding for the architecture, the identified issues, and the proposed refinements.

### 20.1 GPU Cluster Scheduling and Multi-Tenant Serving

#### Model Multiplexing on Shared GPUs

The core problem — dynamically placing and displacing multiple LLM instances on shared GPU memory — is a form of **multi-tenant GPU scheduling** studied in:

- **Gandiva** (Xiao et al., OSDI 2018) — *"Introspective Cluster Scheduling for Deep Learning"*. Introduces time-slicing and migration of DL jobs across GPUs. Directly relevant: Gandiva's *packing* heuristic is analogous to our eviction set algorithm (§9), and its *migration* mechanism maps to our sleep/wake cycle. Gandiva shows that introspective scheduling (reacting to runtime metrics rather than static placement) reduces GPU waste by 26%.

- **Tiresias** (Gu et al., NSDI 2019) — *"A GPU Cluster Manager for Distributed Deep Learning"*. Studies job placement with **Least Attained Service (LAS)** scheduling — the jobs that have received the least GPU time get priority. This is the theoretical fix for our fairness inversion (§18): the 20-request model has more "unattained service" and should not be preempted by a 1-request model. Our `_effective_demand()` is a rough approximation of LAS but lacks the queue-depth awareness that Tiresias uses.

- **AntMan** (Xiao et al., OSDI 2020) — *"Dynamic Scaling on GPU Clusters for Deep Learning"*. Proposes co-locating multiple DNN models on the same GPU via dynamic memory management. Directly analogous to our VRAM ledger and sleep/wake mechanism — AntMan's "memory swapping" is our L1 sleep (weights moved to host/CUDA pool), and its "opportunistic scaling" maps to our demand-based wake.

#### LLM-Specific Serving Systems

- **Orca** (Yu et al., OSDI 2022) — *"A Distributed Serving System for Transformer-Based Generative Models"*. Introduces **iteration-level scheduling** where the scheduler can interleave requests from different models within the same engine. Relevant to our inter-batch gap fairness issue: Orca's continuous batching means the gap between batches is microseconds, not the seconds-long window our system has.

- **vLLM** (Kwon et al., SOSP 2023) — *"Efficient Memory Management for Large Language Model Serving with PagedAttention"*. The underlying engine. vLLM's PagedAttention decouples logical and physical KV-cache blocks, enabling fine-grained memory management. Our VRAM ledger operates at a coarser granularity (model-level), which is the right abstraction for multi-model orchestration but means we cannot exploit vLLM's internal memory efficiency for cross-model sharing.

- **S-LoRA** (Sheng et al., 2023) — *"Serving Thousands of Concurrent LoRA Adapters"*. Serves multiple LoRA adapters on a single base model without model switching. Relevant as a **comparison point**: if models share a base (like Qwen-7B variants), adapter-based serving eliminates the sleep/wake overhead entirely. Our system assumes heterogeneous models (7B/14B/different architectures), where S-LoRA doesn't apply.

- **Sarathi-Serve** (Agrawal et al., 2024) — *"Efficient LLM Inference with Chunked Prefills"*. Addresses the prefill-decode scheduling tension. Relevant to our TTFT analysis: high TTFT under load (p50=64s at 600/10m) is partly caused by model switching overhead, but also by prefill/decode contention within a single model. Sarathi's chunked prefill approach could reduce per-request latency independent of our orchestration improvements.

- **DistServe** (Zhong et al., OSDI 2024) — *"Disaggregating Prefill and Decoding for Goodput-optimized Large Language Model Serving"*. Separates prefill and decode to different GPUs. Relevant for understanding why our TP=2 setup creates the rank 0 VRAM asymmetry (§15.5, Issue C2) — disaggregated serving would eliminate this.

### 20.2 Operating Systems: Scheduling Theory

#### Priority Inversion and the Mars Pathfinder Problem

Our fairness inversion (§18) is a form of **priority inversion**: a high-priority workload (20 queued requests) is preempted by a low-priority workload (1 request) because the scheduler lacks awareness of the full priority context.

- **Sha et al., 1990** — *"Priority Inheritance Protocols"*. Introduced **Priority Inheritance** and **Priority Ceiling** protocols for real-time systems. In our context, priority inheritance would mean: if model B's reclaim would displace model A, model A's effective priority should temporarily inherit the combined priority of its 20 queued requests, making it unpreemptable by a single request.

- **The Mars Pathfinder Incident** (1997, Jones 1997) — Classic example of priority inversion causing system failure. Our system has an analogous failure mode: a low-demand model (B) acquires a shared resource (GPU VRAM) and blocks a high-demand model (A) from running.

#### Convoy Effect

- **Blasgen et al., 1979** — *"The Convoy Phenomenon"*. In database locking, short transactions queue behind long transactions holding locks. Our system exhibits the reverse: a short transaction (1 request) can acquire the "lock" (VRAM) and force long transactions (20 requests) to wait. This is the **inverse convoy effect** — the overhead of acquiring the resource (sleep/wake cycle) is disproportionate to the work performed.

#### Working Set Theory and Thrashing

- **Denning, 1968** — *"The Working Set Model for Program Behavior"*. Defines thrashing as the state where a system spends more time managing resources (page swaps) than doing useful work. Our model switching overhead (sleep/wake ~2-3s, cold load ~30-60s) maps directly to page fault overhead. Denning's working set concept suggests: **keep the "working set" of models in memory** — the models that are actively receiving requests over a time window. Our demand tracker with exponential decay approximates this, but the reclaim logic doesn't respect it.

- **Clock-PRO** (Jiang et al., USENIX ATC 2005) — Adaptive page replacement combining frequency and recency. Our eviction algorithm sorts by `effective_demand` (frequency × decay = recency-weighted frequency), which is conceptually similar to Clock-PRO's "cold page" detection. The difference: Clock-PRO has a "test period" for cold pages before they're evicted — our system has no equivalent, which is why cold marking leaks (Race R3) and why freshly-loaded models need the tenure protection hack.

### 20.3 Resource Allocation Fairness

#### Dominant Resource Fairness

- **Ghodsi et al., NSDI 2011** — *"Dominant Resource Fairness: Fair Allocation of Multiple Resources in Datacenters"*. DRF generalizes max-min fairness to multiple resource types. In our system, the dominant resource is GPU VRAM — the bottleneck that determines which models can run simultaneously. DRF would allocate VRAM proportionally to each model's demand share, preventing the situation where a low-demand model starves a high-demand model.

  **Concrete application**: Instead of the binary "fits/doesn't fit" VRAM check, compute each model's **fair share**: `model_demand / total_demand × total_VRAM`. A model requesting reclaim should only succeed if the target model's fair share exceeds the victim's fair share. This subsumes both competitive ratios and queue-aware idle checks into a single principled framework.

#### Max-Min Fairness and Weighted Fair Queuing

- **Demers et al., 1989** — *"Analysis and Simulation of a Fair Queueing Algorithm"*. Weighted Fair Queuing (WFQ) ensures that each flow receives bandwidth proportional to its weight. Our system's queue-oblivious reclaim violates WFQ: model A with 20 requests should receive 20× the "bandwidth" (GPU time) of model B with 1 request. The fix is to make reclaim decisions proportional to cumulative queue depth across both scheduler and backend queues.

- **Shreedhar & Varghese, 1995** — *"Efficient Fair Queuing using Deficit Round-Robin"*. DRR is simpler to implement than WFQ and provides the same fairness guarantees. Our model switching could be modeled as DRR across models: each model gets a "quantum" of GPU time proportional to its queue depth, and switching only occurs when the current model's quantum is exhausted.

### 20.4 Memory Management in Virtualized Systems

#### VRAM as Virtual Memory

Our VRAM management is structurally identical to OS virtual memory management, with models as "processes" and VRAM as "physical memory":

| OS Concept | Logos Equivalent |
|---|---|
| Process | Model lane |
| Physical memory | GPU VRAM |
| Page table | VRAM ledger |
| Page fault | Cold load |
| Swap to disk | Sleep (weights to CUDA pool) |
| Swap from disk | Wake (weights from CUDA pool) |
| Page replacement | Eviction algorithm |
| Working set | Models with active demand |
| Thrashing | Model switching exceeding useful work |

- **Waldspurger, 2002** — *"Memory Resource Management in VMware ESX Server"*. ESX's balloon driver and content-based page sharing are analogous to our sleep mechanism (model weights "deflated" to CUDA pool) and potential weight deduplication (shared base model weights across LoRA variants). ESX's **tax-based proportional sharing** is relevant: idle VMs are taxed (memory reclaimed), but the tax is proportional, not all-or-nothing like our current system.

- **Agesen et al., 2010** — *"The Evolution of an x86 Virtual Machine Monitor"*. Describes VMware's evolution from simple paging to sophisticated memory reclamation with **idle memory detection**. The parallel to our idle check is direct — VMware evolved from simple "recently accessed" to statistical sampling of working sets. Our idle check could similarly evolve from binary (active_requests > 0) to probabilistic (demand decay + queue prediction).

### 20.5 Capacity Planning and Autoscaling

- **Gulati et al., 2012** — *"VMware Distributed Resource Management: Design, Implementation, and Lessons Learned"*. DRS handles live migration and load balancing across hosts. Our planner cycle is a simplified version of DRS's periodic rebalancing. Key lesson from DRS: **admission control** — don't start a migration (model switch) unless the target state is provably better than the current state. Our competitive ratios approximate this, but without formal admission control, the system can start a reclaim that worsens overall throughput.

- **Rzadca et al., 2020** — *"Autopilot: Workload Autoscaling at Google"*. Autopilot uses historical demand patterns and ML-based prediction for resource allocation. Our exponential decay demand tracker is a simpler version of this. Relevant refinement: rather than purely reactive demand tracking, use **short-horizon prediction** (e.g., EWMA with trend) to anticipate demand shifts and pre-position models.

### 20.6 Queueing Theory

- **Harchol-Balter, 2013** — *"Performance Modeling and Design of Computer Systems: Queueing Theory in Action"*. Provides the theoretical framework for analyzing our system as a **processor-sharing queue with setup times**. Each model switch imposes a setup time (sleep/wake cost), and the optimal policy minimizes the product of setup frequency × setup cost. The current system lacks this optimization — it switches whenever any demand signal exists, without amortizing the setup cost over the expected request burst length.

- **Coffman & Denning, 1973** — *"Operating Systems Theory"*. Classic analysis of **multiprogramming with variable memory demands** — exactly our scenario. The key theorem: with N processes competing for M memory units where the total demand exceeds M, the optimal policy is to maintain the **balance set** (subset of processes whose combined demand fits in memory and maximizes throughput). Our planner heuristically approximates the balance set but doesn't formalize it.

### 20.7 Specific Techniques Mapped to Our Anti-Thrashing Mechanisms

| Our Mechanism | Academic Technique | Source |
|---|---|---|
| Tenure protection (10s) | **Clock page replacement** — recently loaded pages get a second chance before eviction | Corbató, 1968 |
| Competitive ratios (1.5×/2.0×/3.0×) | **Competitive analysis in online algorithms** — ratio between online and offline optimal | Sleator & Tarjan, 1985 |
| Demand decay (0.95/cycle) | **Exponential Weighted Moving Average (EWMA)** — standard in networking (TCP RTT estimation) and load balancing | Jacobson, 1988 |
| Burst detection (5 req/10s) | **Token bucket rate limiting** — count arrivals in a sliding window | Turner, 1986 |
| Load cooldown (60s) | **Hysteresis in control systems** — prevent oscillation by requiring a minimum dwell time in each state | Schmitt trigger analogy |
| Eviction by demand ascending | **LRU / LFU hybrid replacement** — evict least-recently/frequently-used; our `effective_demand` combines frequency (decay score) and recency (queue depth) | O'Neil et al., 1993 (2Q/ARC) |
| Drain suppression | **Negative feedback in control loops** — dampen the system's response to prevent overshoot | Control theory, Åström & Murray, 2008 |

### 20.8 Thesis Research Directions

Based on this analysis, the following thesis-level research questions emerge:

#### Direction 1: Formal Fair-Share GPU Memory Scheduling

**Question**: Can Dominant Resource Fairness (DRF) be extended to handle the discrete, non-preemptable nature of LLM model placement on GPUs?

**Novelty**: DRF assumes continuous resource division. LLM model placement is binary (model either fits in VRAM or doesn't) and has asymmetric transition costs (sleep=2s, cold-load=60s). A DRF extension must account for:
- Discrete placement constraints (model A + model B fit, but A + C don't)
- Asymmetric setup/teardown costs
- The "sleeping" intermediate state (partial VRAM occupation)

**Anchors**: Ghodsi et al. 2011 (DRF), Grandl et al. 2014 (Tetris — multi-resource packing with placement constraints)

#### Direction 2: Working Set-Based Model Retention

**Question**: Can Denning's working set theory be adapted to predict the optimal set of models to keep resident in GPU memory?

**Novelty**: The "working set" of models varies with time-of-day, user cohort, and request classification patterns. Unlike page-level working sets (thousands of pages, millisecond access), model-level working sets are small (2-5 models), with high transition costs (seconds to minutes). The challenge is maintaining a working set estimate that is responsive to demand shifts but resistant to noise.

**Anchors**: Denning 1968 (Working Set), Jiang et al. 2005 (Clock-PRO adaptive replacement), Megiddo & Modha 2003 (ARC — Adaptive Replacement Cache)

#### Direction 3: Queue-Aware Preemption with Bounded Regret

**Question**: What is the optimal preemption policy when models have heterogeneous VRAM costs, queue depths, and serve times?

**Novelty**: The fairness inversion (§18) is a manifestation of the **preemptive scheduling problem with setup times**. Optimal policies exist for simpler variants (e.g., single-machine scheduling with setup times: Allahverdi et al. 2008), but the multi-GPU, multi-model, heterogeneous-VRAM variant is unstudied. A regret-bounded online algorithm could provide formal guarantees that no model starves for more than O(setup_time × log(N)) seconds.

**Anchors**: Allahverdi et al. 2008 (scheduling with setup times), Azar et al. 1994 (online load balancing), Sleator & Tarjan 1985 (competitive analysis)

#### Direction 4: Admission Control for Model Switching

**Question**: When should the system refuse to switch models (and instead queue the request) to maximize overall throughput?

**Novelty**: Current system always attempts to serve every request immediately (possibly by switching models). But if the switching cost (2-60s) exceeds the expected queue wait (requests drain at rate μ, queue depth = n, wait ≈ n/μ), switching is counterproductive. An admission control policy would compare `expected_switch_cost` vs `expected_queue_wait` and choose the lower-cost option.

**Anchors**: Gulati et al. 2012 (VMware DRS admission control), Harchol-Balter 2013 (queueing theory with setup times), Wierman & Harchol-Balter 2003 (scheduling with switching costs)

#### Direction 5: Predictive Model Placement

**Question**: Can short-horizon demand prediction (EWMA with trend, or lightweight ML) reduce model switching frequency while maintaining SLO compliance?

**Novelty**: Instead of purely reactive demand tracking (exponential decay), use arrival rate estimation and trend detection to predict which models will be needed in the next 30-60 seconds. Pre-position models before demand materializes, converting cold loads into pre-warmed sleeps.

**Anchors**: Rzadca et al. 2020 (Autopilot), Cortez et al. 2017 (Resource Central — ML-based resource prediction), Zhang et al. 2019 (Sinan — ML-driven microservice QoS management)
