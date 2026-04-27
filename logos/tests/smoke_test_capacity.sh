#!/usr/bin/env bash
# smoke_test_capacity.sh — End-to-end capacity planner smoke tests
#
# Tests all lane lifecycle scenarios:
#   1. Empty system → single request → cold load
#   2. Model loaded/awake → same model request → instant
#   3. Model loaded/awake → different model request → sleep+load
#   4. Model sleeping → same model request → wake
#   5. Model sleeping → different model request → stop+load
#   6. Two models sleeping → third model request → evict+load
#   7. Rapid alternation (mini-benchmark): 7B ↔ 14B interleaved
#   8. Three-model rotation: 7B → 14B → DeepSeek → 7B
#
# Usage: bash tests/smoke_test_capacity.sh [API_KEY]

set -euo pipefail

API_BASE="${API_BASE:-http://localhost:18080}"
API_KEY="${1:-lg-root-ifoY6N0fWiWD8_wUvrmeXY-Ft6aEGmbeBKQT47R_JtDrHVm1guuA9beCo3LEbQg8qZQKBP8iye73e8EVce1L6DHhaK3r3sMJjpcNDNWqPsGB6TmXd_dHqYOXz4GrKV9M}"

MODEL_7B="Qwen/Qwen2.5-Coder-7B-Instruct-AWQ"
MODEL_14B="Qwen/Qwen2.5-Coder-14B-Instruct-AWQ"
MODEL_DS="casperhansen/deepseek-r1-distill-llama-8b-awq"

PASS=0
FAIL=0
TOTAL=0

# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

send_request() {
    local model="$1"
    local max_tokens="${2:-20}"
    local timeout="${3:-300}"
    local start_ms
    start_ms=$(date +%s%3N)

    local response
    response=$(curl -s --max-time "$timeout" -w "\n%{http_code}" -X POST "$API_BASE/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $API_KEY" \
        -d "{\"model\":\"$model\",\"messages\":[{\"role\":\"user\",\"content\":\"Say hi.\"}],\"max_tokens\":$max_tokens}")

    local http_code
    http_code=$(echo "$response" | tail -1)
    local body
    body=$(echo "$response" | sed '$d')
    local end_ms
    end_ms=$(date +%s%3N)
    local dur_ms=$((end_ms - start_ms))

    echo "$http_code|$dur_ms|$body"
}

check_result() {
    local test_name="$1"
    local result="$2"
    local max_dur_ms="${3:-300000}"
    local http_code dur_ms body

    TOTAL=$((TOTAL + 1))
    http_code=$(echo "$result" | cut -d'|' -f1)
    dur_ms=$(echo "$result" | cut -d'|' -f2)
    body=$(echo "$result" | cut -d'|' -f3-)

    if [ "$http_code" = "200" ] && [ "$dur_ms" -le "$max_dur_ms" ]; then
        PASS=$((PASS + 1))
        echo "  ✓ $test_name — ${dur_ms}ms (HTTP $http_code)"
    else
        FAIL=$((FAIL + 1))
        local reason=""
        if [ "$http_code" != "200" ]; then
            reason="HTTP $http_code"
            # Extract error detail
            local detail
            detail=$(echo "$body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('detail',''))" 2>/dev/null || echo "")
            [ -n "$detail" ] && reason="$reason: $detail"
        fi
        if [ "$dur_ms" -gt "$max_dur_ms" ]; then
            reason="${reason:+$reason, }${dur_ms}ms > ${max_dur_ms}ms"
        fi
        echo "  ✗ $test_name — ${dur_ms}ms (FAIL: $reason)"
    fi
}

wait_for_idle() {
    # Wait for all lanes to go idle (no active requests)
    local max_wait="${1:-30}"
    local waited=0
    while [ $waited -lt $max_wait ]; do
        sleep 2
        waited=$((waited + 2))
    done
}

get_lane_summary() {
    docker logs logos-server --since 10s 2>&1 | grep -o "lanes=[0-9]* loaded=[0-9]* sleeping=[0-9]*" | tail -1
}

# ──────────────────────────────────────────────────────────────────────
# Pre-flight: ensure system is clean
# ──────────────────────────────────────────────────────────────────────

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Capacity Planner Smoke Tests                               ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "API: $API_BASE"
echo "Models: 7B, 14B, DeepSeek-8B"
echo ""

# ──────────────────────────────────────────────────────────────────────
# Test 1: Empty system → cold load (first request)
# ──────────────────────────────────────────────────────────────────────

echo "━━━ Test 1: Empty system → 7B cold load ━━━"
echo "  Expecting: cold load ~45-60s"
result=$(send_request "$MODEL_7B" 10 180)
check_result "7B cold load from empty" "$result" 180000

# ──────────────────────────────────────────────────────────────────────
# Test 2: Model loaded/awake → same model (instant)
# ──────────────────────────────────────────────────────────────────────

echo ""
echo "━━━ Test 2: 7B loaded → 7B request (instant) ━━━"
echo "  Expecting: <2s (model already awake)"
result=$(send_request "$MODEL_7B" 10 30)
check_result "7B instant (already loaded)" "$result" 5000

# ──────────────────────────────────────────────────────────────────────
# Test 3: Model loaded/awake → different model (sleep + cold load)
# ──────────────────────────────────────────────────────────────────────

echo ""
echo "━━━ Test 3: 7B awake → DeepSeek request (sleep 7B + load DS) ━━━"
echo "  Expecting: sleep 7B (~1s) + cold load DS (~45-60s) = ~60s"
result=$(send_request "$MODEL_DS" 10 180)
check_result "DS cold load while 7B awake" "$result" 180000

# ──────────────────────────────────────────────────────────────────────
# Test 4: Verify DS is now loaded — instant request
# ──────────────────────────────────────────────────────────────────────

echo ""
echo "━━━ Test 4: DeepSeek loaded → DS request (instant) ━━━"
echo "  Expecting: <2s"
result=$(send_request "$MODEL_DS" 10 30)
check_result "DS instant (already loaded)" "$result" 5000

# ──────────────────────────────────────────────────────────────────────
# Test 5: Model loaded → different model → triggers sleep+load cycle
#          (7B should be sleeping from test 3, DS is awake)
# ──────────────────────────────────────────────────────────────────────

echo ""
echo "━━━ Test 5: DS awake, 7B sleeping → 7B request (sleep DS + wake 7B) ━━━"
echo "  Expecting: sleep DS (~1s) + wake 7B (~3-5s) = ~10s"
result=$(send_request "$MODEL_7B" 10 120)
check_result "7B wake from sleep (DS sleeps)" "$result" 120000

# ──────────────────────────────────────────────────────────────────────
# Test 6: Verify 7B awake now — instant
# ──────────────────────────────────────────────────────────────────────

echo ""
echo "━━━ Test 6: 7B loaded → 7B request (instant verification) ━━━"
result=$(send_request "$MODEL_7B" 10 30)
check_result "7B instant after wake" "$result" 5000

# ──────────────────────────────────────────────────────────────────────
# Test 7: 14B request — requires more VRAM, should evict sleeping DS
#          (7B awake ~16.7GB, DS sleeping ~1.4GB, 14B needs 25.5GB)
#          Must stop 7B + DS to fit 14B
# ──────────────────────────────────────────────────────────────────────

echo ""
echo "━━━ Test 7: 7B awake + DS sleeping → 14B request (evict both) ━━━"
echo "  Expecting: sleep 7B + stop DS + cold load 14B = ~60-90s"
result=$(send_request "$MODEL_14B" 10 180)
check_result "14B cold load (evicting 7B+DS)" "$result" 180000

# ──────────────────────────────────────────────────────────────────────
# Test 8: 14B loaded → 14B request (instant)
# ──────────────────────────────────────────────────────────────────────

echo ""
echo "━━━ Test 8: 14B loaded → 14B instant ━━━"
result=$(send_request "$MODEL_14B" 10 30)
check_result "14B instant (already loaded)" "$result" 5000

# ──────────────────────────────────────────────────────────────────────
# Test 9: 14B awake → 7B request (sleep 14B + cold load 7B)
# ──────────────────────────────────────────────────────────────────────

echo ""
echo "━━━ Test 9: 14B awake → 7B request (sleep 14B + load 7B) ━━━"
result=$(send_request "$MODEL_7B" 10 180)
check_result "7B load while 14B active" "$result" 180000

# ──────────────────────────────────────────────────────────────────────
# Test 10: Three-model rotation — 7B → DS → 14B, verify each works
# ──────────────────────────────────────────────────────────────────────

echo ""
echo "━━━ Test 10: Three-model rotation (7B → DS → 14B) ━━━"
echo "  7B should be awake from test 9"

# DS request (sleep 7B + load/wake DS)
result=$(send_request "$MODEL_DS" 10 180)
check_result "Rotation: DS load" "$result" 180000

# 14B request (sleep DS + load/wake 14B)
result=$(send_request "$MODEL_14B" 10 180)
check_result "Rotation: 14B load" "$result" 180000

# Back to 7B (sleep 14B + load/wake 7B)
result=$(send_request "$MODEL_7B" 10 180)
check_result "Rotation: 7B load" "$result" 180000

# ──────────────────────────────────────────────────────────────────────
# Test 11: Rapid alternation mini-benchmark (5 requests each, interleaved)
# ──────────────────────────────────────────────────────────────────────

echo ""
echo "━━━ Test 11: Rapid alternation — 7B/DS interleaved (5 each) ━━━"
echo "  Testing sleep/wake cycle stability"

for i in 1 2 3 4 5; do
    result=$(send_request "$MODEL_7B" 10 180)
    check_result "Alt $i/5: 7B" "$result" 180000

    result=$(send_request "$MODEL_DS" 10 180)
    check_result "Alt $i/5: DS" "$result" 180000
done

# ──────────────────────────────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────────────────────────────

echo ""
echo "══════════════════════════════════════════════════════════════"
echo "  Results: $PASS passed / $FAIL failed / $TOTAL total"
echo "══════════════════════════════════════════════════════════════"

if [ "$FAIL" -gt 0 ]; then
    echo "  ⚠  Some tests failed — check planner/workernode logs"
    exit 1
else
    echo "  ✓  All tests passed"
    exit 0
fi
