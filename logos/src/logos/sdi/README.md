# Scheduling Data Interface (SDI)

## Overview

SDI provides a **pure data interface** for accessing real-time scheduling information from heterogeneous providers. It does NOT implement scheduling algorithms - it provides data that schedulers use to make decisions.

**Key Features:**
- Queries Ollama `/api/ps` for VRAM usage, loaded models, expiration times
- Tracks Azure rate limits from response headers (per-deployment)
- Accurate cold-start prediction using real data
- Multi-provider routing
- Request lifecycle tracking with metrics

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Your Scheduler                                     │
│  (queries SDI facades, makes decisions)             │
└──────────────────┬──────────────────────────────────┘
                   │
       ┌───────────┴────────────┐
       ▼                        ▼
┌──────────────┐          ┌─────────────┐
│   Ollama     │          │   Azure     │
│   Facade     │          │   Facade    │
│              │          │             │
└──────┬───────┘          └──────┬──────┘
       │                         │
       │ manages N providers     │ manages N providers
       ▼                         ▼
┌──────────────┐          ┌─────────────┐
│   Ollama     │          │   Azure     │
│   Provider   │          │   Provider  │
└──────┬───────┘          └──────┬──────┘
       │                         │
       ▼                         ▼
   /api/ps              rate limit headers
```

**Components:**

*Facades (Type-Safe APIs):*
- **OllamaSchedulingDataFacade**: Manages multiple Ollama servers, returns dataclasses
- **AzureSchedulingDataFacade**: Manages Azure deployments with per-deployment rate limits

*Provider Implementations:*
- **OllamaDataProvider**: Polls /api/ps for VRAM and model status
- **AzureDataProvider**: Tracks per-deployment rate limits from API headers

*Data Models:*
- **ModelStatus**: Common model status (used by both provider types)
- **OllamaCapacity**: VRAM capacity info
- **AzureCapacity**: Per-deployment rate limit info
- **RequestMetrics**: Request lifecycle metrics

## Quick Start

### Option 1: Ollama Facade (Multiple Servers)

```python
from logos.queue import PriorityQueueManager
from logos.sdi import OllamaSchedulingDataFacade

# Initialize queue manager and facade
queue_mgr = PriorityQueueManager()
facade = OllamaSchedulingDataFacade(queue_mgr, db_manager)

# Register models from multiple Ollama servers
facade.register_model(
    model_id=1,
    provider_name='gpu-1',
    ollama_admin_url='http://gpu-1.internal:11434',
    model_name='llama3.3:latest',
    total_vram_mb=49152  # 48GB
)

facade.register_model(
    model_id=2,
    provider_name='gpu-2',
    ollama_admin_url='http://gpu-2.internal:11434',
    model_name='llama3.1:8b',
    total_vram_mb=49152
)

# Query model status (returns ModelStatus dataclass)
status = facade.get_model_status(1)
if status.is_loaded and status.queue_depth < 3:
    # Good candidate: warm and not overloaded
    schedule_to_model(1)

# Get capacity info (returns OllamaCapacity dataclass)
capacity = facade.get_capacity_info('gpu-1')
if capacity.available_vram_mb > 4096:
    # Enough VRAM to load new model
    load_model('new-model')

# Track request lifecycle (3 stages)
facade.on_request_start('req-123', model_id=1, priority='high')
# ... request queued ...
facade.on_request_begin_processing('req-123')
# ... request processing ...
metrics = facade.on_request_complete('req-123', was_cold_start=False, duration_ms=180)
```

### Option 2: Azure Facade (Per-Deployment Rate Limits)

```python
from logos.sdi import AzureSchedulingDataFacade

# Initialize facade
facade = AzureSchedulingDataFacade(db_manager)

# Register Azure models (deployment name extracted from endpoint)
facade.register_model(
    model_id=10,
    provider_name='azure',
    model_name='gpt-4',
    model_endpoint='https://my-resource.openai.azure.com/openai/deployments/gpt-4o/chat/completions'
)

# Query model status (returns ModelStatus dataclass)
status = facade.get_model_status(10)
if status.queue_depth < 10:
    # Not overloaded
    schedule_to_model(10)

# Get rate limit info (returns AzureCapacity dataclass)
capacity = facade.get_capacity_info('azure', 'gpt-4o')
if capacity.has_capacity and capacity.rate_limit_remaining_requests > 10:
    # Send request
    make_api_call()

# Update rate limits after API call
facade.update_rate_limits('azure', 'gpt-4o', response.headers)

# Note: Azure facades do not support request lifecycle tracking
# (on_request_start, on_request_begin_processing, on_request_complete)
# Cloud providers manage queues internally - no visibility into queue state
```

## Key Methods

**OllamaSchedulingDataFacade API:**
- `register_model(model_id, provider_name, ollama_admin_url, model_name, total_vram_mb)` - Register Ollama model
- `get_model_status(model_id)` → `ModelStatus` - Get current status (returns dataclass)
- `get_capacity_info(provider_name)` → `OllamaCapacity` - Get VRAM availability (returns dataclass)
- `get_scheduling_data(model_ids)` → `List[ModelStatus]` - Batch query multiple models
- `on_request_start(request_id: str, model_id: int, priority: str = 'normal')` - Track request arrival (→ queue)
- `on_request_begin_processing(request_id: str)` - Track processing start (queue → active)
- `on_request_complete(request_id: str, was_cold_start: bool, duration_ms: int)` → `RequestMetrics` - Track completion

**AzureSchedulingDataFacade API:**
- `register_model(model_id, provider_name, model_name, model_endpoint)` - Register Azure model
- `get_model_status(model_id)` → `ModelStatus` - Get current status (returns dataclass)
- `get_capacity_info(provider_name, deployment_name)` → `AzureCapacity` - Get rate limits (returns dataclass)
- `get_scheduling_data(model_ids)` → `List[ModelStatus]` - Batch query multiple models
- `update_rate_limits(provider_name, deployment_name, response_headers)` - Update rate limits from API response

**Note:** Azure facade does not support request lifecycle tracking (cloud providers manage queues internally)

**Note:** SDI provides raw data only. Schedulers derive predictions (e.g., cold starts) from this data.

## Request Lifecycle

SDI tracks requests through three stages:

```
┌─────────────┐  on_request_start()           ┌──────────────┐
│   Request   │ ────────────────────────────> │     Queue    │
│   Arrives   │                               │  (waiting)   │
└─────────────┘                               └──────┬───────┘
                                                     │
                                                     │ on_request_begin_processing()
                                                     ▼
                                              ┌──────────────┐
                                              │    Active    │
                                              │ (processing) │
                                              └──────┬───────┘
                                                     │
                                                     │ on_request_complete()
                                                     ▼
                                              ┌──────────────┐
                                              │   Complete   │
                                              └──────────────┘
```

**Fields in ModelStatus:**
- `queue_depth`: Requests waiting in queue (not yet processing)
- `active_requests`: Requests currently being processed
- `total_load = queue_depth + active_requests`

**Example:**
```python
# Request arrives
facade.on_request_start('req-123', model_id=1, priority='high')
# status.queue_depth = 1, status.active_requests = 0

# Processing starts
facade.on_request_begin_processing('req-123')
# status.queue_depth = 0, status.active_requests = 1

# Request finishes
metrics = facade.on_request_complete('req-123', was_cold_start=False, duration_ms=250)
# status.queue_depth = 0, status.active_requests = 0
```

## Data Sources

### Ollama: /api/ps Endpoint

Polls every 5 seconds to get ground truth:

```bash
curl http://gpu-vm-1:11434/api/ps | jq
```

**Response:**
```json
{
  "models": [
    {
      "name": "llama3.3:latest",
      "size_vram": 8589934592,
      "expires_at": "2025-01-11T15:35:00Z"
    }
  ]
}
```

**Provided Data:**
- `is_loaded`: Model in response and not expired
- `expires_at`: When model will be unloaded from VRAM
- `available_vram_mb`: `total_vram_mb - sum(size_vram) / 1024²`


### Azure: Rate Limit Headers

Updates after each API call:

```python
response = requests.post(azure_url, ...)
facade.update_rate_limits('azure', 'gpt-4o', response.headers)
```

**Parsed headers:**
- `x-ratelimit-remaining-requests`
- `x-ratelimit-remaining-tokens`
- `x-ratelimit-reset-requests`

## Database Schema

### providers table (SDI fields)

```sql
CREATE TABLE providers (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    provider_type VARCHAR(20) DEFAULT 'cloud',

    -- SDI: Ollama monitoring
    ollama_admin_url TEXT DEFAULT '', -- used for /api/ps calls
    total_vram_mb INTEGER DEFAULT NULL,

    -- SDI: Configuration
    parallel_capacity INTEGER DEFAULT 1,
    keep_alive_seconds INTEGER DEFAULT 300,
    max_loaded_models INTEGER DEFAULT 3,

    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
```

### model_provider_config table

Per-model overrides for cold start thresholds and observed statistics:

```sql
CREATE TABLE model_provider_config (
    model_id INTEGER NOT NULL,
    provider_name VARCHAR(50) NOT NULL,
    cold_start_threshold_ms REAL DEFAULT 1000.0,
    parallel_capacity INTEGER DEFAULT NULL,
    keep_alive_seconds INTEGER DEFAULT NULL,
    observed_avg_cold_load_ms REAL DEFAULT NULL,
    observed_avg_warm_load_ms REAL DEFAULT NULL,
    PRIMARY KEY (model_id, provider_name)
);
```

**Configuration Hierarchy:**
1. `model_provider_config` (per-model overrides)
2. `providers` table (provider defaults)
3. Hardcoded defaults in `OllamaDataProvider`

## Two-URL Architecture

**Important distinction for Ollama:**

1. **base_url** (execution): Where to send user requests
   - Example: `https://gpu.aet.cit.tum.de/` (OpenWebUI proxy)
   - Used by main application for forwarding

2. **ollama_admin_url** (monitoring): Where to query /api/ps
   - Example: `http://gpu-vm-1.internal:11434` (direct Ollama)
   - Used by SDI for monitoring only

Cloud providers only need `base_url` (no monitoring URL).

## Queue Integration

### Overview

SDI provides priority-aware queue state tracking. The `ModelStatus` dataclass includes queue depth breakdown by priority level, enabling schedulers to make more informed decisions.

### Queue State Per Priority

The `queue_state` field provides detailed queue information:

```python
from logos.sdi import OllamaSchedulingDataFacade

facade = OllamaSchedulingDataFacade(...)
status = facade.get_model_status(1)

# Access queue state
print(f"LOW priority:    {status.queue_state.low}")
print(f"NORMAL priority: {status.queue_state.normal}")
print(f"HIGH priority:   {status.queue_state.high}")
print(f"Total:           {status.queue_state.total}")

# Convenience property: queue_depth (sum of all priorities)
print(f"Total depth: {status.queue_depth}")  # Same as queue_state.total
```

### ModelStatus

```python
@dataclass
class ModelStatus:
    model_id: int
    is_loaded: bool
    vram_mb: int
    expires_at: datetime | None
    queue_state: QueueStatePerPriority  # Detailed breakdown
    active_requests: int
    provider_type: str

    @property
    def queue_depth(self) -> int:
        """Convenience property: returns sum of all priority levels"""
        return self.queue_state.total
```

### QueueStatePerPriority

```python
@dataclass
class QueueStatePerPriority:
    low: int = 0
    normal: int = 0
    high: int = 0

    @property
    def total(self) -> int:
        return self.low + self.normal + self.high
```

### Integration with Priority Queue Manager

OllamaSchedulingDataFacade requires a PriorityQueueManager for accurate queue state tracking:

```python
from logos.queue import PriorityQueueManager
from logos.sdi import OllamaSchedulingDataFacade

# Create queue manager
queue_mgr = PriorityQueueManager()

# Initialize facade with queue manager (REQUIRED for Ollama)
facade = OllamaSchedulingDataFacade(queue_mgr, db_manager)

# Queue state accurately reflects 3 priority levels (LOW/NORMAL/HIGH)
# from the queue manager
```

### Scheduling with Queue State

Schedulers can use detailed queue state for better decisions:

```python
# Query multiple models
models = [1, 2, 3]
statuses = [facade.get_model_status(mid) for mid in models]

# Score based on priority queue state
def score_model(status):
    score = 0
    
    # Prefer models with less HIGH priority load
    score -= status.queue_state.high * 10
    
    # Penalize NORMAL priority load
    score -= status.queue_state.normal * 5
    
    # Slightly penalize LOW priority load
    score -= status.queue_state.low * 1
    
    # Prefer warm models (no cold start)
    if not status.is_loaded:
        score -= 50
    
    # Prefer less active requests
    score -= status.active_requests * 3
    
    return score

# Select best model
best_model = max(statuses, key=score_model)
print(f"Selected model {best_model.model_id}")
```

### Related Documentation

- Priority Queue Subsystem: `src/logos/queue/README.md`
- Pipeline Schedulers: `src/logos/pipeline/README.md` (includes utilization_scheduler.py, fcfs_scheduler.py)
- Integration Tests: `tests/scheduling_data/` (comprehensive Queue + SDI + Scheduler tests)
