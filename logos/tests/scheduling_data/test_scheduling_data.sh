#!/usr/bin/env bash
# Integration test runner for Queue + SDI + Scheduler
# Runs comprehensive integration tests in Docker

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

echo "======================================"
echo "SDI Integration Test Suite (Docker)"
echo "Scheduling Data Interface Tests"
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
    if docker compose ps "$CONTAINER_NAME" 2>/dev/null | grep -q "Up\|running"; then
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
log "Running integration tests..."
echo ""

test_exit_code=0
docker compose exec "$CONTAINER_NAME" poetry run pytest tests/scheduling_data/test_scheduling_data.py -v || test_exit_code=$?

echo ""
echo "======================================"

if [ $test_exit_code -eq 0 ]; then
    printf "\n\033[1;32m✅ Success!\033[0m All 21 integration tests passed.\n\n"
    log "Test coverage:"
    log "  - Mixed workload scenarios (1 test)"
    log "  - Rate limit handling (1 test)"
    log "  - Cold start scenarios (3 tests)"
    log "  - High traffic burst (3 tests)"
    log "  - SDI integration (3 tests)"
    log "  - SDI data usage (5 tests) ← CRITICAL"
    log "  - Request lifecycle (5 tests) ← CRITICAL"
    printf "\n"
else
    printf "\n\033[1;31m❌ Failed!\033[0m Tests failed with exit code: %s\n\n" "$test_exit_code"
fi

echo "======================================"

exit $test_exit_code
