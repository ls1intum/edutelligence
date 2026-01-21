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
WORKLOAD="tests/performance/workloads/sample_workload_mixed.csv"
API_BASE="http://localhost:8080"
LATENCY_SLO_MS="10000"
OUTPUT="tests/performance/results/benchmark_$(date +%Y%m%d_%H%M%S).csv"

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

# Check docker is available
if ! command -v docker &> /dev/null; then
    err "docker is not installed or not in PATH"
    exit 1
fi

log "Starting Docker containers..."
docker compose up -d
ok "Containers started"

echo ""
log "Waiting for container to be ready..."

# Wait for container to be running and responsive
attempts=0
max_attempts=$((MAX_WAIT_SECONDS / 2))

while [ $attempts -lt $max_attempts ]; do
    if docker compose ps "$CONTAINER_NAME" 2>/dev/null | grep -qE "Up|running"; then
        if docker compose exec -T "$CONTAINER_NAME" poetry --version >/dev/null 2>&1; then
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

echo ""
log "Running performance tests..."
echo ""

test_exit_code=0
docker compose exec "$CONTAINER_NAME" poetry run python tests/performance/run_api_workload.py \
    --logos-key "$LOGOS_KEY" \
    --workload "$WORKLOAD" \
    --api-base "$API_BASE" \
    --output "$OUTPUT" \
    --latency-slo-ms "$LATENCY_SLO_MS" || test_exit_code=$?

echo ""
echo "======================================"

if [ $test_exit_code -eq 0 ]; then
    printf "\n\033[1;32m✅ Success!\033[0m Performance benchmark completed.\n\n"
    log "Test results:"
    log "  - Detailed metrics: tests/performance/results/"
    log "  - Latency charts: tests/performance/results/*.png"
    log "  - Summary CSV: tests/performance/results/*_summary.csv"
    log "  - Detailed CSV: tests/performance/results/*_detailed.csv"
    printf "\n"
else
    printf "\n\033[1;31m❌ Failed!\033[0m Performance test failed with exit code: %s\n\n" "$test_exit_code"
fi

echo "======================================"

exit $test_exit_code
