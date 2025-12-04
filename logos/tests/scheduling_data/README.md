# Scheduling Data Interface (SDI) Integration Tests

Comprehensive integration tests for Queue + SDI + Scheduler focusing on scheduling data **correctness**, freshness and how it can be used in Scheduler.

For **performance testing** (workload simulation, statistics), see `tests/performance/`.

## Quick Start

### Basic Test Run (Skips Live Tests)

Run all SDI integration tests without live tests:

```bash
cd tests/scheduling_data
./test_scheduling_data.sh
```

All tests will run, but live integration tests will be skipped automatically.

### Running with Live SSH Tests

To run live Ollama SSH polling tests, provide SSH credentials:

```bash
./test_scheduling_data.sh \
  --ssh-host=hochbruegge.aet.cit.tum.de \
  --ssh-user=ge84ciq \
  --ssh-key-path=/root/.ssh/id_ed25519 \
  --ssh-remote-port=11434
```

If parameters are not provided, live SSH tests are skipped and the rest still run.

### Running with Live Model Tests

To run live inference tests from the database:

```bash
./test_scheduling_data.sh \
  --ollama-live-model-id=18 \
  --azure-live-model-id=12
```

### Running All Tests (Including Live)

Combine all parameters to run everything:

```bash
./test_scheduling_data.sh \
  --ssh-host=hochbruegge.aet.cit.tum.de \
  --ssh-user=ge84ciq \
  --ssh-key-path=/root/.ssh/id_ed25519 \
  --ollama-live-model-id=18 \
  --azure-live-model-id=12
```

### Direct pytest Invocation (Advanced)

You can also run pytest directly inside the container:

```bash
docker compose exec logos-server poetry run pytest tests/scheduling_data \
  --ssh-host=hochbruegge.aet.cit.tum.de \
  --ssh-user=ge84ciq \
  --ssh-key-path=/root/.ssh/id_ed25519 \
  -v
```

### Available Parameters

| Parameter | Description | Default | Required |
|-----------|-------------|---------|----------|
| `--ssh-host` | SSH hostname for live Ollama tests | None | For SSH tests |
| `--ssh-user` | SSH username | None | For SSH tests |
| `--ssh-key-path` | Path to SSH private key | None | For SSH tests |
| `--ssh-remote-port` | Remote Ollama port | 11434 | Optional |
| `--ollama-live-model-id` | Ollama model ID for live tests | None | For live Ollama tests |
| `--azure-model-id` | Azure model ID | 12 | Optional |
| `--azure-live-model-id` | Azure live model ID | None | For live Azure tests |

**Note**: SSH tests require ALL of: `--ssh-host`, `--ssh-user`, and `--ssh-key-path`. If any are missing, those tests will be skipped.

### Help

```bash
./test_scheduling_data.sh --help
```

Detailed SSH setup (VPN, key mounts, provider row config) is in `tests/scheduling_data/README_ollama_ssh.md`.
That guide also explains the real workflow: SSH-based `/api/ps` polling plus how to route live inference to a remote Ollama via tunnel or direct base_url.

## What Gets Tested

The integration test suite (multiple files under `tests/scheduling_data/`) provides comprehensive coverage of:

### 1. Mixed Workload Scenarios
- ✅ Load distribution across Azure + Ollama models
- ✅ Multi-provider task scheduling

### 2. Rate Limit Handling
- ✅ Failover to Ollama when Azure rate-limited
- ✅ Multi-provider resilience

### 3. Cold Start Scenarios
- ✅ Warm vs cold model preference
- ✅ VRAM constraint tracking (40GB models, etc.)
- ✅ Multiple models loaded simultaneously

### 4. High Traffic Scenarios
- ✅ Queue buildup under load (20+ tasks)
- ✅ Limited capacity scheduling
- ✅ Load balancing across models

### 5. SDI Integration
- ✅ Queue state reporting per priority level
- ✅ Azure models: no queue visibility (cloud provider)
- ✅ Ollama models: full queue visibility (local)

### 6. **SDI Data Usage** - **CRITICAL**
- ✅ Azure rate limits block scheduling via SDI
- ✅ Rate limit recovery enables scheduling
- ✅ Ollama loaded model status tracked
- ✅ VRAM capacity tracked accurately
- ✅ Work table derived from SDI queries
- ✅ Azure request/response updates rate limits (model 12, mocked request with decrement)
  (use `--azure-model-id` parameter to test a different Azure model; defaults to 12)

### 7. **Request Lifecycle Tests** - **CRITICAL**
- ✅ Sequential execution with queue draining
- ✅ Parallel execution with capacity limits
- ✅ Mixed priority ordering during execution
- ✅ Multi-provider concurrent execution
- ✅ Complete queue drain with SDI verification at every step

### 8. Ollama SSH Polling (optional live)
- ✅ Mocked SSH path (unit)
- ✅ Optional live SSH + `/api/ps` when SSH parameters are provided
- ✅ Optional DB-driven live inference + SSH poll when `--ollama-live-model-id` is provided (uses DB provider/model config)
  (test will skip if the DB-configured base_url is not reachable)

## Test Architecture

Tests use **REAL implementations** with mocked HTTP layer:

```
Task → SimplePriorityScheduler (REAL)
         ↓
     PriorityQueueManager (REAL queue operations)
         ↓
     OllamaSchedulingDataFacade / AzureSchedulingDataFacade (REAL)
         ↓
     OllamaDataProvider / AzureDataProvider (REAL)
         ↓
     [MOCKED: HTTP responses only]
```

All business logic is tested with real code, only network calls are mocked.

## Key Test Classes

- **TestMixedWorkload** - Multi-provider load distribution (1 test)
- **TestRateLimitHandling** - Azure failover scenarios (1 test)
- **TestColdStartScenarios** - Ollama VRAM and model loading (3 tests)
- **TestHighTrafficBurst** - Queue buildup under load (3 tests)
- **TestSDIIntegration** - SDI queue visibility and reporting (3 tests)
- **TestSDIDataUsage** - Verifies scheduler uses SDI data (5 tests) ← CRITICAL
- **TestRequestLifecycleSequential** - One-by-one execution with queue draining
- **TestRequestLifecycleParallel** - Concurrent execution with capacity limits
- **TestRequestLifecycleMixedPriority** - Priority ordering verification
- **TestRequestLifecycleMultiProvider** - Azure + Ollama concurrent execution
- **TestRequestLifecycleQueueDrainComplete** - Full drain with step-by-step SDI verification

## What Makes These Tests Critical

### SDI Data Usage Tests (5 tests)
These verify the scheduler **actually uses** SDI data for decision-making:
- ✅ Rate limits from SDI block/enable scheduling
- ✅ Loaded model status from SDI determines schedulability
- ✅ VRAM capacity from SDI tracked accurately
- ✅ Work table built from SDI queries (not hardcoded)

Without these tests, SDI could exist but be ignored by the scheduler.

### Request Lifecycle Tests (5 tests)
These verify the **complete request execution flow**:
1. ✅ Enqueue → Queue depth increases, SDI reports it
2. ✅ Schedule/dequeue → Queue depth decreases
3. ✅ Begin processing → Active requests increments
4. ✅ Complete → Active requests decrements, capacity freed
5. ✅ Next task schedules → Queue continues progressing
6. ✅ SDI accurate at **every single step**

This ensures the entire system works correctly under real workload conditions.
