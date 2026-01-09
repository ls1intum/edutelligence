# Request Pipeline

## Overview

The Request Pipeline orchestrates the lifecycle of a request from entry to execution. It decouples the three main stages of request handling:

1.  **Classification**: Analyzing the request to determine candidate models.
2.  **Scheduling**: Selecting the best available model based on utilization, priority, and policy.
3.  **Execution**: Resolving backend details and performing the actual API call.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           HTTP Layer                                     │
│                    /v1/{path}, /openai/{path}                           │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      RequestPipeline                                     │
│  Orchestrates: classify → schedule → execute → respond                  │
└─────────────────────────────────────────────────────────────────────────┘
                    │              │              │
          ┌────────┘              │              └────────┐
          ▼                       ▼                       ▼
┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│  Classification  │   │    Scheduler     │   │    Executor      │
│    Manager       │   │   (Interface)    │   │                  │
│                  │   │                  │   │  - DB resolution │
│ - Policy eval    │   │ - SDI queries    │   │  - API key lookup│
│ - Model ranking  │   │ - Queue updates  │   │  - Backend calls │
│ - Weight calc    │   │ - Model selection│   │  - Response      │
└──────────────────┘   └────────┬─────────┘   └──────────────────┘
                                │
                    ┌───────────┴───────────┐
                    ▼                       ▼
          ┌──────────────────┐   ┌──────────────────┐
          │ OllamaSDIFacade  │   │ AzureSDIFacade   │
          │                  │   │                  │
          │ - /api/ps polls  │   │ - Rate limits    │
          │ - VRAM tracking  │   │ - Per-deployment │
          │ - Queue state    │   │   tracking       │
          └────────┬─────────┘   └──────────────────┘
                   │
                   ▼
          ┌──────────────────┐
          │PriorityQueueMgr  │
          │                  │
          │ - LOW/NORMAL/HIGH│
          │ - Per-model      │
          └──────────────────┘
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

## Components

### `RequestPipeline` (`pipeline.py`)
The main entry point. It coordinates the flow and ensures that monitoring data is recorded.

### `UtilizationAwareScheduler` (`utilization_scheduler.py`)
The brain of the operation.
*   **Availability Awareness**: Uses SDI to avoid sending requests to overloaded or rate-limited models.
*   **Async Queuing**: Handles backpressure by queuing requests when necessary.
*   **Priority Management**: Respects request priority and prevents starvation.

### `Executor` (`executor.py`)
The muscle.
*   **Context Resolution**: Fetches all necessary details (URL, keys) from the database.
*   **Execution**: Performs the actual HTTP request (supporting both streaming and synchronous modes).
*   **Usage Extraction**: Parses response bodies to extract token usage for billing/logging.
