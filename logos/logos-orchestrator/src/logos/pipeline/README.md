# Request Pipeline

## Overview

The Request Pipeline plans a request up to a resolved execution context. It decouples three stages:

1.  **Classification**: Analyzing the request to determine candidate models based on prompt content, policies, and model capabilities.
2.  **Scheduling**: Selecting the best available model based on real-time utilization, priority, queue depth, and scheduling policies.
3.  **Context resolution**: Resolving the selected model, provider, endpoint, and authentication inputs.

`RequestPipeline.process()` returns this plan to `main.py`. The response helpers there prepare the provider-specific headers and payload, execute the request, record completion, and release the reservation.

## System Architecture

```
Client
  │ /v1/*, /v2/*, /openai/*
  ▼
main.py: HTTP endpoints, authentication, and logging
  │ RequestPipeline.process()
  ▼
RequestPipeline
  │ classify → schedule → resolve ExecutionContext
  │
  ├─ ClassificationManager
  ├─ ClassificationCorrectingScheduler
  │    ├─ scheduling-data facades
  │    └─ PriorityQueueManager
  └─ ContextResolver ── PostgreSQL
  │
  │ returns PipelineResult
  ▼
main.py: reads result.execution_context
  │ _sync_response() / _streaming_response()
  │ ContextResolver.prepare_headers_and_payload()
  │
  ├─ LogosNode provider ── registry RPC
  └─ HTTP provider ─────── Executor
  │
  ▼
Response, logging, completion recording, and scheduler.release()
```

## Request Flow

### 1. Happy Path (Immediate Execution)

1.  **Request Arrives**: `main.py` receives the request and delegates classification, scheduling, and context resolution to `RequestPipeline.process()`.
2.  **Classification**: `ClassificationManager` ranks models based on policy and weights.
3.  **Scheduling**: `ClassificationCorrectingScheduler` expands eligible model deployments and, by default, estimates expected time to first token to re-rank only the classified candidates. When ETTFT correction is disabled, it preserves classification weights while still expanding deployments and checking availability.
    *   It reserves an available LogosNode lane or selects an available cloud deployment; otherwise it queues against the best eligible local candidate.
4.  **Execution**: `RequestPipeline.process()` returns a `PipelineResult`, and `main.py` reads `result.execution_context`. `_sync_response` or `_streaming_response` then calls `ContextResolver.prepare_headers_and_payload()` and uses LogosNode registry RPC or the HTTP `Executor`.
5.  **Release**: The response helpers record completion and call `scheduler.release()` to free capacity and check for queued requests.

### 2. Queued Path (Busy Models)

1.  **Scheduling**: If eligible local candidates are busy, cold, sleeping, or otherwise unavailable:
    *   The scheduler creates an `asyncio.Future`.
    *   It enqueues the future into `PriorityQueueManager` (HIGH/NORMAL/LOW), together with the request's estimated work in tokens (`estimated_work_tokens()` in `context_budget.py` — prompt plus reserved output, 0 when unreadable).
    *   It `await`s the future, pausing the request execution.
2.  **Waiting**: The request remains suspended until a slot opens up. Queues use strict HIGH, then NORMAL, then LOW priority ordering; priorities are not automatically promoted. **Within one priority level, shorter estimated work dispatches before longer work** (then arrival time, FIFO), and requests whose work could not be estimated (0) keep the arrival order but sort after the estimated ones. This is what keeps small latency-sensitive requests — e.g. Claude Code's auto-permission classifier requests (#828) — from waiting for every long-running request that arrived before them when the queue fills under load. The estimate is derived from the payload the server already holds, so it cannot be gamed by the client.
3.  **Wake Up**: When another request finishes:
    *   `scheduler.release()` calls `queue_mgr.dequeue_with_entry()`.
    *   It finds the highest priority waiting future (shortest work first within the level).
    *   It calls `future.set_result()`, waking up the suspended request.
4.  **Resumption**: The `await` returns, and the request proceeds to **Execution**.

### 3. Direct-model path

When a request names a model, `main.py` first verifies access and limits deployments to that model. The pipeline then runs with `skip_laura=True`: it skips Laura's ML ranking, but still applies privacy policy, policy and token filtering, provider/deployment scheduling, and context resolution. After `process()` returns, `main.py` performs execution and completion recording through the same response helpers.

### 4. Execution readiness

`ContextResolver` resolves an execution context that includes the forward URL and credential header/value. Later, the response helper uses that context to assemble the headers and provider-adjusted payload. Readiness retries are deliberately narrow: the pipeline retries an absent execution context only for a scheduled LogosNode provider while a lane is becoming available. Cloud providers do not inherit that local-lane retry behavior.

### Queue priority resolution

The priority a request is queued with is resolved by `resolve_queue_priority()` in `pipeline.py` before scheduling:

- **The API key's `default_priority` wins** when set (non-zero). It is configured per key in the admin UI ("Queue Priority"), so a key owner's explicit choice determines where that key's traffic sits in the queue, regardless of the policy.
- **The policy-level `priority` is the fallback** when the key has none set (`0`, the default for newly created keys): the request queues with the priority of the policy selected for it (or `0` → NORMAL when no policy applies).

Both values use the same 1/5/10 scale (LOW/NORMAL/HIGH, see `queue/models.py`); non-canonical values are normalized by `Priority.from_int`. The resolved value is applied to every classified candidate, so the schedulers, the priority queues, the monitoring events, and the logged classification stats all agree on it.

## Pipeline Components

### Core Files in `src/logos/pipeline/`

```
pipeline/
├── pipeline.py                 # Main RequestPipeline orchestrator
├── scheduler_interface.py      # Abstract scheduler interface & data models
├── base_scheduler.py           # Shared provider, capacity, and queue helpers
├── fcfs_scheduler.py           # Top-classified-candidate scheduler
├── utilization_scheduler.py    # Availability-aware scoring scheduler
├── correcting_scheduler.py     # Production ETTFT-correcting scheduler
├── ettft_estimator.py          # Provider-specific readiness and wait estimates
├── executor.py                # Backend execution & API calling
└── context_resolver.py        # Database resolution for models/providers
```

### `pipeline.py` - RequestPipeline
**The request-planning orchestrator.** Coordinates the request up to a resolved execution context:
- Delegates to `ClassificationManager` to rank candidate models
- Calls scheduler to select best available model
- Uses `ContextResolver` to resolve provider, routing, and authentication inputs
- Returns a `PipelineResult`; `main.py` reads its `execution_context`

### `scheduler_interface.py` - SchedulerInterface
**Abstract interface** defining the scheduler contract:
- `SchedulingRequest`: Input data structure (candidates, priority, timeout)
- `SchedulingResult`: Output data structure (selected model, queue state, metrics)
- `SchedulerInterface`: Abstract base class with methods:
  - `schedule()`: Select and reserve a model
  - `release()`: Free capacity when request completes
  - `get_total_queue_depth()`: Query current queue state
  - `update_provider_stats()`: Update rate limits from response headers

### `base_scheduler.py` - BaseScheduler
**Shared scheduler logic.** Implements common functionality:
- Integrates with `PriorityQueueManager` for request queuing
- Manages SDI facades (`LogosNodeSchedulingDataFacade`, `AzureSchedulingDataFacade`)
- Tracks per-model provider and deployment types (LogosNode/cloud)
- Provides helper methods for queue management and metrics collection
- Uses strict HIGH → NORMAL → LOW dequeue ordering for queued requests (shorter estimated work first within a level)
- Uses the model-only `PriorityQueueManager`; its compatibility `provider_id` arguments are ignored

### `fcfs_scheduler.py` - FcfScheduler
**Top-candidate scheduler.** Tries every deployment of the highest-ranked classified model. When queueing, it uses the first matching LogosNode deployment as representative metadata and enqueues by model.

### `utilization_scheduler.py` - UtilizationAwareScheduler
**Availability-aware scheduler.** Scores deployments for immediate selection. When queueing, it chooses the highest-weight classified model with a LogosNode deployment, uses the first matching deployment as representative metadata, and enqueues by model.

### `correcting_scheduler.py` - ClassificationCorrectingScheduler
**Production scheduler.** By default, re-ranks only the classifier's eligible candidates using expected-time-to-first-token (ETTFT) penalties. `LOGOS_SCHEDULER_ETTFT_ENABLED=false` preserves classification weights/order while retaining deployment expansion and availability checks:
- Expands each classified model across all eligible deployments/providers
- Combines the classification weight with provider-specific readiness and wait estimates
- Never promotes a model that classification excluded
- Reserves available LogosNode capacity or accepts an available cloud deployment
- Queues on the best eligible local candidate when no candidate is immediately available
- Uses the shared strict-priority queues from `BaseScheduler`

### `executor.py` - Executor
**HTTP backend client.** Used by `main.py` for non-LogosNode providers:
- Consumes `execution_context.forward_url` plus the headers and payload prepared by the response helper
- Performs synchronous or streaming upstream HTTP requests
- Extracts token usage from synchronous responses
- Does not write to the database; `RequestPipeline` and `MonitoringRecorder` record pipeline lifecycle fields, while the main response helpers persist response payloads and extract streaming usage
- Handles errors and timeouts gracefully
- LogosNode providers bypass `Executor` and use registry RPC

### `context_resolver.py` - ContextResolver
**Database and execution-preparation layer.** Fetches runtime configuration:
- Looks up model details (name, endpoint)
- Retrieves provider information (base URL, auth)
- Resolves an `ExecutionContext` during `RequestPipeline.process()`
- Prepares provider-specific headers and payload when called by the main response helpers
- Lightweight database queries to minimize overhead

## Dependencies

The pipeline integrates several modules together

### Classification (`../classification/`)
- `ClassificationManager`: Ranks models based on policies and weights
- `PolicyClassifier`: Policy-based filtering
- `TokenClassifier`: Token-count based selection
- `AIClassifier`: AI-powered classification
- `LauraEmbeddingClassifier`: Embedding-based model matching

### Scheduling Data Interface (`../sdi/`)
- `LogosNodeSchedulingDataFacade`: Real-time LogosNode lane, queue, and model-loading state
- `AzureSchedulingDataFacade`: Rate limits and quota tracking
- Provides availability data for intelligent scheduling decisions

### Priority Queue (`../queue/`)
- `PriorityQueueManager`: Per-model priority queues
- `Priority` enum: LOW, NORMAL, HIGH
- Strict HIGH → NORMAL → LOW dequeue ordering (no automatic promotion); within a level, shorter estimated work first, then arrival time (work of 0 = unreadable payload sorts last among known work)

### Monitoring (`../monitoring/`)
- `MonitoringRecorder`: Logs request lifecycle events and performance metrics
- `prometheus_metrics`: Exposes pipeline and provider metrics

### Database (`../dbutils/`)
- `DBManager`: Database connection and query execution
- Schema: models, providers, log_entry
