#!/usr/bin/env bash
#
# run_loop.sh — Repeatedly run the benchmark, drawing a FRESH RANDOM SEED each
# iteration. The seed is passed to run_bench.sh (→ benchmark_anontool.py --seed)
# and recorded in every run's run_meta.json ("seed" / "workload_seed"), so each
# loop's raw output is reproducible and self-identifying.
#
# Intended for an unattended (e.g. overnight) sweep on a small workload.
#
# Environment:
#   ITERS         number of iterations; 0 = loop until killed   (default: 0)
#   NUM_SAMPLES   requests per run                               (default: 100)
#   plus every knob run_bench.sh understands (SCENARIOS, PATTERNS, ANONTOOL_URL,
#   ANONTOOL_KEY, GPU_HOSTS, GPU_SSH_USER, SKIP_CALIBRATION, SHELLY, ...).
#
# Example (small overnight sweep, all scenarios/patterns, 100 requests):
#   ITERS=0 NUM_SAMPLES=100 SKIP_CALIBRATION=1 \
#   SCENARIOS="anontool-nosleep,anontool-sleep,ray,kserve" \
#     ./run_loop.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ITERS="${ITERS:-0}"
export NUM_SAMPLES="${NUM_SAMPLES:-100}"

new_seed() {
  # 31-bit seed: prefer urandom, fall back to bash RANDOM.
  if command -v od >/dev/null 2>&1; then
    echo $(( $(od -An -N4 -tu4 /dev/urandom | tr -d ' ') % 2147483647 ))
  else
    echo $(( (RANDOM << 15 | RANDOM) % 2147483647 ))
  fi
}

i=0
while [[ "$ITERS" -eq 0 || "$i" -lt "$ITERS" ]]; do
  i=$((i + 1))
  SEED_VAL="$(new_seed)"
  echo ">> [$(date -u +%FT%TZ)] iteration ${i} — seed=${SEED_VAL}, NUM_SAMPLES=${NUM_SAMPLES}"
  SEED="${SEED_VAL}" "${HERE}/run_bench.sh" || echo ">> iteration ${i} failed (seed=${SEED_VAL}) — continuing"
done
