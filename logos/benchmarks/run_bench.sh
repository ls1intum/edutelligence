#!/usr/bin/env bash
#
# Logos GSM8K benchmark runner — repository-tracked, NO secrets.
#
# Two steps:
#   1. Regenerate the GSM8K workload CSVs (1000 requests at 0.5 req/s by
#      default — one shared load level across all scenarios).
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
#   GSM8K_SPLIT=all           test=1319, train=7473, all=train+test (8792)
#   GSM8K_RPS=0.5             single arrival rate for ALL scenarios; 0 = all offsets 0
#   NUM_SAMPLES=1000          total requests; empty/0 = ALL examples in the split
#   SEED=42                   reproducibility seed (assignment + traffic timing)
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
#   MANAGE_CALIB_WINDOW=1     1 = disable the orchestrator's nightly calibration
#                             window for the run (so it can't fire mid-benchmark)
#                             and restore it after; 0 = leave it as deployed
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

GSM8K_SPLIT="${GSM8K_SPLIT:-all}"
# Single shared load level for ALL scenarios (open-loop — fire on the arrival
# schedule regardless of completion, so scenarios stay comparable). The big slow
# models (Qwen35B ~0.02 req/s, Phi-4-reasoning) cap sustainable throughput, so
# 0.3 req/s keeps queues from diverging too hard; overload shows up as latency,
# NOT as errors, because the per-request timeout is effectively disabled below.
# Override GSM8K_RPS / NUM_SAMPLES to sweep the load level.
GSM8K_RPS="${GSM8K_RPS:-0.3}"
NUM_SAMPLES="${NUM_SAMPLES:-1000}"
# Seed for reproducibility: drives the request→model assignment (prepare) and
# the poisson/mixed traffic timing (benchmark). Same seed → identical run.
SEED="${SEED:-42}"
SKIP_PREPARE="${SKIP_PREPARE:-0}"
# Skip BOTH the per-node pre-fetch cycling and the per-scenario warmup (fast
# iteration — models cold-load on first real request instead). 1 = skip.
SKIP_WARMUP="${SKIP_WARMUP:-0}"

RESET_CALIBRATION="${RESET_CALIBRATION:-0}"
CALIBRATION_PROVIDER_IDS="${CALIBRATION_PROVIDER_IDS:-3 2}"
# SKIP_CALIBRATION=1 runs against the existing profiles as-is: no reset and no
# ensure-calibrate (the run won't pass --calibration-provider-ids, so incomplete
# profiles are served as-is rather than triggering a calibration session). Useful
# for a fast debug run when models are already loadable.
SKIP_CALIBRATION="${SKIP_CALIBRATION:-0}"
BENCHMARK_LOCAL_CACHE="${BENCHMARK_LOCAL_CACHE:-}"
ONLY_OLLAMA="${ONLY_OLLAMA:-0}"
MANAGE_CALIB_WINDOW="${MANAGE_CALIB_WINDOW:-1}"
SHELLY="${SHELLY:-0}"
SHELLY_PORT="${SHELLY_PORT:-9876}"
SHELLY_TRANSPORT="${SHELLY_TRANSPORT:-http}"
SHELLY_INGEST_IMAGE="${SHELLY_INGEST_IMAGE:-python:3-alpine}"
# Global request-lifecycle timeout (seconds): ONE knob shared by the benchmark
# client and the orchestrator (LOGOS_TIMEOUT_S in the orchestrator/worker env).
# Default 86400 (24 h ~= "never"): under open-loop, requests to a slow/saturated
# model queue for a long time — we want that to show up as high TTFT/TTLT, NOT
# as client ReadTimeout errors. (The previous default of 1800 s caused ~28% of
# Qwen/Phi requests to ReadTimeout-starve under burst.) Overload = latency here,
# not errors.
LOGOS_TIMEOUT_S="${LOGOS_TIMEOUT_S:-86400}"
export LOGOS_TIMEOUT_S
# Hard drain cap (seconds): after the LAST request of each pattern is fired, the
# benchmark waits at most this long for in-flight requests to finish, then
# abandons the stragglers (counted as errors). Default 0 = DISABLED (wait for ALL
# in-flight to complete) so a deep-but-draining queue never produces abandonment
# errors — required for the 0-error goal. The placement/sleep fixes prevent lanes
# from wedging, so full drain terminates; set a positive value if you want a
# hang-safety net at the cost of possible abandonment errors on a genuine wedge.
LOGOS_BENCH_DRAIN_CAP_S="${LOGOS_BENCH_DRAIN_CAP_S:-0}"
export LOGOS_BENCH_DRAIN_CAP_S
# When the global knob is set it also drives the client request timeout (unless
# REQUEST_TIMEOUT_S is set explicitly).
REQUEST_TIMEOUT_S="${REQUEST_TIMEOUT_S:-${LOGOS_TIMEOUT_S:-1800}}"
# Quick-debug subsetting (empty = all). E.g. SCENARIOS=logos-nosleep PATTERNS=mixed.
SCENARIOS="${SCENARIOS:-}"
PATTERNS="${PATTERNS:-}"
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
  prepare_args=(--split "$GSM8K_SPLIT" --rps "$GSM8K_RPS" --seed "$SEED")
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
  --seed "$SEED"
)
[[ -n "$LOGOS_KEY" ]] && bench_args+=(--logos-key "$LOGOS_KEY")
# Quick-debug subsetting: SCENARIOS=logos-nosleep PATTERNS=mixed runs just that
# scenario/pattern. Empty = all scenarios / all 4 patterns.
[[ -n "$SCENARIOS" ]] && bench_args+=(--scenarios "$SCENARIOS")
[[ -n "$PATTERNS" ]] && bench_args+=(--patterns "$PATTERNS")
[[ "$SKIP_WARMUP" == "1" ]] && bench_args+=(--skip-warmup)
[[ "$ONLY_OLLAMA" == "1" ]] && bench_args+=(--only-ollama)
[[ "$MANAGE_CALIB_WINDOW" == "0" ]] && bench_args+=(--no-manage-calibration-window)
[[ "$SHELLY" == "1" ]] && bench_args+=(--shelly --shelly-port "$SHELLY_PORT" --shelly-transport "$SHELLY_TRANSPORT" --shelly-ingest-image "$SHELLY_INGEST_IMAGE")
# Provider IDs are needed whether or not we reset: without a full reset the run
# still triggers calibration for any model the worker never calibrated. Split the
# space-separated list into a proper array so word boundaries are explicit and no
# glob expansion can sneak in.
if [[ -n "$CALIBRATION_PROVIDER_IDS" && "$SKIP_CALIBRATION" != "1" ]]; then
  read -ra _calib_provider_ids <<< "$CALIBRATION_PROVIDER_IDS"
  bench_args+=(--calibration-provider-ids "${_calib_provider_ids[@]}")
fi
[[ "$RESET_CALIBRATION" == "1" && "$SKIP_CALIBRATION" != "1" ]] && bench_args+=(--reset-calibration)
[[ -n "$BENCHMARK_LOCAL_CACHE" ]] && bench_args+=(--benchmark-local-cache "$BENCHMARK_LOCAL_CACHE")
# shellcheck disable=SC2206
[[ -n "$EXTRA_ARGS" ]] && bench_args+=($EXTRA_ARGS)

"$PYTHON" -u benchmark_logos.py "${bench_args[@]}" 2>&1 | tee "$LOG"
rc=${PIPESTATUS[0]}
echo "[run_bench] benchmark exited rc=$rc (log=$LOG)"
exit "$rc"
