# Scheduling Data Interface (SDI) Integration Tests

Comprehensive integration tests for Queue + SDI + Scheduler focusing on scheduling data **correctness**, freshness and how it can be used in Scheduler.

For **performance testing** (workload simulation, statistics), see `tests/performance/`.

## Quick Start

Run all SDI integration tests:

```bash
./tests/scheduling_data/test_scheduling_data.sh
```

## What Gets Tested

The integration test suite (`test_scheduling_data.py`) provides comprehensive coverage of:

### 1. Mixed Workload Scenarios (1 test)
- ✅ Load distribution across Azure + Ollama models
- ✅ Multi-provider task scheduling

### 2. Rate Limit Handling (1 test)
- ✅ Failover to Ollama when Azure rate-limited
- ✅ Multi-provider resilience

### 3. Cold Start Scenarios (3 tests)
- ✅ Warm vs cold model preference
- ✅ VRAM constraint tracking (40GB models, etc.)
- ✅ Multiple models loaded simultaneously

### 4. High Traffic Scenarios (3 tests)
- ✅ Queue buildup under load (20+ tasks)
- ✅ Limited capacity scheduling
- ✅ Load balancing across models

### 5. SDI Integration (3 tests)
- ✅ Queue state reporting per priority level
- ✅ Azure models: no queue visibility (cloud provider)
- ✅ Ollama models: full queue visibility (local)

### 6. **SDI Data Usage** (5 tests) - **CRITICAL**
- ✅ Azure rate limits block scheduling via SDI
- ✅ Rate limit recovery enables scheduling
- ✅ Ollama loaded model status tracked
- ✅ VRAM capacity tracked accurately
- ✅ Work table derived from SDI queries

### 7. **Request Lifecycle Tests** (5 tests) - **CRITICAL**
- ✅ Sequential execution with queue draining
- ✅ Parallel execution with capacity limits
- ✅ Mixed priority ordering during execution
- ✅ Multi-provider concurrent execution
- ✅ Complete queue drain with SDI verification at every step

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
