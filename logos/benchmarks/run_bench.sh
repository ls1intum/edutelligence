#!/usr/bin/env bash
#
# AnonTool GSM8K benchmark runner — repository-tracked, NO secrets.
#
# Two steps:
#   1. Regenerate the GSM8K workload CSVs (1000 requests at 0.5 req/s by
#      default — one shared load level across all scenarios).
#   2. Run benchmark_anontool.py --run-all-scenarios against them.
#
# Secrets and host-specific values come from the ENVIRONMENT (or a local,
# git-ignored env file) — never hard-code a key or URL in this file.
#
# On the benchmark host (e.g. anontool-test) keep them in a git-ignored file such
# as /root/bench-secrets.env and run:
#
#     cd /opt/edutelligence && git pull            # read-only, public repo
#     set -a; . /root/bench-secrets.env; set +a    # load ANONTOOL_KEY etc.
#     anontool/benchmarks/run_bench.sh
#
# ── Environment variables ───────────────────────────────────────────────────
# Required (unless ONLY_OLLAMA=1):
#   ANONTOOL_KEY                 AnonTool API key (lg-...).
#
# Optional (defaults shown):
#   ANONTOOL_URL=https://anontool-test.example.com
#   GPU_HOSTS="gpu-node-a.example.com gpu-node-b.example.com"   (space-separated)
#   GPU_SSH_USER=anontool-server
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
#   CALIBRATION_PROVIDER_IDS="3 2"   provider IDs (gpu-node-a gpu-node-b); needed if reset
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
#   ONLY_OLLAMA=0             1 = only the Ollama scenario (no ANONTOOL_KEY needed)
#   REQUEST_TIMEOUT_S=1800    per-request client timeout (large models like the 35B
#                             need >600s or they fail with ReadTimeout)
#   MANAGE_CALIB_WINDOW=1     1 = disable the orchestrator's nightly calibration
#                             window for the run (so it can't fire mid-benchmark)
#                             and restore it after; 0 = leave it as deployed
#   EXTRA_ARGS=               extra flags appended verbatim to benchmark_anontool.py
#
set -euo pipefail

# Run from this script's directory so workloads/ and benchmark_results/ resolve.
cd "$(dirname "$(readlink -f "$0")")"

# ── Defaults ────────────────────────────────────────────────────────────────
ANONTOOL_URL="${ANONTOOL_URL:-https://anontool-test.example.com}"
GPU_HOSTS="${GPU_HOSTS:-gpu-node-a.example.com gpu-node-b.example.com}"
GPU_SSH_USER="${GPU_SSH_USER:-anontool-server}"
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
# Pre-dispatch settle (seconds): with warmup skipped, wait this long after each
# scenario starts before the first request, so the planner reacts before a fully
# cold system is hit. Defaults to 20s when warmup is skipped, else 0.
if [[ "$SKIP_WARMUP" == "1" ]]; then
  SETTLE_DELAY_S="${SETTLE_DELAY_S:-20}"
else
  SETTLE_DELAY_S="${SETTLE_DELAY_S:-0}"
fi

RESET_CALIBRATION="${RESET_CALIBRATION:-0}"
CALIBRATION_PROVIDER_IDS="${CALIBRATION_PROVIDER_IDS:-3 2}"
# SKIP_CALIBRATION=1 runs against the existing profiles as-is: no reset and no
# ensure-calibrate (passes --skip-calibration). Provider IDs are STILL forwarded
# so the lane-state poller fills model_timeline.csv — calibration and timeline
# data are independent. Useful for a fast run when models are already loadable.
SKIP_CALIBRATION="${SKIP_CALIBRATION:-0}"
BENCHMARK_LOCAL_CACHE="${BENCHMARK_LOCAL_CACHE:-}"
ONLY_OLLAMA="${ONLY_OLLAMA:-0}"
MANAGE_CALIB_WINDOW="${MANAGE_CALIB_WINDOW:-1}"
SHELLY="${SHELLY:-0}"
SHELLY_PORT="${SHELLY_PORT:-9876}"
SHELLY_TRANSPORT="${SHELLY_TRANSPORT:-http}"
SHELLY_INGEST_IMAGE="${SHELLY_INGEST_IMAGE:-python:3-alpine}"
# Global request-lifecycle timeout (seconds): ONE knob shared by the benchmark
# client and the orchestrator (ANONTOOL_TIMEOUT_S in the orchestrator/worker env).
# Default 86400 (24 h ~= "never"): under open-loop, requests to a slow/saturated
# model queue for a long time — we want that to show up as high TTFT/TTLT, NOT
# as client ReadTimeout errors. (The previous default of 1800 s caused ~28% of
# Qwen/Phi requests to ReadTimeout-starve under burst.) Overload = latency here,
# not errors.
ANONTOOL_TIMEOUT_S="${ANONTOOL_TIMEOUT_S:-86400}"
export ANONTOOL_TIMEOUT_S
# Hard drain cap (seconds): after the LAST request of each pattern is fired, the
# benchmark waits at most this long for in-flight requests to finish, then
# abandons the stragglers (counted as errors). Default 1800 = 30 min: a HANG
# safety net. Without it (0 = disabled) a single wedged/half-open request — e.g. a
# stream the worker dropped mid-response on a model swap — blocks the whole
# pattern until the per-request timeout (hours), deadlocking the run. Legit
# requests, even with a cold load (~8 min) or KServe scale-from-zero under
# contention, finish well within 30 min; only genuinely-stuck ones are abandoned.
# Set 0 to disable (wait for ALL in-flight) only if you are sure no lane can wedge.
ANONTOOL_BENCH_DRAIN_CAP_S="${ANONTOOL_BENCH_DRAIN_CAP_S:-1800}"
export ANONTOOL_BENCH_DRAIN_CAP_S
# When the global knob is set it also drives the client request timeout (unless
# REQUEST_TIMEOUT_S is set explicitly).
REQUEST_TIMEOUT_S="${REQUEST_TIMEOUT_S:-${ANONTOOL_TIMEOUT_S:-1800}}"
# Quick-debug subsetting (empty = all). E.g. SCENARIOS=anontool-nosleep PATTERNS=mixed.
SCENARIOS="${SCENARIOS:-}"
PATTERNS="${PATTERNS:-}"
EXTRA_ARGS="${EXTRA_ARGS:-}"
ANONTOOL_KEY="${ANONTOOL_KEY:-}"

if [[ "$ONLY_OLLAMA" != "1" && -z "$ANONTOOL_KEY" ]]; then
  echo "[run_bench] ERROR: ANONTOOL_KEY is required (or set ONLY_OLLAMA=1)." >&2
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
  --anontool-url "$ANONTOOL_URL"
  --workload "$WORKLOAD"
  --gpu-host $GPU_HOSTS
  --gpu-ssh-user "$GPU_SSH_USER"
  --request-timeout-s "$REQUEST_TIMEOUT_S"
  --seed "$SEED"
  --rps "$GSM8K_RPS"
  --settle-delay-s "$SETTLE_DELAY_S"
)
[[ -n "$ANONTOOL_KEY" ]] && bench_args+=(--anontool-key "$ANONTOOL_KEY")
# Quick-debug subsetting: SCENARIOS=anontool-nosleep PATTERNS=mixed runs just that
# scenario/pattern. Empty = all scenarios / all 4 patterns.
[[ -n "$SCENARIOS" ]] && bench_args+=(--scenarios "$SCENARIOS")
[[ -n "$PATTERNS" ]] && bench_args+=(--patterns "$PATTERNS")
[[ "$SKIP_WARMUP" == "1" ]] && bench_args+=(--skip-warmup)
[[ "$ONLY_OLLAMA" == "1" ]] && bench_args+=(--only-ollama)
[[ "$MANAGE_CALIB_WINDOW" == "0" ]] && bench_args+=(--no-manage-calibration-window)
[[ "$SHELLY" == "1" ]] && bench_args+=(--shelly --shelly-port "$SHELLY_PORT" --shelly-transport "$SHELLY_TRANSPORT" --shelly-ingest-image "$SHELLY_INGEST_IMAGE")
# Provider IDs are ALWAYS forwarded — they feed the live lane-state poller that
# fills model_timeline.csv, which is independent of calibration. (They are also
# used by --reset-calibration / ensure-calibrate when those run.) Split the
# space-separated list into a proper array so word boundaries are explicit and no
# glob expansion can sneak in.
if [[ -n "$CALIBRATION_PROVIDER_IDS" ]]; then
  read -ra _calib_provider_ids <<< "$CALIBRATION_PROVIDER_IDS"
  bench_args+=(--calibration-provider-ids "${_calib_provider_ids[@]}")
fi
# SKIP_CALIBRATION only gates the calibration step itself — NOT the lane poller.
[[ "$SKIP_CALIBRATION" == "1" ]] && bench_args+=(--skip-calibration)
[[ "$RESET_CALIBRATION" == "1" && "$SKIP_CALIBRATION" != "1" ]] && bench_args+=(--reset-calibration)
[[ -n "$BENCHMARK_LOCAL_CACHE" ]] && bench_args+=(--benchmark-local-cache "$BENCHMARK_LOCAL_CACHE")
# shellcheck disable=SC2206
[[ -n "$EXTRA_ARGS" ]] && bench_args+=($EXTRA_ARGS)

"$PYTHON" -u benchmark_anontool.py "${bench_args[@]}" 2>&1 | tee "$LOG"
rc=${PIPESTATUS[0]}
echo "[run_bench] benchmark exited rc=$rc (log=$LOG)"
exit "$rc"
