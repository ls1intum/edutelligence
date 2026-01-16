# Scheduling Performance Tests

Comprehensive performance benchmarking for Logos scheduling system using **real API workload replay**.

For **correctness testing** (SDI integration, queue state, priority ordering), see `tests/scheduling_data/`.

## Quick Start

Run all performance tests (requires Logos API key):

```bash
./tests/performance/test_scheduling_performance.sh --logos-key "your-api-key-here"
```

**Note:** The `--logos-key` argument is **required**. Get your API key from the Logos dashboard.

## What Gets Tested

The performance test suite replays workload CSVs against a live Logos API and measures:

### Core Metrics
- **TTFT (Time To First Token):** Latency from request to first streamed token
- **TPOT (Time Per Output Token):** Average time between tokens
- **Total Latency:** End-to-end request duration
- **Client Duration:** Wall-clock time as perceived by client
- **Throughput:** Requests processed per second

### Analysis
- **Latency Percentiles:** p50, p95, p99 across all requests
- **SLA Compliance:** Percentage of requests meeting latency SLO
- **Per-Model Performance:** Breakdown by provider and model
- **Priority Impact:** How priority affects scheduling latency
- **Mode Impact:** Interactive vs batch request performance

## Test Architecture

### Components

1. **Workload CSVs** (`workloads/`)
   - Standardized request traces with timing information
   - Configurable mode (interactive/batch) and priority (low/mid/high)
   - Direct model selection or classification mode
   - See `workloads/README.md` for CSV format

2. **API Workload Runner** (`run_api_workload.py`)
   - Async HTTP client for concurrent API requests
   - Reads workloads and replays with correct timing
   - Queries database for detailed log entries (TTFT, TPOT, etc.)
   - Generates CSV reports and latency visualizations

3. **Results Storage** (`results/`)
   - `*_benchmark_summary.csv` - Aggregated metrics per request
   - `*_benchmark_detailed.csv` - Full per-request breakdown with DB logs
   - `*.png` - Latency distribution charts

### Workload Types

| Workload | Description | Use Case |
|----------|-------------|----------|
| `sample_workload_direct.csv` | Direct model selection only | Benchmark pure scheduling (no classification) |
| `sample_workload_classify.csv` | Classification mode only | Benchmark classification + scheduling |
| `sample_workload_mixed.csv` | Mix of both modes | Realistic production workload |

## Running Tests

### Docker (Recommended)

**Minimum required (uses default workload):**
```bash
./tests/performance/test_scheduling_performance.sh --logos-key "your-api-key"
```

**Custom workload:**
```bash
./tests/performance/test_scheduling_performance.sh \
    --logos-key "your-api-key" \
    --workload tests/performance/workloads/sample_workload_direct.csv
```

**Full customization:**
```bash
./tests/performance/test_scheduling_performance.sh \
    --logos-key "your-api-key" \
    --workload tests/performance/workloads/sample_workload_classify.csv \
    --latency-slo-ms 5000 \
    --output tests/performance/results/my_custom_benchmark.csv
```

This will:
1. Start Docker containers
2. Wait for Logos API to be ready
3. Run workload replay with specified parameters
4. Generate results in `tests/performance/results/` (persisted to local repo via volume mount)

### Shell Script Arguments

```
--logos-key <KEY>            Logos API key (REQUIRED)
--workload <CSV>             Path to workload CSV (default: sample_workload_mixed.csv)
--api-base <URL>             Logos API base URL (default: http://localhost:8080)
--output <PATH>              Output CSV path (default: auto-generated with timestamp)
--latency-slo-ms <MS>        Latency SLO in milliseconds (default: 10000)
```

### Direct Python Execution (Advanced)

If you need more control or want to run outside the shell script:

```bash
docker compose exec logos-server poetry run python tests/performance/run_api_workload.py \
    --logos-key "your-api-key" \
    --workload tests/performance/workloads/sample_workload_direct.csv \
    --output tests/performance/results/my_benchmark.csv \
    --latency-slo-ms 5000
```

## Output Files

After running, check `tests/performance/results/`:

### Summary CSV
- One row per request with aggregated metrics
- Columns: request_id, status_code, client_duration_ms, ttft_ms, total_latency_ms, etc.

### Detailed CSV
- Full request details + database log entries
- Includes: provider, model, queue times, TPOT, token counts

### Latency Charts
- `*_benchmark.png` - Overall latency distribution
- `*_benchmark_client_duration.png` - Client-perceived latency over time

## Metrics Definitions

| Metric | Definition | Source |
|--------|------------|--------|
| **Client Duration** | Wall-clock time from request to response (ms) | HTTP client |
| **TTFT** | Time from request to first token (ms) | Database log |
| **Total Latency** | Time from request to final token (ms) | Database log |
| **TPOT** | Average time per output token (ms) | Database log |
| **Queue Time** | Time spent waiting in scheduler queue (ms) | Database log |

## Best Practices

1. **Use Docker for consistency** - `test_scheduling_performance.sh` ensures clean environment
2. **Test with realistic workloads** - Mix of priorities, modes, and models
3. **Check SLA compliance** - Set `--latency-slo-ms` to your target
4. **Analyze per-model** - Identify bottlenecks by provider/model
5. **Compare before/after** - Baseline results before scheduler changes

## Troubleshooting

### Test fails with "Connection refused"
- Ensure Logos API is running: `docker compose ps logos-server`
- Check API health: `curl http://localhost:8080/health`

### Test fails with "--logos-key is required"
- The `--logos-key` argument is mandatory when using the shell script
- Pass it directly: `./test_scheduling_performance.sh --logos-key "your-key"`
- Get your API key from the Logos dashboard

### Results files not appearing in local repo
- Verify the docker-compose.yaml volume mount exists:
  ```yaml
  - ./tests/performance/results:/app/logos/tests/performance/results
  ```
- Restart containers after changing volume mounts: `docker compose down && docker compose up -d`

### Missing database metrics (TTFT, TPOT)
- Verify database logging is enabled in Logos config
- Check log entries exist: `SELECT * FROM log WHERE request_id = '...'`

### Workload CSV errors
- Validate CSV format: see `workloads/README.md`
- Ensure `body_json` is valid JSON
- Check model names exist in database

## See Also

- **Workload Format:** `tests/performance/workloads/README.md`
- **Correctness Tests:** `tests/scheduling_data/README.md`
- **SDI Documentation:** `src/logos/sdi/README.md`
