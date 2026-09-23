#!/usr/bin/env bash
# Demonstrates that killing one logos-webservice replica is not user-visible
# on the public inference gateway (/v1, /openai, /jobs) — see
# docs/deployment.md#failover-verification.
#
# Fires a steady stream of unauthenticated GET /v1/models requests at the
# gateway, kills one webservice container partway through, and fails if any
# request comes back as a connection error or a 5xx — those are the only
# outcomes a live replica behind Traefik would not otherwise produce.
# Ordinary 401s (no API key given) count as success: they prove the request
# reached a healthy instance and was processed.
#
# Usage:
#   scripts/gateway-failover-demo.sh [BASE_URL] [DURATION_SECONDS]
#
# Prerequisites: the target compose stack already up with
# LOGOS_WEBSERVICE_REPLICAS>=2 (or `--scale logos-webservice=2`). Override
# COMPOSE_FILE to point at a non-dev stack.

set -euo pipefail

BASE_URL="${1:-http://localhost:18081}"
DURATION="${2:-30}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.dev.yaml}"
KILL_AFTER="${KILL_AFTER:-5}"

cd "$(dirname "$0")/.."

mapfile -t CONTAINERS < <(docker compose -f "$COMPOSE_FILE" ps -q logos-webservice)
if [ "${#CONTAINERS[@]}" -lt 2 ]; then
  echo "Need >=2 logos-webservice replicas running under $COMPOSE_FILE (found ${#CONTAINERS[@]})." >&2
  echo "Start with: docker compose -f $COMPOSE_FILE up -d --scale logos-webservice=2" >&2
  exit 1
fi
KILL_TARGET="${CONTAINERS[0]}"

RESULTS_FILE="$(mktemp)"
trap 'rm -f "$RESULTS_FILE"' EXIT

echo "Firing requests at $BASE_URL/v1/models for ${DURATION}s; killing $KILL_TARGET after ${KILL_AFTER}s..."

(
  END=$((SECONDS + DURATION))
  while [ "$SECONDS" -lt "$END" ]; do
    START_MS=$(date +%s%3N)
    STATUS=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$BASE_URL/v1/models" || echo "000")
    END_MS=$(date +%s%3N)
    echo "$STATUS $((END_MS - START_MS))" >>"$RESULTS_FILE"
    sleep 0.2
  done
) &
LOAD_PID=$!

sleep "$KILL_AFTER"
echo "Killing $KILL_TARGET ..."
docker kill "$KILL_TARGET" >/dev/null

wait "$LOAD_PID"

TOTAL=$(wc -l <"$RESULTS_FILE")
# Any status the gateway itself produced (2xx-4xx) means a live instance
# answered; 000 (curl couldn't connect/timed out) or 5xx means it did not.
FAILED=$(awk '$1 !~ /^[2-4][0-9][0-9]$/ {c++} END{print c+0}' "$RESULTS_FILE")
MAX_LATENCY=$(awk '{if ($2 > m) m = $2} END{print m + 0}' "$RESULTS_FILE")

echo "Requests: $TOTAL, failed (connection error / 5xx): $FAILED, max latency: ${MAX_LATENCY}ms"
if [ "$FAILED" -gt 0 ]; then
  echo "FAIL: killing one replica was user-visible ($FAILED failed requests)." >&2
  exit 1
fi
echo "PASS: no failed requests while one replica was killed."
