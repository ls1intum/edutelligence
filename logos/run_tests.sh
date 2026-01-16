#!/usr/bin/env bash
# Unified test runner for Logos
# Usage:
#   ./run_tests.sh [unit|integration|sdi|performance|all] [extra args...]

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_ROOT"

if [ $# -gt 0 ]; then
  CATEGORY="$1"
  shift
else
  CATEGORY="all"
fi

EXTRA_ARGS=("$@")

usage() {
  cat <<'EOF'
Usage: ./run_tests.sh [unit|integration|sdi|performance|all] [extra args...]

Examples:
  ./run_tests.sh unit
  ./run_tests.sh sdi --azure-live-model-id=12
  ./run_tests.sh integration --test test_sync_proxy -vv
  ./run_tests.sh all
EOF
}

run_unit() {
  if [ -d tests/unit ]; then
    echo "=== Running unit tests ==="
    poetry run pytest tests/unit -v "${EXTRA_ARGS[@]}"
  else
    echo "No unit tests directory (tests/unit); skipping."
  fi
}

run_integration() {
  echo "=== Running integration tests ==="
  ./tests/integration/run_integration_tests.sh "${EXTRA_ARGS[@]}"
}

run_sdi() {
  echo "=== Running SDI/scheduling tests ==="
  ./run_scheduling_data_test.sh "${EXTRA_ARGS[@]}"
}

run_performance() {
  if [ -x ./tests/performance/test_scheduling_performance.sh ]; then
    echo "=== Running performance tests ==="
    ./tests/performance/test_scheduling_performance.sh "${EXTRA_ARGS[@]}"
  else
    echo "Performance runner not found; skipping."
  fi
}

if [ "$CATEGORY" = "all" ] && [ ${#EXTRA_ARGS[@]} -gt 0 ]; then
  echo "Note: extra args are ignored for 'all' runs."
fi

case "$CATEGORY" in
  unit) run_unit ;;
  integration) run_integration ;;
  sdi) run_sdi ;;
  performance) run_performance ;;
  all)
    run_unit
    run_integration
    run_sdi
    run_performance
    ;;
  *) usage; exit 1 ;;
esac
