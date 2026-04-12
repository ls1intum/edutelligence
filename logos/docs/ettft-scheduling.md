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

## 10. Configuration

| Parameter | Default | Location | Effect |
|-----------|---------|----------|--------|
| `ettft_enabled` | `True` | Scheduler constructor | Enable/disable ETTFT correction (ablation switch) |
| `CORRECTION_STRENGTH` | `1.5` | `ettft_estimator.py` | Penalty multiplier (higher = more aggressive infrastructure-awareness) |
| `NORMALIZATION_HORIZON_S` | `60.0` | `ettft_estimator.py` | Wait duration at which penalty saturates |
| `OVERHEAD_COLD_S` | `45.0` | `ettft_estimator.py` | Cold load time estimate |
| `OVERHEAD_SLEEPING_S` | `2.5` | `ettft_estimator.py` | Sleep→wake transition estimate |
| `OVERHEAD_RECLAIM_S` | `8.0` | `ettft_estimator.py` | VRAM eviction overhead |
| `DEFAULT_GENERATION_TIME_S` | `3.0` | `ettft_estimator.py` | Per-request generation time for queue wait estimation |
