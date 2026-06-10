#!/usr/bin/env bash
# SDI / scheduling_data test runner
# - Spins up docker compose (logos-server) for parity with perf setup
# - Runs mocked SDI tests (no DB, no network, no creds)

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
cd "$REPO_ROOT"

CONTAINER_NAME="logos-server"
MAX_WAIT_SECONDS=60

log() { printf "[\033[1;34mINFO\033[0m] %s\n" "$*"; }
ok()  { printf "[\033[1;32m OK \033[0m] %s\n" "$*"; }
warn(){ printf "[\033[1;33mWARN\033[0m] %s\n" "$*"; }
err() { printf "[\033[1;31mFAIL\033[0m] %s\n" "$*"; }

echo "======================================"
echo "SDI / Scheduling Data Tests (mocked)"
echo "======================================"
echo ""

if command -v docker &>/dev/null; then
  log "Starting Docker containers..."
  if docker compose up -d; then
    ok "Containers started"

    log "Waiting for container to be ready..."
    attempts=0
    max_attempts=$((MAX_WAIT_SECONDS / 2))
    ready=0

    while [ $attempts -lt $max_attempts ]; do
      if docker compose ps "$CONTAINER_NAME" 2>/dev/null | grep -qE "Up|running"; then
          if docker compose exec -T "$CONTAINER_NAME" poetry --version >/dev/null 2>&1; then
              ok "Container is ready (${attempts} attempts, $((attempts * 2))s)"
              ready=1
              break
          fi
      fi
      attempts=$((attempts + 1))
      sleep 2
    done

    if [ "$ready" -ne 1 ]; then
      warn "Container not ready after ${MAX_WAIT_SECONDS}s; continuing with local env."
    fi
  else
    warn "Docker compose failed; continuing with local env."
  fi
else
  warn "Docker not found; running tests locally without containers."
fi

echo ""
log "Running SDI tests (fully mocked; no DB/network required)..."
echo ""

test_exit=0
poetry run pytest tests/unit/queue tests/unit/sdi tests/unit/main tests/unit/responses -v --color=yes "$@" || test_exit=$?

echo ""
log "Running API endpoint minimal tests (proxy/resource/job combos)..."
poetry run pytest tests/integration/sdi/test_api_endpoints.py -v --color=yes || test_exit=$?

exit $test_exit
