#!/usr/bin/env bash
# Performance test runner for API workload replay
# Runs comprehensive performance benchmarks against live Logos API

set -Eeuo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
cd "$REPO_ROOT"

CONTAINER_NAME="logos-server"
MAX_WAIT_SECONDS=60

# Colored logging
log() { printf "[\033[1;34mINFO\033[0m] %s\n" "$*"; }
ok() { printf "[\033[1;32m OK \033[0m] %s\n" "$*"; }
err() { printf "[\033[1;31mFAIL\033[0m] %s\n" "$*"; }

# Default values
LOGOS_KEY=""
WORKLOAD="tests/performance/workloads/explicit/10m/workload_explicit_local5_skewed_bursty_10m.csv"
API_BASE="http://localhost:18080"
LATENCY_SLO_MS="10000"
OUTPUT=""

is_local_api_base() {
  case "$1" in
    http://localhost:*|https://localhost:*|http://127.0.0.1:*|https://127.0.0.1:*|http://0.0.0.0:*|https://0.0.0.0:*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --logos-key)
      LOGOS_KEY="$2"
      shift 2
      ;;
    --workload)
      WORKLOAD="$2"
      shift 2
      ;;
    --api-base)
      API_BASE="$2"
      shift 2
      ;;
    --output)
      OUTPUT="$2"
      shift 2
      ;;
    --latency-slo-ms)
      LATENCY_SLO_MS="$2"
      shift 2
      ;;
    *)
      err "Unknown argument: $1"
      echo "Usage: $0 --logos-key <KEY> [--workload <CSV>] [--api-base <URL>] [--output <PATH>] [--latency-slo-ms <MS>]"
      exit 1
      ;;
  esac
done

# Validate required arguments
if [ -z "$LOGOS_KEY" ]; then
    err "Error: --logos-key is required"
    echo "Usage: $0 --logos-key <KEY> [--workload <CSV>] [--api-base <URL>] [--output <PATH>] [--latency-slo-ms <MS>]"
    exit 1
fi

echo "======================================"
echo "Performance Test Suite (Docker)"
echo "API Workload Replay & Benchmarking"
echo "======================================"
echo ""

if is_local_api_base "$API_BASE"; then
    log "Execution mode: local/docker"

    if ! command -v docker &> /dev/null; then
        err "docker is not installed or not in PATH"
        exit 1
    fi

    log "Starting benchmark services..."
    docker compose up -d logos-db logos-server
    ok "Benchmark services started"

    echo ""
    log "Waiting for container to be ready..."

    attempts=0
    max_attempts=$((MAX_WAIT_SECONDS / 2))

    while [ $attempts -lt $max_attempts ]; do
        if docker compose ps "$CONTAINER_NAME" 2>/dev/null | grep -qE "Up|running"; then
            if docker compose exec -T "$CONTAINER_NAME" python --version >/dev/null 2>&1; then
                ok "Container is ready (${attempts} attempts, $((attempts * 2))s)"
                break
            fi
        fi

        attempts=$((attempts + 1))
        if [ $attempts -ge $max_attempts ]; then
            err "Container failed to become ready within ${MAX_WAIT_SECONDS}s"
            echo ""
            err "Container logs:"
            docker compose logs --tail=30 "$CONTAINER_NAME"
            exit 1
        fi

        sleep 2
    done
else
    log "Execution mode: remote/http-only"
    if ! command -v poetry &> /dev/null; then
        err "poetry is not installed or not in PATH"
        exit 1
    fi
fi

echo ""
log "Running performance tests..."
echo ""

test_exit_code=0
RUN_TIMESTAMP="$(date +"%Y%m%d_%H%M%S")"
if is_local_api_base "$API_BASE"; then
    log "Syncing local benchmark files into the container..."
    docker compose cp tests/performance/run_api_workload.py "$CONTAINER_NAME":/app/tests/performance/run_api_workload.py >/dev/null
    docker compose cp tests/performance/workloads/README.md "$CONTAINER_NAME":/app/tests/performance/workloads/README.md >/dev/null
    docker compose cp tests/performance/workloads/explicit "$CONTAINER_NAME":/app/tests/performance/workloads >/dev/null
    docker compose cp tests/performance/workloads/resource "$CONTAINER_NAME":/app/tests/performance/workloads >/dev/null
    docker compose cp src/logos/dbutils/dbmanager.py "$CONTAINER_NAME":/app/src/logos/dbutils/dbmanager.py >/dev/null

    RUNNER_CMD=(
        python /app/tests/performance/run_api_workload.py
        --logos-key "$LOGOS_KEY"
        --workload "/app/$WORKLOAD"
        --api-base "http://127.0.0.1:8080"
        --run-timestamp "$RUN_TIMESTAMP"
        --latency-slo-ms "$LATENCY_SLO_MS"
    )
    if [ -n "$OUTPUT" ]; then
        RUNNER_CMD+=(--output "/app/$OUTPUT")
    fi
    docker compose exec "$CONTAINER_NAME" "${RUNNER_CMD[@]}" || test_exit_code=$?
else
    RUNNER_CMD=(
        poetry run python tests/performance/run_api_workload.py
        --logos-key "$LOGOS_KEY"
        --workload "$WORKLOAD"
        --api-base "$API_BASE"
        --run-timestamp "$RUN_TIMESTAMP"
        --latency-slo-ms "$LATENCY_SLO_MS"
    )
    if [ -n "$OUTPUT" ]; then
        RUNNER_CMD+=(--output "$OUTPUT")
    fi
    "${RUNNER_CMD[@]}" || test_exit_code=$?
fi

echo ""
echo "======================================"

if [ $test_exit_code -eq 0 ]; then
    printf "\n\033[1;32m✅ Success!\033[0m Performance benchmark completed.\n\n"
    log "Test results:"
    log "  - Each run is saved in its own folder under tests/performance/results/"
    log "  - Folder format: YYYYMMDD_HHMMSS - experiment-name"
    log "  - Summary CSV: summary.csv"
    log "  - Detailed CSV: detailed.csv"
    log "  - Runtime snapshots: runtime_samples.jsonl"
    log "  - VRAM snapshots: provider_vram.json"
    log "  - Aggregated request stats: request_log_stats.json"
    log "  - Run metadata: run_meta.json"
    log "  - Charts: detailed*.png"
    printf "\n"
else
    printf "\n\033[1;31m❌ Failed!\033[0m Performance test failed with exit code: %s\n\n" "$test_exit_code"
fi

echo "======================================"

exit $test_exit_code
