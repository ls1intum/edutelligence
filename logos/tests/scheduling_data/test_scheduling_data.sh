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

test_exit_code=0

# Build pytest arguments from script parameters
PYTEST_ARGS=()

# Parse script arguments and convert to pytest options
while [[ $# -gt 0 ]]; do
  case $1 in


    --ollama-live-model-id=*)
      PYTEST_ARGS+=("--ollama-live-model-id=${1#*=}")
      shift
      ;;
    --ollama-live-model-id)
      PYTEST_ARGS+=("--ollama-live-model-id=$2")
      shift 2
      ;;
    --azure-model-id=*)
      PYTEST_ARGS+=("--azure-model-id=${1#*=}")
      shift
      ;;
    --azure-model-id)
      PYTEST_ARGS+=("--azure-model-id=$2")
      shift 2
      ;;
    --azure-live-model-id=*)
      PYTEST_ARGS+=("--azure-live-model-id=${1#*=}")
      shift
      ;;
    --azure-live-model-id)
      PYTEST_ARGS+=("--azure-live-model-id=$2")
      shift 2
      ;;
    -h|--help)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --ollama-live-model-id ID     Ollama model ID for live tests"
      echo "  --azure-model-id ID           Azure model ID (default: 12)"
      echo "  --azure-live-model-id ID      Azure live model ID"
      echo ""
      echo "Examples:"
      echo "  # Run all tests (skip live tests)"
      echo "  $0"
      echo ""

      echo "  # Run with all live tests"
      echo "  $0 --ollama-live-model-id=18 --azure-live-model-id=12"
      exit 0
      ;;
    *)
      err "Unknown option: $1"
      echo "Use --help for usage information"
      exit 1
      ;;
  esac
done

echo ""
log "Running integration tests..."
echo ""

# Run pytest with collected arguments
if [ ${#PYTEST_ARGS[@]} -eq 0 ]; then
  log "Running tests without live test parameters (live tests will be skipped)"
  docker compose exec "$CONTAINER_NAME" poetry run pytest tests/scheduling_data -v || test_exit_code=$?
else
  log "Running tests with parameters: ${PYTEST_ARGS[*]}"
  docker compose exec "$CONTAINER_NAME" poetry run pytest tests/scheduling_data "${PYTEST_ARGS[@]}" -v || test_exit_code=$?
fi

echo ""
echo "======================================"

if [ $test_exit_code -eq 0 ]; then
    printf "\n\033[1;32m✅ Success!\033[0m SDI test suite passed.\n\n"
    log "Test coverage:"
    log "  - Mixed workload scenarios"
    log "  - Rate limit handling"
    log "  - Cold start and high-traffic scenarios"
    log "  - SDI integration and data usage"
    log "  - Request lifecycle (sequential/parallel/multi-provider)"
    log "  - Request lifecycle (sequential/parallel/multi-provider)"
    printf "\n"
else
    printf "\n\033[1;31m❌ Failed!\033[0m Tests failed with exit code: %s\n\n" "$test_exit_code"
fi

echo "======================================"

exit $test_exit_code
