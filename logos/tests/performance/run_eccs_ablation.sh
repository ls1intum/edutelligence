#!/usr/bin/env bash
# run_eccs_ablation.sh — Run ECCS ablation benchmark (correction on vs off)
#
# Runs the same workload twice:
#   1. ECCS enabled (ettft_enabled=True)  → decision log + benchmark CSV
#   2. ECCS disabled (ettft_enabled=False) → decision log + benchmark CSV
# Then runs the analysis script to compare.
#
# Prerequisites:
#   - Logos server running in Docker (docker compose up)
#   - API key configured
#
# Usage:
#   bash tests/performance/run_eccs_ablation.sh [OPTIONS]
#
# Options:
#   --logos-key KEY           API key (default: from API_KEY env var)
#   --workload PATH           Workload CSV (default: ablation/workload_150_burst5_gap70.csv)
#   --weight-override JSON    ECCS_WEIGHT_OVERRIDE value (default: none)
#   --weight-scenario NAME    Shorthand: tight|medium|wide (sets --weight-override)
#   --output-dir DIR          Results directory (default: tests/performance/results/ablation/)
#   --api-base URL            API base URL (default: http://localhost:8080)
#   --skip-off                Skip the ECCS-off run (only run ECCS-on)
#
# Example:
#   bash tests/performance/run_eccs_ablation.sh \
#       --logos-key YourKey \
#       --weight-scenario medium \
#       --workload tests/performance/workloads/ablation/workload_150_burst5_gap70.csv

set -euo pipefail

# Defaults
API_KEY="${API_KEY:-}"
API_BASE="${API_BASE:-http://localhost:8080}"
WORKLOAD="tests/performance/workloads/ablation/workload_150_burst5_gap70.csv"
WEIGHT_OVERRIDE=""
WEIGHT_SCENARIO=""
OUTPUT_DIR=""
SKIP_OFF=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --logos-key)      API_KEY="$2"; shift 2 ;;
        --workload)       WORKLOAD="$2"; shift 2 ;;
        --weight-override) WEIGHT_OVERRIDE="$2"; shift 2 ;;
        --weight-scenario) WEIGHT_SCENARIO="$2"; shift 2 ;;
        --output-dir)     OUTPUT_DIR="$2"; shift 2 ;;
        --api-base)       API_BASE="$2"; shift 2 ;;
        --skip-off)       SKIP_OFF=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Map weight scenario to override
if [[ -n "$WEIGHT_SCENARIO" ]]; then
    case "$WEIGHT_SCENARIO" in
        tight)  WEIGHT_OVERRIDE='{"1": 10.0, "2": 9.5, "3": 9.0}' ;;
        medium) WEIGHT_OVERRIDE='{"1": 10.0, "2": 7.0, "3": 4.0}' ;;
        wide)   WEIGHT_OVERRIDE='{"1": 10.0, "2": 2.0, "3": 1.0}' ;;
        *) echo "Unknown weight scenario: $WEIGHT_SCENARIO (use tight/medium/wide)"; exit 1 ;;
    esac
fi

if [[ -z "$API_KEY" ]]; then
    echo "Error: --logos-key or API_KEY env var required"
    exit 1
fi

# Determine output directory
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
WORKLOAD_NAME=$(basename "$WORKLOAD" .csv)
SCENARIO_SUFFIX="${WEIGHT_SCENARIO:-custom}"
if [[ -z "$OUTPUT_DIR" ]]; then
    OUTPUT_DIR="tests/performance/results/ablation/${WORKLOAD_NAME}_${SCENARIO_SUFFIX}_${TIMESTAMP}"
fi

ECCS_ON_DIR="$OUTPUT_DIR/eccs_on"
ECCS_OFF_DIR="$OUTPUT_DIR/eccs_off"
mkdir -p "$ECCS_ON_DIR" "$ECCS_OFF_DIR"

echo "================================================================"
echo "  ECCS Ablation Benchmark"
echo "================================================================"
echo ""
echo "  Workload:          $WORKLOAD"
echo "  Weight scenario:   ${WEIGHT_SCENARIO:-none}"
echo "  Weight override:   ${WEIGHT_OVERRIDE:-none}"
echo "  Output:            $OUTPUT_DIR"
echo "  API:               $API_BASE"
echo ""

# ── Run 1: ECCS On ──────────────────────────────────────────────────

echo "────────────────────────────────────────────────────────────────"
echo "  Run 1: ECCS ENABLED"
echo "────────────────────────────────────────────────────────────────"

ECCS_ON_ENV=""
if [[ -n "$WEIGHT_OVERRIDE" ]]; then
    ECCS_ON_ENV="ECCS_WEIGHT_OVERRIDE=$WEIGHT_OVERRIDE"
fi

docker compose exec \
    -e "ECCS_DECISION_LOG=/tmp/eccs_decisions_on.jsonl" \
    ${ECCS_ON_ENV:+-e "$ECCS_ON_ENV"} \
    logos-server \
    poetry run python tests/performance/run_api_workload.py \
        --logos-key "$API_KEY" \
        --workload "$WORKLOAD" \
        --api-base "$API_BASE" \
        --output "$ECCS_ON_DIR/detailed.csv"

# Copy decision log from container
docker compose cp logos-server:/tmp/eccs_decisions_on.jsonl "$ECCS_ON_DIR/decisions.jsonl" 2>/dev/null || true

echo ""
echo "  ECCS ON results saved to $ECCS_ON_DIR"

# ── Run 2: ECCS Off ─────────────────────────────────────────────────

if [[ "$SKIP_OFF" != true ]]; then
    echo ""
    echo "  Waiting 60s between runs for model state to normalize..."
    sleep 60

    echo "────────────────────────────────────────────────────────────────"
    echo "  Run 2: ECCS DISABLED"
    echo "────────────────────────────────────────────────────────────────"

    ECCS_OFF_ENV="ECCS_ETTFT_ENABLED=false"
    if [[ -n "$WEIGHT_OVERRIDE" ]]; then
        ECCS_OFF_ENV="$ECCS_OFF_ENV ECCS_WEIGHT_OVERRIDE=$WEIGHT_OVERRIDE"
    fi

    docker compose exec \
        -e "ECCS_DECISION_LOG=/tmp/eccs_decisions_off.jsonl" \
        -e "ECCS_ETTFT_ENABLED=false" \
        ${WEIGHT_OVERRIDE:+-e "ECCS_WEIGHT_OVERRIDE=$WEIGHT_OVERRIDE"} \
        logos-server \
        poetry run python tests/performance/run_api_workload.py \
            --logos-key "$API_KEY" \
            --workload "$WORKLOAD" \
            --api-base "$API_BASE" \
            --output "$ECCS_OFF_DIR/detailed.csv"

    docker compose cp logos-server:/tmp/eccs_decisions_off.jsonl "$ECCS_OFF_DIR/decisions.jsonl" 2>/dev/null || true

    echo ""
    echo "  ECCS OFF results saved to $ECCS_OFF_DIR"
fi

# ── Analysis ─────────────────────────────────────────────────────────

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  ANALYSIS"
echo "════════════════════════════════════════════════════════════════"

ANALYSIS_ARGS=(
    --decision-log "$ECCS_ON_DIR/decisions.jsonl"
    --export-csv "$OUTPUT_DIR/summary.csv"
)

if [[ -f "$ECCS_ON_DIR/detailed.csv" ]]; then
    ANALYSIS_ARGS+=(--benchmark-csv "$ECCS_ON_DIR/detailed.csv")
fi

if [[ "$SKIP_OFF" != true ]] && [[ -f "$ECCS_OFF_DIR/decisions.jsonl" ]]; then
    ANALYSIS_ARGS+=(--baseline-log "$ECCS_OFF_DIR/decisions.jsonl")
    if [[ -f "$ECCS_OFF_DIR/detailed.csv" ]]; then
        ANALYSIS_ARGS+=(--baseline-csv "$ECCS_OFF_DIR/detailed.csv")
    fi
fi

python3 tests/performance/analyze_eccs_ablation.py "${ANALYSIS_ARGS[@]}"

echo ""
echo "  Full results in: $OUTPUT_DIR"
