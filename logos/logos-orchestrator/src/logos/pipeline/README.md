# Request Pipeline

## Overview

The Request Pipeline orchestrates the lifecycle of a request from entry to execution. It decouples the three main stages of request handling:

1.  **Classification**: Analyzing the request to determine candidate models based on prompt content, policies, and model capabilities.
2.  **Scheduling**: Selecting the best available model based on real-time utilization, priority, queue depth, and scheduling policies.
3.  **Execution**: Resolving backend details (endpoints, API keys) and performing the actual API call with proper error handling.

## System Architecture

```
┌───────────────────────────────────────────────────────────────────────────┐
│                         Logos System Architecture                         │
└───────────────────────────────────────────────────────────────────────────┘

                                 ┌──────────┐
                                 │  Client  │
                                 │ (OpenAI  │
                                 │   API)   │
                                 └─────┬────┘
                                       │
                    /v1/*, /openai/*, /chat/completions
                                       │
                                       ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                          HTTP Layer (main.py)                             │
│                  FastAPI endpoints + Auth + Logging                       │
└───────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
╔═══════════════════════════════════════════════════════════════════════════╗
║                  ┌─────────────────────────────────────┐                  ║
║                  │  REQUEST PIPELINE (src/logos/pipeline/)                ║
║                  │  Core orchestration layer           │                  ║
║                  └─────────────────────────────────────┘                  ║
║                                                                           ║
║  ┌────────────────────────────────────────────────────────────────────┐   ║
║  │               pipeline.py - RequestPipeline                         │  ║
║  │      Orchestrates: classify → schedule → execute → monitor          │  ║
║  └────────────────────────────────────────────────────────────────────┘   ║
║            │                         │                         │          ║
║            ▼                         ▼                         ▼          ║
║  ┌──────────────────┐   ┌───────────────────────┐   ┌────────────────── ┐ ║
║  │ executor.py      │   │  Scheduler Layer      │   │context_resolver.py║ ║
║  │                  │   │                       │   │                   │ ║
║  │ • HTTP requests  │   │scheduler_interface.py │   │ • Model/provider  │ ║
║  │ • Sync responses │   │  SchedulerInterface   │   │   lookup          │ ║
║  │ • Streaming      │   │         │             │   │ • Endpoint/auth   │ ║
║  │ • Usage parsing  │   │         ▼             │   │   resolution      │ ║
║  │ • Error handling │   │  base_scheduler.py    │   │                   │ ║
║  │ • Error handling │   │    BaseScheduler      │   │                   │ ║
║  │                  │   │         │             │   │                   │ ║
║  │                  │   │         ▼             │   │                   │ ║
║  │                  │   │correcting_scheduler.py│   │                   │ ║
║  │                  │   │ (active; FCFS and     │   │                   │ ║
║  │                  │   │ utilization variants)│   │                   │ ║
║  └──────────────────┘   └──────────┬────────────┘   └───────────────────┘ ║
║                                    │                                      ║
╚════════════════════════════════════┼══════════════════════════════════════╝
                                     │
              ┌──────────────────────┼──────────────────────┐
              ▼                      ▼                      ▼
    ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
    │ Classification   │   │  SDI (Scheduling │   │ PriorityQueueMgr │
    │ (../classification)  │   Data Interface)│   │   (../queue/)    │
    ├──────────────────┤   │     (../sdi/)    │   ├──────────────────┤
    │ClassificationMgr │   ├──────────────────┤   │ • LOW priority   │
    │ PolicyClassifier │   │ LogosNode facade │   │ • NORMAL         │
    │ TokenClassifier  │   │  - /api/ps polls │   │ • HIGH           │
    │ AIClassifier     │   │  - VRAM tracking │   │ • Per-model      │
    │ LauraEmbedding   │   │ Azure facade     │   │   queues         │
    │                  │   │  - Rate limits   │   │ • Strict HIGH →  │
    │Ranks & weights   │   │  - Quotas        │   │   NORMAL → LOW   │
    └──────────────────┘   └──────────────────┘   └──────────────────┘
                                     │
                                     ▼
                        ┌──────────────────────────┐
                        │  Database (PostgreSQL)   │
                        │  - models, providers     │
                        │  - log_entry, jobs       │
                        └──────────────────────────┘
```

## Request Flow

### 1. Happy Path (Immediate Execution)

1.  **Request Arrives**: `main.py` receives the request and delegates to `RequestPipeline.process()`.
2.  **Classification**: `ClassificationManager` ranks models based on policy and weights.
3.  **Scheduling**: `ClassificationCorrectingScheduler` expands eligible model deployments and, by default, estimates expected time to first token to re-rank only the classified candidates. When ETTFT correction is disabled, it preserves classification weights while still expanding deployments and checking availability.
    *   It reserves an available LogosNode lane or selects an available cloud deployment; otherwise it queues against the best eligible local candidate.
4.  **Execution**: `ContextResolver` resolves the selected deployment's endpoint and authentication context; the route passes that resolved URL, headers, and payload to `Executor`.
5.  **Release**: Upon completion, `scheduler.release()` is called to free capacity and check for queued requests.

### 2. Queued Path (Busy Models)

1.  **Scheduling**: If eligible local candidates are busy, cold, sleeping, or otherwise unavailable:
    *   The scheduler creates an `asyncio.Future`.
    *   It enqueues the future into `PriorityQueueManager` (HIGH/NORMAL/LOW).
    *   It `await`s the future, pausing the request execution.
2.  **Waiting**: The request remains suspended until a slot opens up. Queues use strict HIGH, then NORMAL, then LOW priority ordering; priorities are not automatically promoted.
3.  **Wake Up**: When another request finishes:
    *   `scheduler.release()` calls `queue_mgr.dequeue()`.
    *   It finds the highest priority waiting future.
    *   It calls `future.set_result()`, waking up the suspended request.
4.  **Resumption**: The `await` returns, and the request proceeds to **Execution**.

### 3. Direct-model path

When a request names a model, `main.py` first verifies access and limits deployments to that model. The pipeline then runs with `skip_laura=True`: it skips Laura's ML ranking, but still applies privacy policy, policy and token filtering, provider/deployment scheduling, context resolution, execution, and completion recording.

### 4. Execution readiness

`ContextResolver` creates the provider-specific URL, authentication headers, and execution context. Readiness retries are deliberately narrow: the pipeline retries an absent execution context only for a scheduled LogosNode provider while a lane is becoming available. Cloud providers do not inherit that local-lane retry behavior.

## Pipeline Components

### Core Files in `src/logos/pipeline/`

```
pipeline/
├── pipeline.py                 # Main RequestPipeline orchestrator
├── scheduler_interface.py      # Abstract scheduler interface & data models
├── base_scheduler.py           # Shared provider, capacity, and queue helpers
├── correcting_scheduler.py     # Production ETTFT-correcting scheduler
├── ettft_estimator.py          # Provider-specific readiness and wait estimates
├── executor.py                # Backend execution & API calling
└── context_resolver.py        # Database resolution for models/providers
```

### `pipeline.py` - RequestPipeline
**The main orchestrator.** Coordinates the full request lifecycle:
- Delegates to `ClassificationManager` to rank candidate models
- Calls scheduler to select best available model
- Invokes executor to perform the actual API call
- Records monitoring data to `log_entry`
- Handles errors and ensures proper resource cleanup

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
- Uses strict HIGH → NORMAL → LOW dequeue ordering for queued requests

### `correcting_scheduler.py` - ClassificationCorrectingScheduler
**Production scheduler.** By default, re-ranks only the classifier's eligible candidates using expected-time-to-first-token (ETTFT) penalties. `LOGOS_SCHEDULER_ETTFT_ENABLED=false` preserves classification weights/order while retaining deployment expansion and availability checks:
- Expands each classified model across all eligible deployments/providers
- Combines the classification weight with provider-specific readiness and wait estimates
- Never promotes a model that classification excluded
- Reserves available LogosNode capacity or accepts an available cloud deployment
- Queues on the best eligible local candidate when no candidate is immediately available
- Uses the shared strict-priority queues from `BaseScheduler`

### `executor.py` - Executor
**Backend execution engine.** Performs the actual API calls:
- Consumes the URL, headers, and payload already produced by `ContextResolver`
- Executes the upstream HTTP request
- Supports both streaming and non-streaming responses
- Extracts token usage for billing/logging
- Handles errors and timeouts gracefully

### `context_resolver.py` - ContextResolver
**Database resolution layer.** Fetches runtime configuration:
- Looks up model details (name, endpoint)
- Retrieves provider information (base URL, auth)
- Resolves API keys and authentication headers
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
- Strict HIGH → NORMAL → LOW dequeue ordering (no automatic promotion)

### Monitoring (`../monitoring/`)
- `MonitoringRecorder`: Logs request lifecycle events and performance metrics
- `prometheus_metrics`: Exposes pipeline and provider metrics

### Database (`../dbutils/`)
- `DBManager`: Database connection and query execution
- Schema: models, providers, log_entry
