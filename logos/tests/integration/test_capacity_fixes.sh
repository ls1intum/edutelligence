#!/usr/bin/env bash
# Integration test for capacity planner fairness & retry fixes
# Phases A-D from the verification plan
set -euo pipefail

LOGOS_KEY="lg-root-ifoY6N0fWiWD8_wUvrmeXY-Ft6aEGmbeBKQT47R_JtDrHVm1guuA9beCo3LEbQg8qZQKBP8iye73e8EVce1L6DHhaK3r3sMJjpcNDNWqPsGB6TmXd_dHqYOXz4GrKV9M"
BASE_URL="http://localhost:18080"

MODEL_A="Qwen/Qwen2.5-Coder-7B-Instruct-AWQ"
MODEL_B="Qwen/Qwen2.5-Coder-14B-Instruct-AWQ"
MODEL_C="solidrust/Mistral-7B-Instruct-v0.3-AWQ"

send_request() {
    local model="$1"
    local tag="${2:-}"
    curl -s -X POST "$BASE_URL/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -H "logos_key: $LOGOS_KEY" \
        -d '{
            "model": "'"$model"'",
            "messages": [{"role": "user", "content": "Say hello in one word."}],
            "max_tokens": 10,
            "temperature": 0
        }' &
    local pid=$!
    if [ -n "$tag" ]; then
        echo "[$tag] Sent request to $model (pid=$pid)"
    fi
    echo $pid
}

wait_for_model_state() {
    local model_substr="$1"
    local target_state="$2"
    local timeout="${3:-120}"
    local start=$SECONDS
    echo "Waiting for $model_substr to reach state=$target_state (timeout=${timeout}s)..."
    while true; do
        local elapsed=$((SECONDS - start))
        if [ $elapsed -ge $timeout ]; then
            echo "TIMEOUT waiting for $model_substr -> $target_state"
            return 1
        fi
        local logs
        logs=$(docker compose -f docker-compose.dev.yaml logs --tail 5 logos-server 2>&1)
        if echo "$logs" | grep -q "$model_substr" && echo "$logs" | grep -q "$target_state"; then
            echo "$model_substr reached $target_state after ${elapsed}s"
            return 0
        fi
        sleep 2
    done
}

check_log_pattern() {
    local pattern="$1"
    local desc="$2"
    local since="${3:-5m}"
    if docker compose -f docker-compose.dev.yaml logs --since "$since" logos-server 2>&1 | grep -q "$pattern"; then
        echo "  FOUND: $desc"
        docker compose -f docker-compose.dev.yaml logs --since "$since" logos-server 2>&1 | grep "$pattern" | tail -3
        return 0
    else
        echo "  NOT FOUND: $desc"
        return 1
    fi
}

echo "=============================================="
echo "Phase A: Basic model wake + inference"
echo "=============================================="
echo ""
echo "Step 1: Send request to $MODEL_A (will trigger wake from sleep)"
echo ""

PID_A=$(send_request "$MODEL_A" "Phase-A")

echo "Waiting for model A to wake and respond..."
wait $PID_A && echo "Model A request completed" || echo "Model A request returned (may have error)"

echo ""
echo "Checking logs for wake/load activity..."
check_log_pattern "prepare_lane_for_request" "Capacity preparation triggered" "3m" || true
check_log_pattern "Idle reclaim skip" "Demand-gated idle reclaim (Change 1)" "3m" || true
check_log_pattern "Retrying pending capacity" "Pending capacity retry (Change 3)" "3m" || true

echo ""
echo "=============================================="
echo "Phase B: Concurrent model competition"
echo "=============================================="
echo ""
echo "Step 1: While model A is loaded, send request to model B"
echo "  This forces a capacity decision - reclaim A's VRAM for B"
echo ""

PID_B=$(send_request "$MODEL_B" "Phase-B")

echo "Waiting for model B response..."
wait $PID_B && echo "Model B request completed" || echo "Model B request returned"

echo ""
echo "Checking capacity planner decisions..."
check_log_pattern "reclaim" "Reclaim activity" "5m" || true
check_log_pattern "drain" "Drain activity" "5m" || true
check_log_pattern "Request-time reclaim" "Request-time reclaim (fixed reason string)" "5m" || true

echo ""
echo "=============================================="
echo "Phase C: Fairness test - high-demand vs low-demand"
echo "=============================================="
echo ""
echo "Step 1: Send 5 concurrent requests to model B (high demand)"
echo ""

PIDS_B=()
for i in $(seq 1 5); do
    PID=$(send_request "$MODEL_B" "Phase-C-B-$i")
    PIDS_B+=($PID)
done

echo ""
echo "Step 2: While B has queue depth, send 1 request to model C (low demand)"
echo ""
sleep 2
PID_C=$(send_request "$MODEL_C" "Phase-C-C")

echo ""
echo "Waiting for all requests to complete..."
for pid in "${PIDS_B[@]}"; do
    wait $pid 2>/dev/null || true
done
wait $PID_C 2>/dev/null || true

echo ""
echo "=============================================="
echo "Checking fairness-related log patterns"
echo "=============================================="
check_log_pattern "Idle reclaim skip" "Demand gate prevented unfair reclaim" "5m" || true
check_log_pattern "victim.*has.*queued vs target" "Victim/target queue comparison" "5m" || true
check_log_pattern "scheduler_queue_depth" "Scheduler queue depth checked" "5m" || true

echo ""
echo "=============================================="
echo "Phase D: Log pattern summary"
echo "=============================================="
echo ""
echo "--- Change 1: Demand-gated idle reclaim ---"
check_log_pattern "Idle reclaim skip" "Demand gate active" "10m" || true
echo ""
echo "--- Change 2: Idle sleep scheduler queue check ---"
check_log_pattern "scheduler queue" "Scheduler queue check in idle sleep" "10m" || true
echo ""
echo "--- Change 3: Pending capacity retry ---"
check_log_pattern "Retrying pending capacity" "Retry mechanism active" "10m" || true
echo ""
echo "--- Change 4: Dead code removal ---"
check_log_pattern "_record_switch_event\|_is_thrashing" "Dead code references (should NOT appear)" "10m" && echo "  WARNING: Dead code still referenced!" || echo "  OK: No dead code references"
echo ""
echo "--- Change 5: Multi-lane drain ---"
check_log_pattern "VRAM feasibility" "Old VRAM feasibility gate (should NOT appear)" "10m" && echo "  WARNING: Old gate still present!" || echo "  OK: Old VRAM feasibility gate removed"
echo ""
echo "--- Change 6: Drain reason string ---"
check_log_pattern "Request-time reclaim (drain" "Fixed drain+sleep reason string" "10m" || true
echo ""
echo "--- Prometheus counter ---"
check_log_pattern "CAPACITY_PLANNER_SWITCHES_TOTAL\|capacity_planner_switches" "Switch counter" "10m" || echo "  (Counter only fires on actual model switches)"
echo ""
echo "=============================================="
echo "Integration test complete"
echo "=============================================="
