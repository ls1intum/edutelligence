#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────
# Run the full Ollama benchmark suite: 150, 300, 600 requests over 10 min.
#
# Each run starts COLD (all models unloaded from GPU).
# Uses the same hw3 workload CSVs as the vLLM/Logos benchmarks.
# Results are stored under tests/performance/results_ollama/.
#
# Usage:
#   cd logos/
#   bash tests/performance/run_ollama_benchmark_suite.sh [--ollama-base URL]
#
# Prerequisites:
#   pip install httpx matplotlib numpy   (if not already available)
#   Ollama must be running (e.g. `ollama serve` or via Docker)
# ──────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

OLLAMA_BASE="${1:-http://localhost:11434}"
OVERHEAD_MS=500
SLO_MS=10000
TIMEOUT_S=1200

WORKLOADS=(
    "tests/performance/workloads/explicit/10m/workload_explicit_hw3_even_random_150_10m.csv"
    "tests/performance/workloads/explicit/10m/workload_explicit_hw3_even_random_300_10m.csv"
    "tests/performance/workloads/explicit/10m/workload_explicit_hw3_even_random_600_10m.csv"
)

OUTPUT_DIRS=(
    "tests/performance/results_ollama/hw3_random_10m_150req"
    "tests/performance/results_ollama/hw3_random_10m_300req"
    "tests/performance/results_ollama/hw3_random_10m_600req"
)

echo "============================================"
echo " Ollama Benchmark Suite"
echo " Base URL:  $OLLAMA_BASE"
echo " Overhead:  ${OVERHEAD_MS}ms"
echo " SLO:       ${SLO_MS}ms"
echo "============================================"
echo ""

# Check Ollama is reachable
if ! curl -sf "$OLLAMA_BASE/api/tags" > /dev/null 2>&1; then
    echo "ERROR: Cannot reach Ollama at $OLLAMA_BASE"
    echo "Start Ollama first:  ollama serve"
    exit 1
fi

for i in "${!WORKLOADS[@]}"; do
    workload="${WORKLOADS[$i]}"
    output_dir="${OUTPUT_DIRS[$i]}"

    if [ ! -f "$workload" ]; then
        echo "ERROR: Workload file not found: $workload"
        exit 1
    fi

    req_count=$(tail -n +2 "$workload" | wc -l)
    echo ""
    echo "────────────────────────────────────────────"
    echo " Run $((i+1))/${#WORKLOADS[@]}: $req_count requests"
    echo " Workload: $workload"
    echo " Output:   $output_dir"
    echo "────────────────────────────────────────────"
    echo ""

    python3 tests/performance/run_ollama_benchmark.py \
        --workload "$workload" \
        --ollama-base "$OLLAMA_BASE" \
        --output-dir "$output_dir" \
        --overhead-ms "$OVERHEAD_MS" \
        --latency-slo-ms "$SLO_MS" \
        --request-timeout-s "$TIMEOUT_S"

    echo ""
    echo " Run $((i+1)) complete."
    echo ""

    # Brief pause between runs to let GPU memory settle
    if [ $i -lt $((${#WORKLOADS[@]} - 1)) ]; then
        echo "Waiting 10s before next run..."
        sleep 10
    fi
done

echo ""
echo "============================================"
echo " All benchmark runs complete!"
echo " Results in: tests/performance/results_ollama/"
echo "============================================"
