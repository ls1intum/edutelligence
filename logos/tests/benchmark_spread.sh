#!/usr/bin/env bash
# benchmark_spread.sh — Multi-model spread benchmark (150 / 300 / 600 requests)
#
# Sends requests in model-grouped bursts — each burst fires CONCURRENCY
# parallel requests for ONE model, then rotates.  This matches how a
# single-GPU system actually serves: one active model at a time, with
# sleep/wake cycles between model switches.
#
# Usage: bash tests/benchmark_spread.sh [TOTAL_REQUESTS] [CONCURRENCY] [BURST_SIZE]
#   TOTAL_REQUESTS: 150, 300, or 600 (default: 150)
#   CONCURRENCY:    parallel requests per burst (default: 5)
#   BURST_SIZE:     requests per model before rotating (default: 10)

set -euo pipefail

API_BASE="${API_BASE:-http://localhost:18080}"
API_KEY="${API_KEY:-lg-root-ifoY6N0fWiWD8_wUvrmeXY-Ft6aEGmbeBKQT47R_JtDrHVm1guuA9beCo3LEbQg8qZQKBP8iye73e8EVce1L6DHhaK3r3sMJjpcNDNWqPsGB6TmXd_dHqYOXz4GrKV9M}"

TOTAL="${1:-150}"
CONCURRENCY="${2:-5}"
BURST="${3:-10}"

MODEL_7B="Qwen/Qwen2.5-Coder-7B-Instruct-AWQ"
MODEL_14B="Qwen/Qwen2.5-Coder-14B-Instruct-AWQ"
MODEL_MISTRAL="solidrust/Mistral-7B-Instruct-v0.3-AWQ"
MODELS=("$MODEL_7B" "$MODEL_14B" "$MODEL_MISTRAL")

RESULTS_DIR="tests/benchmark_results"
mkdir -p "$RESULTS_DIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
CSV_FILE="$RESULTS_DIR/spread_${TOTAL}_${TIMESTAMP}.csv"

PER_MODEL=$((TOTAL / 3))

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Multi-Model Spread Benchmark                               ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "  Total requests:  $TOTAL ($PER_MODEL per model)"
echo "  Concurrency:     $CONCURRENCY"
echo "  Burst size:      $BURST (per model before rotating)"
echo "  API:             $API_BASE"
echo "  Output:          $CSV_FILE"
echo ""

# CSV header
echo "request_id,model,status,duration_ms,http_code,timestamp" > "$CSV_FILE"

# ──────────────────────────────────────────────────────────────────────
# Worker function
# ──────────────────────────────────────────────────────────────────────

send_one() {
    local req_id="$1"
    local model="$2"
    local ts
    ts=$(date +%s%3N)
    local start_ms=$ts

    local response
    response=$(curl -s --max-time 600 -w "\n%{http_code}" -X POST "$API_BASE/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $API_KEY" \
        -d "{\"model\":\"$model\",\"messages\":[{\"role\":\"user\",\"content\":\"Count from 1 to 5.\"}],\"max_tokens\":30}" 2>/dev/null)

    local http_code
    http_code=$(echo "$response" | tail -1)
    local end_ms
    end_ms=$(date +%s%3N)
    local dur_ms=$((end_ms - start_ms))

    local status="ok"
    if [ "$http_code" != "200" ]; then
        status="fail"
    fi

    local short=""
    case "$model" in
        *7B*) short="7B" ;;
        *14B*) short="14B" ;;
        *Mistral*|*mistral*) short="M7B" ;;
    esac

    echo "$req_id,$model,$status,$dur_ms,$http_code,$ts" >> "$CSV_FILE"

    if [ "$status" = "ok" ]; then
        echo "  ✓ #$req_id $short ${dur_ms}ms"
    else
        echo "  ✗ #$req_id $short ${dur_ms}ms (HTTP $http_code)"
    fi
}

# ──────────────────────────────────────────────────────────────────────
# Run: rotate through models in bursts
# ──────────────────────────────────────────────────────────────────────

OVERALL_START=$(date +%s)
echo "━━━ Starting benchmark at $(date +%H:%M:%S) ━━━"
echo ""

declare -A model_sent
for m in "${MODELS[@]}"; do model_sent["$m"]=0; done

req_num=0
model_idx=0
all_done=false

while [ "$all_done" = "false" ]; do
    model="${MODELS[$model_idx]}"
    remaining=$((PER_MODEL - model_sent["$model"]))

    if [ "$remaining" -le 0 ]; then
        model_idx=$(( (model_idx + 1) % 3 ))
        # Check if all models are done
        all_done=true
        for m in "${MODELS[@]}"; do
            if [ "${model_sent[$m]}" -lt "$PER_MODEL" ]; then
                all_done=false
                break
            fi
        done
        continue
    fi

    burst_count=$BURST
    if [ "$burst_count" -gt "$remaining" ]; then
        burst_count=$remaining
    fi

    short=""
    case "$model" in
        *7B*) short="7B" ;;
        *14B*) short="14B" ;;
        *Mistral*|*mistral*) short="M7B" ;;
    esac
    echo "── Burst: $short ×$burst_count (${model_sent[$model]}/$PER_MODEL done) ──"

    active=0
    for _ in $(seq 1 "$burst_count"); do
        req_num=$((req_num + 1))
        model_sent["$model"]=$((model_sent["$model"] + 1))
        send_one "$req_num" "$model" &
        active=$((active + 1))

        if [ "$active" -ge "$CONCURRENCY" ]; then
            wait -n 2>/dev/null || true
            active=$((active - 1))
        fi
    done
    wait  # wait for burst to complete

    model_idx=$(( (model_idx + 1) % 3 ))
done

OVERALL_END=$(date +%s)
OVERALL_DUR=$((OVERALL_END - OVERALL_START))

# ──────────────────────────────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────────────────────────────

echo ""
echo "━━━ Benchmark Complete (${OVERALL_DUR}s) ━━━"
echo ""

python3 -c "
import csv, sys
from collections import defaultdict

rows = []
with open('$CSV_FILE') as f:
    reader = csv.DictReader(f)
    for r in reader:
        rows.append(r)

if not rows:
    print('No results!')
    sys.exit(1)

models = defaultdict(lambda: {'ok': 0, 'fail': 0, 'durations': []})
for r in rows:
    short = '14B' if '14B' in r['model'] else ('7B' if '7B' in r['model'] else 'M7B')
    models[short][r['status']] += 1
    models[short]['durations'].append(int(r['duration_ms']))

total_ok = sum(m['ok'] for m in models.values())
total_fail = sum(m['fail'] for m in models.values())
total = total_ok + total_fail

dur = $OVERALL_DUR
print(f'  Total: {total_ok} ok / {total_fail} fail / {total} total')
print(f'  Wall time: {dur}s')
if dur > 0:
    print(f'  Throughput: {total / dur:.2f} req/s')
print()

for name in sorted(models.keys()):
    m = models[name]
    durations = sorted(m['durations'])
    n = len(durations)
    if n == 0:
        continue
    p50 = durations[n // 2]
    p95 = durations[int(n * 0.95)]
    p99 = durations[int(n * 0.99)]
    avg = sum(durations) / n
    mn = min(durations)
    mx = max(durations)
    print(f'  {name:>3s}: {m[\"ok\"]:>3d} ok / {m[\"fail\"]:>3d} fail  '
          f'p50={p50:>6d}ms  p95={p95:>6d}ms  p99={p99:>6d}ms  '
          f'avg={avg:>8.0f}ms  min={mn:>6d}ms  max={mx:>6d}ms')
print()
" 2>&1

echo "  Results saved to: $CSV_FILE"
