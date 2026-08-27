# ETTFT-Corrected Classification Scheduling (ECCS)

## 1. Problem Statement

Multi-model inference on VRAM-constrained hardware creates a fundamental tension: **classification accuracy** (choosing the right model for the task) and **infrastructure responsiveness** (choosing a model that can serve the request quickly) are competing objectives.

A classification layer scores models by task suitability — policy compliance, token budget matching, pedagogical ranking. But it is **infrastructure-blind**: it cannot know whether the top-ranked model is loaded in GPU memory (0s latency), sleeping with weights retained (2.5s wake), or entirely cold (45s load from disk requiring VRAM eviction).

The naive approach — always serving the classification winner — degrades into pathological behavior under VRAM contention. When 3 models compete for 2 GPU slots, the classifier's top choice is cold ~33% of the time, producing 45-second delays even when an equally-suitable model is already warm.

## 2. Core Insight

Classification scores are **task-optimal but deployment-unaware**. Infrastructure state introduces a **cost-to-serve** dimension that the classifier cannot observe. The key insight is that this cost can be expressed as a **range-scaled additive penalty** in the same unit space as classification weights, enabling principled score correction without destroying the classifier's rankings for models in the same infrastructure state.

## 3. Formal Definition

### Corrected Score

```
corrected(m, p) = w(m) - penalty(m, p)
```

where `w(m)` is the classification weight for model `m` and `penalty(m, p)` accounts for the expected wait on provider `p`.

### Range-Scaled Additive Penalty

```
penalty = min(E[wait] / H, 1.0) × S × α
```

| Symbol | Name | Value | Description |
|--------|------|-------|-------------|
| `E[wait]` | Expected wait | varies | Infrastructure overhead + queue wait (seconds) |
| `H` | Normalization horizon | 60s | Maximum expected wait before penalty saturates |
| `S` | Weight span | computed | Dynamic range of candidate classification weights |
| `α` | Correction strength | 1.5 | Penalty multiplier (allows infrastructure to override classification when cost is extreme) |

### Weight Span

The span adapts the penalty magnitude to the current candidate set:

```
S = max(w_max - w_min, max(|w_max|, |w_min|) × 0.2, 1.0)
```

This handles:
- **Normal case**: span = classification score range (penalty proportional to how much the classifier cares about ordering)
- **Close weights**: 20% floor prevents vanishing corrections when candidates are similarly ranked
- **Negative weights**: classification rebalances around median of 0, so weights can be negative. Additive penalty correctly subtracts from both positive and negative scores.
- **Single candidate**: floor of 1.0 ensures non-trivial penalty even with one option

### Expected Wait Decomposition

```
E[wait] = state_overhead + queue_wait
queue_wait = (queue_depth / effective_parallel) × generation_time
```

Where `effective_parallel` includes vLLM's 3× concurrency oversubscription.

## 4. Infrastructure Tiers

The estimator maps runtime state + VRAM availability into six tiers:

| Tier | Overhead (s) | Condition | Description |
|------|-------------|-----------|-------------|
| **WARM** | 0.0 | Lane loaded/running | Serve immediately |
| **SLEEPING** | 2.5 | Lane sleeping, KV cache fits in available VRAM | Wake from L1 sleep (weights on GPU, allocate KV cache) |
| **SLEEPING_RECLAIM** | 10.5 | Lane sleeping, KV cache > available VRAM | Must evict another model's KV cache first, then wake |
| **COLD** | 45.0 | Lane cold/starting, model fits in available VRAM | Cold load from disk |
| **COLD_RECLAIM** | 53.0 | Lane cold, model > available VRAM | Must evict another model to free VRAM, then cold load |
| **UNAVAILABLE** | ∞ | No lanes / all stopped/error | Cannot serve; logosnode models queue as COLD fallback |

VRAM-awareness (the reclaim variants) is critical: without it, the estimator would assign the same cost to a cold model that fits in free VRAM (45s) and one that requires evicting an active model first (53s). The 8s reclaim overhead accounts for the sleep/stop + VRAM deallocation cycle.

## 5. Multi-Provider Expansion

The scheduler expands each `(model_id, weight)` across **all** matching deployments:

```
candidates × deployments → scored_candidates
```

For example, model X on logosnode (sleeping, E[wait]=2.5s) and Azure (warm, E[wait]=0.3s) produces two entries with the same classification weight but different penalties. Azure (0.3s) beats sleeping logosnode (2.5s) for the same model.

Key rules:
- **Cloud providers never queue**: accept (WARM/BUSY) or reject (UNAVAILABLE) immediately
- **Only logosnode deployments queue**: when no candidate can be served immediately, the request queues on the highest-scored logosnode candidate
- **Same model, two logosnode providers**: both are scored independently — a loaded provider-B beats cold provider-A

## 6. Properties

### Same-State Ordering Invariant

Two models in the **same infrastructure state** receive **identical penalties** (because `E[wait]` depends only on state + queue, not on classification weight). This means:

```
state(A) = state(B) ⟹ corrected(A) > corrected(B) ⟺ w(A) > w(B)
```

The classifier's relative ordering is preserved within each infrastructure tier. ETTFT correction only reranks across tiers.

### Bounded Correction

The maximum penalty is `S × α = weight_span × 1.5`. This means:
- A cold model (45s) can be penalized by up to **112.5%** of the weight span (0.75 × 1.5 = 1.125×), enough to overcome most classification advantages
- A sleeping model (2.5s) is penalized by only **6.25%** of the span (0.042 × 1.5), barely noticeable but sufficient to break ties
- At the extreme, only models with wait ≥ 40s lose more than 100% of the weight span

### Ablation

Setting `ettft_enabled=False` disables correction entirely: `corrected = w(m)`. This provides a clean baseline for evaluating whether infrastructure-aware reranking improves system throughput.

## 7. Scientific Connections

### 7.1 Ski Rental Problem (Competitive Analysis)

The decision "should I pay 45s to cold-load model A, or use already-warm model B?" is a variant of the **ski rental problem** (Karlin et al., 1988). The rental cost is the classification quality delta; the purchase cost is the cold-load latency. Our competitive ratios in the capacity planner (1.5× wake, 2.0× load, 3.0× drain) are analogous to the deterministic 2-competitive algorithm for ski rental.

> Karlin, A. R., Manasse, M. S., Rudolph, L., & Sleator, D. D. (1988). Competitive snarky algorithms for paging in the dark. *ACM SIGACT News*, 19(2), 86-90.

### 7.2 Multi-Armed Bandit with Switching Costs

Model selection under state-dependent costs maps to the **multi-armed bandit problem with switching costs** (Agrawal et al., 1988). Each model is an arm; the reward is classification quality; pulling a different arm incurs a switching cost (model swap latency). The ETTFT correction acts as a state-dependent cost adjustment that biases toward the currently-loaded "arm," reducing unnecessary switching.

> Agrawal, R., Hedge, M. V., & Teneketzis, D. (1988). Asymptotically efficient adaptive allocation rules for the multiarmed bandit problem with switching cost. *IEEE Transactions on Automatic Control*, 33(10), 899-906.

### 7.3 Admission Control and Queueing Theory

The queue-capacity-normalized penalty (`queue_rounds = depth / parallel`) follows standard **admission control** formulations from queueing theory. The expected wait scales linearly with queue depth and inversely with service capacity, matching the M/M/c queue mean wait approximation. The generation time parameter acts as the service rate inverse.

> Kleinrock, L. (1975). *Queueing Systems, Volume I: Theory*. Wiley-Interscience.

### 7.4 Virtual Memory and Working Set Model

VRAM management in the capacity planner directly parallels Denning's **working set model** (1968) for virtual memory. GPU VRAM is physical memory; models are processes; loading/evicting models is page-in/page-out. The anti-thrash tenure (5s grace period) mirrors the working set window that prevents thrashing. The reclaim tiers (COLD_RECLAIM, SLEEPING_RECLAIM) correspond to page faults that require eviction.

> Denning, P. J. (1968). The working set model for program behavior. *Communications of the ACM*, 11(5), 323-333.

### 7.5 Cost-Aware Scheduling

The range-scaled penalty is a form of **cost-aware scheduling** where the "cost" is deployment latency. This approach appears in Hadoop YARN's capacity scheduler (Vavilapalli et al., 2013) and Kubernetes resource-aware scheduling, where placement decisions balance task affinity (analogous to classification weight) against resource availability (analogous to ETTFT).

> Vavilapalli, V. K., et al. (2013). Apache Hadoop YARN: Yet another resource negotiator. *Proceedings of the 4th annual Symposium on Cloud Computing*, 1-16.

### 7.6 Range-Scaled Utility Correction

The normalization by weight span is related to **range normalization** in multi-criteria decision making (MCDM). By expressing the penalty as a fraction of the classification score range, the correction magnitude adapts to the classifier's confidence distribution, avoiding both over-correction (when weights are tightly clustered) and under-correction (when weights are spread).

> Hwang, C. L., & Yoon, K. (1981). *Multiple Attribute Decision Making: Methods and Applications*. Springer-Verlag.

## 8. Benchmark Evidence

Comprehensive benchmarks comparing LogosWorkerNode (with ECCS) against raw Ollama (without orchestration) on identical hardware (2×16GB GPUs, TP=2) demonstrate the approach's effectiveness.

See [`docs/benchmark-results-analysis.md`](benchmark-results-analysis.md) for full analysis. Key results at 600 requests over 10 minutes:

| Metric | LogosWorkerNode | Ollama | Speedup |
|--------|----------------|--------|---------|
| P50 TTFT | 42.4s | 360.4s | **8.5×** |
| P95 TTFT | 117.8s | 1,237.0s | **10.5×** |
| Success rate | 100% | 99.3% | — |

The advantage grows super-linearly with load because Ollama's lack of scheduling causes O(n) queue buildup while ECCS maintains bounded latencies through infrastructure-aware model selection and queue-fair capacity management.

## 9. System Architecture

```
Request → Classification Layer → ECCS Scheduler → Provider
              ↓                       ↓
        w(m) weights          corrected(m,p) scores
                                     ↓
                              Multi-Provider Expansion
                              (model × deployment)
                                     ↓
                              ETTFT Estimation
                              (view + VRAM + queue)
                                     ↓
                              Immediate Select or Queue
                                     ↓
                              Capacity Planner
                              (wake/load/evict signals)
```

### Components

1. **ETTFT Estimator** (`ettft_estimator.py`): Pure-function module. Maps `ModelSchedulerView` + VRAM state → `EttftEstimate` with expected wait decomposition.

2. **Correcting Scheduler** (`correcting_scheduler.py`): Expands candidates across deployments, computes range-scaled scores, attempts immediate reservation, queues on logosnode if needed.

3. **Capacity Planner** (`capacity_planner.py`): Background loop managing VRAM ledger, sleep/wake lifecycle, demand-aware eviction. Receives `on_capacity_needed` signals from the scheduler to short-circuit the 30s planning cycle.

4. **Queue Manager** (`priority_queue.py`): Per-(model_id, provider_id) priority queues with starvation prevention (priority aging: LOW→NORMAL after 10s, NORMAL→HIGH after 30s).

## 10. Orchestrator-Level Admission Control

Scoring decides *where* a request should go; admission decides *whether it should leave the orchestrator at all*. The two are separate on purpose.

A request that has been forwarded to a worker is committed. It sits in the engine's own queue, where the orchestrator can no longer:

1. **hand it back** — a worker asked to drain for a restart must first finish everything already forwarded, so wait-mode takes longer the deeper the engine queue is;
2. **reorder it** — a high-priority request arriving later cannot jump ahead of what is already inside the engine;
3. **re-route it** — a peer worker that frees a slot first cannot take over;
4. **place it well** — the prefix-affinity decision below is fixed at forward time and cannot be revisited.

None of that is lost while the request waits in the orchestrator queue. So the orchestrator forwards only what a worker can *start*, and keeps the rest.

### Signals

Admission reads the live lane signals the worker reports (the same ones §4 uses for tier estimation):

**Nothing outside the engine can predict whether vLLM will start a given request or park it.** That depends on whether the new sequence's KV blocks fit against what the running sequences currently occupy — neither exposed nor derivable from the outside. The engine reports the answer only afterwards, as `num_requests_waiting`. Admission is therefore retrospective by necessity: forward while nothing is observed waiting, stop at the first observed waiter. The engine-side queue then hovers at about one request — enough lookahead that the GPU never idles between generations, few enough that essentially everything stays re-prioritisable and re-routable.

| Signal | Source | Gate |
|--------|--------|------|
| `queue_waiting` | vLLM `num_requests_waiting` | The engine is already parking work → hold (`BACKEND_QUEUE_PRESSURE_THRESHOLD`, a constant — see §12) |
| forwarded since the last report | orchestrator-local | Step used up → hold as `awaiting_signal` until the worker reports back |
| `gpu_cache_usage_percent` | vLLM `gpu_cache_usage_perc` | ≥ 90% → hold: vLLM is about to preempt and recompute, which also evicts the prefix-cache blocks §11 depends on |

**`num_parallel` is deliberately not used as a ceiling.** It is the concurrency vLLM guarantees *at full context* — the "Maximum concurrency for N tokens per request" line from its startup log, which the lane-health panel shows as `(min. c)`. Real requests use a fraction of their context, so the engine runs far past it: a production lane serves 8 concurrent requests with `num_parallel = 1` at 78% KV. Read as a ceiling, that lane would be throttled eightfold. It is a *lower bound on capacity*, which makes it sound as a step size and wrong as a limit.

**The signals are sampled, so the gate also counts its own sends.** Every request arriving inside one sampling window reads the same `queue_waiting`, so a simultaneous burst passes untouched — measured on logos-dev, 60 concurrent requests produced zero holds. The orchestrator therefore tracks what it has forwarded since the current worker report and spends `batch_limit` down by it, holding with reason `awaiting_signal` once the step is used up. The next report supersedes the estimate with a measurement and restores the budget, which is why a worker status also re-evaluates the queues (`on_worker_report`) — otherwise a held request would wait for the next completion, and on a ramp from idle nothing has completed yet. Measured feedback latency on dev: **0.21–1.11s, median ~0.9s**, because the worker marks its status dirty when a lane's in-flight count changes rather than waiting for its refresh interval.

The unit of the decision is `AdmissionDecision(can_admit, batch_limit, reason)`. `batch_limit` is how many queued requests one dispatch pass may release — `num_parallel` scaled by the free KV fraction (the same floating figure the panel shows), at least 1 — summed over the model's admissible lanes; a backlogged lane never masks an idle sibling. When a worker reports nothing usable (older worker, lane still starting), `batch_limit` is `None` and the decision falls back to the parallel-capacity gate alone — admission is never stricter than the signals justify.

Two call sites use it:

- **`try_reserve_capacity`** — the arrival path. A refusal sends the request to the orchestrator queue instead of the worker.
- **`reevaluate_model_queues`** — the batch dispatcher that runs after a lane loads or wakes. Its batch size is `min(parallel_capacity − active, batch_limit)`, so a wake event cannot drain the whole queue onto one worker in a single pass.

> **Operator note.** `providers.parallel_capacity` short-circuits the live path entirely: `get_parallel_capacity` returns the configured value whenever it differs from the `200` default, so the worker-reported `num_parallel` is never consulted. Every production provider currently has `parallel_capacity = 20`, which means the per-worker ceiling is a flat 20 and the live-signal capacity introduced in #781 is dormant. The gate described here reads the lane signals directly and is unaffected, but anyone reasoning about the ceiling should know which of the two is actually in force.

The release path (slot transfer on completion) is deliberately *not* gated: a completing request hands its slot straight to the next waiter, which is the mechanism that keeps the engine busy while admission holds new arrivals back.

### Cancelling what was already forwarded

Holding requests back shrinks the window but does not close it: a request that *was* forwarded and whose client then goes away still occupies a lane. On the HTTP path that resolves itself — closing the httpx context closes the connection and vLLM aborts the sequence. Worker requests have no such connection: every request to a worker is multiplexed over one WebSocket, so dropping the local queue only stops the orchestrator from reading. The lane kept generating a response nobody would read, for the full length of the generation.

The bridge therefore carries a `cancel_command` action:

```text
orchestrator                              worker
     │  infer_stream (cmd_id=X)              │
     │─────────────────────────────────────▶ │  relay task X ──▶ lane (httpx stream)
     │  ◀──── stream_chunk … ─────────────── │
     ▽  client disconnects                   │
     │  cancel_command (target_cmd_id=X)     │
     │─────────────────────────────────────▶ │  task X cancelled
     │                                       │    └─ httpx stream closed ──▶ vLLM aborts,
     │  ◀──── command_result {cancelled}──── │       KV blocks freed, in-flight count released
```

Cancelling the relay task is what closes the stream to the lane, and that closed connection is what makes vLLM abort. Details that matter:

- **Both paths.** `infer` (non-streaming) is cancelled the same way; worker command tasks are keyed by `cmd_id` so one request can be targeted without touching its neighbours.
- **Feature-gated.** Only workers that list `cancel_command` in their hello are sent one; an older worker keeps the previous behaviour rather than answering "Unsupported bridge command".
- **Fire-and-forget.** The cancellation is dispatched while a cancelled caller unwinds, so it must not block on the worker answering. The reply only reports whether anything was still running — a cancel racing a completing stream is normal.
- **Deterministic close.** The response generator wraps the worker stream in `contextlib.aclosing`; a bare `async for` would defer the cleanup that sends the cancellation to the async-generator GC hook.

This also keeps the admission signals honest: a ghost generation inflates `requests_running` and KV usage, so without it the gate above would throttle traffic on load that no longer exists.

## 11. Prefix-Cache-Aware Placement

With the same model deployed on several workers, two warm workers tie on corrected score and the tie-break is random. For a coding agent that is the worst possible placement: every turn re-sends a prompt the *previous* worker already has in its KV cache, and a random landing throws that cache away.

### Stream identity

A stream is neither a user nor an API key — one key can drive many agent loops at once. Identity is `(api_key_id, actual request prefix)`, hashed into a chain of fixed-size blocks the way an engine hashes its own prefix-cache blocks:

```text
block₁ = H(api_key_id ‖ text[0:B])
blockᵢ = H(blockᵢ₋₁  ‖ text[(i−1)B : iB])
```

The prompt is serialized append-only (preamble fields, then one record per message), so turn *n+1* extends turn *n*'s string rather than rewriting it and the leading block hashes survive. Only whole blocks are hashed — the trailing partial block is dropped, exactly as an engine drops its own. Lookup walks the blocks deepest-first, so the longest shared prefix wins: two conversations under one key that share only a system prompt match on the early blocks and separate as soon as their first user turns differ.

The map (`PrefixAffinityRouter`) is soft state — an in-memory TTL/LRU table. Losing it costs one round of cache misses.

### Scoring

A hit does not pin the request. It adds a bounded bonus to the corrected score:

```text
bonus = weight_span × CORRECTION_STRENGTH × PREFIX_AFFINITY_BONUS_FRACTION
```

At the default `0.25` that is worth roughly 15s of expected wait (penalty saturates at 60s). The stream stays on the familiar worker unless a peer is *meaningfully* faster — the "if cheaply possible" the routing is meant to honour. The bonus applies only to `WARM` candidates, so affinity never wakes a sleeping worker or triggers a cold load just to stay put, and only logosnode placements are recorded: cloud upstreams route internally.

## 12. Configuration

| Parameter | Default | Location | Effect |
|-----------|---------|----------|--------|
| `ettft_enabled` | `True` | Scheduler constructor | Enable/disable ETTFT correction (ablation switch) |
| `CORRECTION_STRENGTH` | `1.5` | `ettft_estimator.py` | Penalty multiplier (higher = more aggressive infrastructure-awareness) |
| `NORMALIZATION_HORIZON_S` | `60.0` | `ettft_estimator.py` | Wait duration at which penalty saturates |
| `OVERHEAD_COLD_S` | `45.0` | `ettft_estimator.py` | Cold load time estimate |
| `OVERHEAD_SLEEPING_S` | `2.5` | `ettft_estimator.py` | Sleep→wake transition estimate |
| `OVERHEAD_RECLAIM_S` | `8.0` | `ettft_estimator.py` | VRAM eviction overhead |
| `LOGOS_PREFIX_AFFINITY_ENABLED` | `true` | env | Master switch; off restores random tie-break placement |
| `BACKEND_QUEUE_PRESSURE_THRESHOLD` | `0` | `logosnode_provider.py` | Engine-side `queue_waiting` tolerated before holding. Derived, not tuned: any value above zero re-introduces the engine-side queueing the gate removes |
| `KV_CACHE_PRESSURE_PERCENT` | `90` | `logosnode_provider.py` | KV utilisation at which a lane stops being a forwarding target |
| `PREFIX_AFFINITY_BONUS_FRACTION` | `0.25` | `correcting_scheduler.py` | Affinity bonus as a fraction of the maximum ETTFT penalty (~15s of expected wait) |
| `AFFINITY_TTL_S` / `AFFINITY_BLOCK_CHARS` / `AFFINITY_MAX_BLOCKS` / `AFFINITY_MAX_ENTRIES` | `900` / `1024` / `32` / `20000` | `prefix_affinity.py` | Stream-identity granularity and table bounds |

### Metrics

| Metric | Labels | Meaning |
|--------|--------|---------|
| `logos_admission_holds_total` | `reason` = `worker_capacity` \| `backend_queue` \| `kv_cache_pressure` \| `engine_at_capacity` | Requests kept at orchestrator level instead of forwarded |
| `logos_prefix_affinity_total` | `result` = `hit` \| `miss` \| `honored` \| `diverted` | Affinity lookups and whether the scheduler followed them |
| `logos_worker_cancellations_total` | `result` = `aborted` \| `already_done` \| `unsupported` \| `failed` | Cancellations sent for abandoned requests. `unsupported` counts nodes that still leak ghost generations — the number to watch during a rolling worker upgrade |

Two reporting defects in the existing metrics are fixed alongside:

- **`logos_requests_in_flight` only ever rose.** The gauge was hand-maintained with paired `inc()`/`dec()` calls and the pairing did not hold in either direction: terminal paths that write their own log row (client disconnect, rate-limit and budget rejects) never told the recorder the request had ended — production leaked ~470 of them a day — while a request rejected at classification completed without ever having been enqueued and decremented a count it had never added. The gauge is now *derived* from the map of tracked requests, so neither is expressible, and the failure paths release their request through `_record_log_failure`. A sweep drops anything tracked for more than two hours, so a future missed path degrades into a bounded inaccuracy instead of a number that never comes down.
- **Latency percentiles were pinned to two minutes.** `histogram_quantile` cannot report above the highest *finite* bucket, and `logos_request_duration_seconds` topped out at `120.0`. With 5% of production requests over 120s, p95 sat exactly on that edge and p99 (really ~300s, tail past 1600s) was clamped to 120s outright — which read as a dashboard fault. The upper buckets now run to 3600s, covering the 1200s queue-wait bound plus cold load and generation.
| `DEFAULT_GENERATION_TIME_S` | `3.0` | `ettft_estimator.py` | Per-request generation time for queue wait estimation |
