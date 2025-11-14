# Scheduling Data Interface (SDI)

**Version 1.0** - Facade pattern with /api/ps integration for Ollama

## Overview

SDI provides a **pure data interface** for accessing real-time scheduling information from heterogeneous providers. It does NOT implement scheduling algorithms - it provides data that schedulers use to make decisions.

**Key Features:**
- Queries Ollama `/api/ps` for VRAM usage, loaded models, expiration times
- Tracks Azure rate limits from response headers
- Accurate cold-start prediction using real data
- Thread-safe, unified API for all provider types

## Architecture

```
┌─────────────────────────────────────────┐
│  Your Scheduler                         │
│  (queries SDI, makes decisions)         │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│  SchedulingDataFacade                   │
│  (unified API, routes to providers)     │
└────────────────┬────────────────────────┘
                 │
                 ├──────────────┬
                 ▼              ▼
        ┌────────────┐  ┌────────┐
        │  Ollama    │  │ Azure  │
        │ Provider   │  │Provider│
        └────────────┘  └────────┘
             │              │
             ▼              ▼
        /api/ps      rate limits
```

**Components:**
- **SchedulingDataFacade**: Unified entry point for schedulers
- **SchedulingDataProvider**: Abstract base class (interface)
- **OllamaDataProvider**: Polls /api/ps for VRAM and model status
- **AzureDataProvider**: Tracks rate limits from API headers
- **CloudDataProvider**: Base class for cloud providers

## Quick Start

```python
from logos.sdi import SchedulingDataFacade

# Initialize
sdi = SchedulingDataFacade(db_manager)

# Register Ollama model
sdi.register_model(
    model_id=1,
    provider_name='openwebui',
    provider_type='ollama',
    model_name='llama3.3:latest',
    ollama_admin_url='http://gpu-vm-1.internal:11434',
    total_vram_mb=49152  # 48GB
)

# Register Azure model
sdi.register_model(
    model_id=10,
    provider_name='azure',
    provider_type='cloud',
    model_name='azure-gpt-4-omni'
)

# Query model status for scheduling
status = sdi.get_model_status(1)
if not status['cold_start_predicted'] and status['queue_depth'] < 3:
    # Good candidate: warm and not overloaded
    schedule_to_model(1)

# Track request lifecycle
sdi.on_request_start('req-123', model_id=1, priority='high')
# ... process request ...
metrics = sdi.on_request_complete('req-123', was_cold_start=False, duration_ms=250)
```

## Key Methods

**SchedulingDataFacade API:**
- `register_model()` - Register a model with provider
- `get_model_status(model_id)` - Get current status (loaded, queue depth, cold start prediction)
- `get_provider_capacity(provider_name)` - Get VRAM availability or rate limits
- `get_scheduling_data(model_ids)` - Batch query multiple models
- `on_request_start()` - Track request arrival
- `on_request_complete()` - Track completion and return metrics
- `update_cloud_rate_limits()` - Update Azure rate limits from response headers

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

**Calculations:**
- `is_loaded`: Model in response and not expired
- `cold_start_predicted`: Model expired or not in VRAM
- `available_vram_mb`: `total_vram_mb - sum(size_vram) / 1024²`

### Azure: Rate Limit Headers

Updates after each API call:

```python
response = requests.post(azure_url, ...)
sdi.update_cloud_rate_limits('azure', response.headers)
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

## Testing

### Manual Testing with /api/ps

```bash
# Check current state
curl http://gpu-vm-1:11434/api/ps | jq

# Load a model
curl -X POST http://gpu-vm-1:11434/api/generate \
  -d '{"model": "llama3.3:latest", "prompt": "test", "keep_alive": "5m"}'

# Verify it's loaded
curl http://gpu-vm-1:11434/api/ps | jq
```

### Integration Testing

```python
from logos.sdi import SchedulingDataFacade

# Setup
sdi = SchedulingDataFacade(db_manager)
sdi.register_model(
    model_id=1,
    provider_name='openwebui',
    provider_type='ollama',
    model_name='llama3.3:latest',
    ollama_admin_url='http://gpu-vm-1:11434',
    total_vram_mb=49152
)

# Test cold start prediction
status = sdi.get_model_status(1)
assert status['cold_start_predicted'] == True  # Not loaded yet

# Load model, then re-check
# ... (send request to load model) ...
status = sdi.get_model_status(1)
assert status['cold_start_predicted'] == False  # Now warm
assert status['is_loaded'] == True
assert status['vram_mb'] > 0
```

## Two-URL Architecture

**Important distinction for Ollama:**

1. **base_url** (execution): Where to send user requests
   - Example: `https://gpu.aet.cit.tum.de/` (OpenWebUI proxy)
   - Used by main application for forwarding

2. **ollama_admin_url** (monitoring): Where to query /api/ps
   - Example: `http://gpu-vm-1.internal:11434` (direct Ollama)
   - Used by SDI for monitoring only

Cloud providers only need `base_url` (no monitoring URL).
