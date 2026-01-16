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
║  │ • Model lookup   │   │scheduler_interface.py │   │ • Provider        │ ║
║  │ • Provider info  │   │  SchedulerInterface   │   │   resolution      │ ║
║  │ • API keys       │   │         │             │   │ • Endpoint        │ ║
║  │ • Backend calls  │   │         ▼             │   │   lookup          │ ║
║  │ • Streaming      │   │  base_scheduler.py    │   │                   │ ║
║  │ • Error handling │   │    BaseScheduler      │   │                   │ ║
║  │                  │   │    ┌────┴────┐        │   │                   │ ║
║  │                  │   │    ▼         ▼        │   │                   │ ║
║  │                  │   │ fcfs_      utilization│   │                   │ ║
║  │                  │   │ scheduler  _scheduler │   │                   │ ║
║  │                  │   │   .py        .py      │   │                   │ ║
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
    │ PolicyClassifier │   │ OllamaSDIFacade  │   │ • NORMAL         │
    │ TokenClassifier  │   │  - /api/ps polls │   │ • HIGH           │
    │ AIClassifier     │   │  - VRAM tracking │   │ • Per-model      │
    │ LauraEmbedding   │   │ AzureSDIFacade   │   │   queues         │
    │                  │   │  - Rate limits   │   │ • Anti-          │
    │Ranks & weights   │   │  - Quotas        │   │   starvation     │
    └──────────────────┘   └──────────────────┘   └──────────────────┘
                                     │
                                     ▼
                        ┌──────────────────────────┐
                        │  Database (PostgreSQL)   │
                        │  - models, providers     │
                        │  - log_entry, jobs       │
                        │  - request_events        │
                        └──────────────────────────┘
```

## Request Flow

### 1. Happy Path (Immediate Execution)

1.  **Request Arrives**: `main.py` receives the request and delegates to `RequestPipeline.process()`.
2.  **Classification**: `ClassificationManager` ranks models based on policy and weights.
3.  **Scheduling**: `UtilizationAwareScheduler` checks SDI for the top candidate.
    *   If available, it reserves the slot (conceptually) and returns immediate success.
4.  **Execution**: `Executor` resolves the model's endpoint and API key from the DB and sends the request.
5.  **Release**: Upon completion, `scheduler.release()` is called to free capacity and check for queued requests.

### 2. Queued Path (Busy Models)

1.  **Scheduling**: If all candidate models are busy (rate-limited or full capacity):
    *   The scheduler creates an `asyncio.Future`.
    *   It enqueues the future into `PriorityQueueManager` (HIGH/NORMAL/LOW).
    *   It `await`s the future, pausing the request execution.
2.  **Waiting**: The request remains suspended until a slot opens up.
    *   **Starvation Prevention**: Requests waiting too long (>10s for LOW, >30s for NORMAL) are automatically promoted to higher priority.
3.  **Wake Up**: When another request finishes:
    *   `scheduler.release()` calls `queue_mgr.dequeue()`.
    *   It finds the highest priority waiting future.
    *   It calls `future.set_result()`, waking up the suspended request.
4.  **Resumption**: The `await` returns, and the request proceeds to **Execution**.

## Pipeline Components

### Core Files in `src/logos/pipeline/`

```
pipeline/
├── pipeline.py                 # Main RequestPipeline orchestrator
├── scheduler_interface.py      # Abstract scheduler interface & data models
├── base_scheduler.py          # Base scheduler with shared SDI/queue logic
├── fcfs_scheduler.py          # First-Come-First-Served scheduler
├── utilization_scheduler.py   # Utilization-aware scheduler (primary)
├── executor.py                # Backend execution & API calling
└── context_resolver.py        # Database resolution for models/providers
```

### `pipeline.py` - RequestPipeline
**The main orchestrator.** Coordinates the full request lifecycle:
- Delegates to `ClassificationManager` to rank candidate models
- Calls scheduler to select best available model
- Invokes executor to perform the actual API call
- Records monitoring data to database (log_entry, request_events)
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
- Manages SDI facades (`OllamaSchedulingDataFacade`, `AzureSchedulingDataFacade`)
- Tracks per-model provider types (ollama/azure)
- Provides helper methods for queue management and metrics collection
- Anti-starvation logic for queued requests

### `fcfs_scheduler.py` - FcfsScheduler
**Simple FCFS implementation.** Selects first available model without utilization awareness:
- Iterates through candidates in weight order
- No queue management (blocks if no model available)
- Useful for testing and baseline benchmarks

### `utilization_scheduler.py` - UtilizationAwareScheduler
**Production scheduler.** The brain of the operation:
- **Availability Awareness**: Queries SDI to check VRAM, rate limits, and capacity
- **Intelligent Selection**: Avoids overloaded models, respects parallel capacity
- **Async Queuing**: Enqueues requests when all models busy, resumes when capacity frees
- **Priority Management**: HIGH/NORMAL/LOW priority queues with anti-starvation
- **Cold Start Detection**: Tracks model loading state to predict latency

### `executor.py` - Executor
**Backend execution engine.** Performs the actual API calls:
- Resolves model/provider details via `ContextResolver`
- Fetches API keys and endpoints from database
- Executes HTTP requests with proper headers and auth
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
- `OllamaSchedulingDataFacade`: Real-time VRAM and model loading state
- `AzureSchedulingDataFacade`: Rate limits and quota tracking
- Provides availability data for intelligent scheduling decisions

### Priority Queue (`../queue/`)
- `PriorityQueueManager`: Per-model priority queues
- `Priority` enum: LOW, NORMAL, HIGH
- Anti-starvation promotion logic

### Monitoring (`../monitoring/`)
- `OllamaMonitor`: Continuous Ollama provider polling
- `Recorder`: Logs request events and performance metrics to database

### Database (`../dbutils/`)
- `DBManager`: Database connection and query execution
- Schema: models, providers, log_entry, request_events, model_provider_config
