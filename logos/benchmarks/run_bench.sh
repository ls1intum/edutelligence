#!/usr/bin/env bash
#
# Logos GSM8K benchmark runner — repository-tracked, NO secrets.
#
# Two steps:
#   1. Regenerate the GSM8K workload CSVs (the FULL test split by default —
#      all 1319 examples, not a 20-request sample).
#   2. Run benchmark_logos.py --run-all-scenarios against them.
#
# Secrets and host-specific values come from the ENVIRONMENT (or a local,
# git-ignored env file) — never hard-code a key or URL in this file.
#
# On the benchmark host (e.g. logos-test) keep them in a git-ignored file such
# as /root/bench-secrets.env and run:
#
#     cd /opt/edutelligence && git pull            # read-only, public repo
#     set -a; . /root/bench-secrets.env; set +a    # load LOGOS_KEY etc.
#     logos/benchmarks/run_bench.sh
#
# ── Environment variables ───────────────────────────────────────────────────
# Required (unless ONLY_OLLAMA=1):
#   LOGOS_KEY                 Logos API key (lg-...).
#
# Optional (defaults shown):
#   LOGOS_URL=https://logos-test.aet.cit.tum.de
#   GPU_HOSTS="deipapa.ase.cit.tum.de deimama.aet.cit.tum.de"   (space-separated)
#   GPU_SSH_USER=logos-server
#   WORKLOAD=workloads/workload_gsm8k_5llm.csv
#   PYTHON=python3            (host wrapper sets e.g. /root/bench-venv/bin/python)
#
#   # Workload generation (prepare_benchmark.py):
#   GSM8K_SPLIT=test          (test = 1319 examples, train = 7473)
#   GSM8K_RPS=1.0             arrival rate; 0 = all offsets 0
#   NUM_SAMPLES=              empty = ALL examples (the whole dataset); set to cap
#   SKIP_PREPARE=0            1 = reuse existing workload CSVs, skip generation
#
#   # Calibration (expensive — re-downloads all weights, hours):
#   RESET_CALIBRATION=0       1 = wipe + recalibrate all nodes before running
#   CALIBRATION_PROVIDER_IDS="3 2"   provider IDs (deipapa deimama); needed if reset
#
#   # Energy measurement:
#   SHELLY=0                  1 = ALSO measure wall power via the Shelly plug
#                             (additive to GPU/nvidia-smi → energy_gpu_j AND
#                             energy_wall_j per request; needs shelly_daemon.py on the Pi)
#   SHELLY_PORT=9876          port the Pi pushes readings to (udp/tcp only)
#   SHELLY_TRANSPORT=http     udp|tcp|http; must match shelly_daemon.py. http is
#                             the default here: the campus firewall only passes
#                             443, so the pipeline starts a Traefik-routed ingest
#                             sidecar and the Pi daemon POSTs to it over HTTPS.
#   SHELLY_INGEST_IMAGE=python:3-alpine   docker image for the http ingest sidecar
#
#   # Misc:
#   BENCHMARK_LOCAL_CACHE=    redirect OLLAMA_MODELS_MOUNT on GPU nodes (e.g. NVMe)
#   ONLY_OLLAMA=0             1 = only the Ollama scenario (no LOGOS_KEY needed)
#   REQUEST_TIMEOUT_S=1800    per-request client timeout (large models like the 35B
#                             need >600s or they fail with ReadTimeout)
#   EXTRA_ARGS=               extra flags appended verbatim to benchmark_logos.py
#
set -euo pipefail

# Run from this script's directory so workloads/ and benchmark_results/ resolve.
cd "$(dirname "$(readlink -f "$0")")"

# ── Defaults ────────────────────────────────────────────────────────────────
LOGOS_URL="${LOGOS_URL:-https://logos-test.aet.cit.tum.de}"
GPU_HOSTS="${GPU_HOSTS:-deipapa.ase.cit.tum.de deimama.aet.cit.tum.de}"
GPU_SSH_USER="${GPU_SSH_USER:-logos-server}"
WORKLOAD="${WORKLOAD:-workloads/workload_gsm8k_5llm.csv}"
PYTHON="${PYTHON:-python3}"

GSM8K_SPLIT="${GSM8K_SPLIT:-test}"
GSM8K_RPS="${GSM8K_RPS:-1.0}"
NUM_SAMPLES="${NUM_SAMPLES:-}"
SKIP_PREPARE="${SKIP_PREPARE:-0}"

RESET_CALIBRATION="${RESET_CALIBRATION:-0}"
CALIBRATION_PROVIDER_IDS="${CALIBRATION_PROVIDER_IDS:-3 2}"
BENCHMARK_LOCAL_CACHE="${BENCHMARK_LOCAL_CACHE:-}"
ONLY_OLLAMA="${ONLY_OLLAMA:-0}"
SHELLY="${SHELLY:-0}"
SHELLY_PORT="${SHELLY_PORT:-9876}"
SHELLY_TRANSPORT="${SHELLY_TRANSPORT:-http}"
SHELLY_INGEST_IMAGE="${SHELLY_INGEST_IMAGE:-python:3-alpine}"
REQUEST_TIMEOUT_S="${REQUEST_TIMEOUT_S:-1800}"
EXTRA_ARGS="${EXTRA_ARGS:-}"
LOGOS_KEY="${LOGOS_KEY:-}"

if [[ "$ONLY_OLLAMA" != "1" && -z "$LOGOS_KEY" ]]; then
  echo "[run_bench] ERROR: LOGOS_KEY is required (or set ONLY_OLLAMA=1)." >&2
  echo "[run_bench]        Load it from a git-ignored env file, e.g.:" >&2
  echo "[run_bench]        set -a; . /root/bench-secrets.env; set +a" >&2
  exit 1
fi

LOG="bench-$(date +%Y%m%d-%H%M%S).log"
echo "[run_bench] starting, log=$LOG"

# ── Step 1: regenerate the workload (full GSM8K split unless NUM_SAMPLES set) ──
if [[ "$SKIP_PREPARE" == "1" ]]; then
  echo "[run_bench] SKIP_PREPARE=1 — reusing existing workload CSVs."
else
  echo "[run_bench] Preparing GSM8K workload (split=$GSM8K_SPLIT rps=$GSM8K_RPS" \
       "num_samples=${NUM_SAMPLES:-ALL}) ..."
  prepare_args=(--split "$GSM8K_SPLIT" --rps "$GSM8K_RPS")
  [[ -n "$NUM_SAMPLES" ]] && prepare_args+=(--num-samples "$NUM_SAMPLES")
  "$PYTHON" -u prepare_benchmark.py "${prepare_args[@]}"
fi

# ── Step 2: run the benchmark ─────────────────────────────────────────────────
bench_args=(
  --run-all-scenarios
  --logos-url "$LOGOS_URL"
  --workload "$WORKLOAD"
  --gpu-host $GPU_HOSTS
  --gpu-ssh-user "$GPU_SSH_USER"
  --request-timeout-s "$REQUEST_TIMEOUT_S"
)
[[ -n "$LOGOS_KEY" ]] && bench_args+=(--logos-key "$LOGOS_KEY")
[[ "$ONLY_OLLAMA" == "1" ]] && bench_args+=(--only-ollama)
[[ "$SHELLY" == "1" ]] && bench_args+=(--shelly --shelly-port "$SHELLY_PORT" --shelly-transport "$SHELLY_TRANSPORT" --shelly-ingest-image "$SHELLY_INGEST_IMAGE")
[[ "$RESET_CALIBRATION" == "1" ]] && bench_args+=(--reset-calibration --calibration-provider-ids $CALIBRATION_PROVIDER_IDS)
[[ -n "$BENCHMARK_LOCAL_CACHE" ]] && bench_args+=(--benchmark-local-cache "$BENCHMARK_LOCAL_CACHE")
# shellcheck disable=SC2206
[[ -n "$EXTRA_ARGS" ]] && bench_args+=($EXTRA_ARGS)

"$PYTHON" -u benchmark_logos.py "${bench_args[@]}" 2>&1 | tee "$LOG"
rc=${PIPESTATUS[0]}
echo "[run_bench] benchmark exited rc=$rc (log=$LOG)"
exit "$rc"
