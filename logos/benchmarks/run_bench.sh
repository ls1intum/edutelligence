#!/usr/bin/env bash
#
# Logos GSM8K benchmark runner — repository-tracked, NO secrets.
#
# Runs a replicated campaign: for each arrival rate in RATES and each
# replicate 1..REPLICATES it
#   1. Regenerates the GSM8K workload CSVs (NUM_SAMPLES=1000 requests per
#      cell) with a fresh per-replicate seed (SEED + replicate - 1). The seed
#      is shared identically across all scenarios/patterns within a replicate,
#      so configurations stay paired/blocked.
#   2. Runs benchmark_logos.py --run-all-scenarios against them, writing
#      results to benchmark_results/rate_<rate>/rep<NN>_seed<seed>/.
#
# Campaign sizing (evaluation-campaign plan, T1-a / T1-b):
#   Core (defaults):  4 configs × 4 profiles × 1,000 req × R=5
#                     = 80 runs / 80,000 requests at the single core rate.
#   Load sweep:       RATES="0.05 0.1 0.2 0.3 0.5 0.8 1.2 2.0" adds the ×8
#                     rate axis → 640 runs / 640,000 requests fully crossed.
#                     The plan recommends the FULL sweep only at Poisson+burst
#                     (PATTERNS=poisson,burst) with sequential/mixed at 3
#                     anchor rates — subset via RATES/PATTERNS accordingly.
#   Near-knee cells:  use R=8–10 only for high-variance near-knee baseline
#                     cells, e.g. REPLICATE_START=6 REPLICATES=10
#                     SCENARIOS=kserve,ray RATES="<knee rates>" extends an
#                     existing R=5 campaign without re-running replicates 1–5
#                     (seeds stay aligned: replicate i always uses SEED+i-1).
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
#   # Campaign (replication + load sweep):
#   RATES="$GSM8K_RPS"        space-separated arrival rates (req/s); the whole
#                             scenario×pattern×replicate block runs once per rate.
#                             Load sweep: RATES="0.05 0.1 0.2 0.3 0.5 0.8 1.2 2.0"
#   REPLICATES=5              independent replicated runs (R) per rate. Default 5;
#                             use 8-10 only for high-variance near-knee baseline cells.
#   REPLICATE_START=1         first replicate index; >1 extends a finished campaign
#                             (e.g. =6 with REPLICATES=10 adds replicates 6-10)
#
#   # Workload generation (prepare_benchmark.py):
#   GSM8K_SPLIT=all           test=1319, train=7473, all=train+test (8792)
#   GSM8K_RPS=0.3             core arrival rate; used when RATES is unset; 0 = all offsets 0
#   NUM_SAMPLES=1000          requests per cell (N; keep 1000 — 200 would be
#                             transient-dominated and too thin for tail claims)
#   SEED=42                   base seed; replicate i uses SEED+i-1 (assignment + timing)
#   SKIP_PREPARE=0            1 = reuse existing workload CSVs, skip generation
#                             (WARNING: forces all replicates onto the same workload)
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
# Base seed for reproducibility: replicate i runs with SEED+i-1, which drives
# BOTH the request→model assignment (prepare) and the poisson/mixed traffic
# timing (benchmark). Same seed → identical run; the per-replicate seed is
# shared across all scenarios/patterns so configurations stay paired.
SEED="${SEED:-42}"
SKIP_PREPARE="${SKIP_PREPARE:-0}"
# Campaign axes: arrival rates to sweep (T1-b) and replicated runs per rate
# (T1-a). Defaults = core campaign: single rate, R=5.
RATES="${RATES:-$GSM8K_RPS}"
REPLICATES="${REPLICATES:-5}"
REPLICATE_START="${REPLICATE_START:-1}"
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
# abandons the stragglers (counted as errors). Default 1800 = 30 min: a HANG
# safety net. Without it (0 = disabled) a single wedged/half-open request — e.g. a
# stream the worker dropped mid-response on a model swap — blocks the whole
# pattern until the per-request timeout (hours), deadlocking the run. Legit
# requests, even with a cold load (~8 min) or KServe scale-from-zero under
# contention, finish well within 30 min; only genuinely-stuck ones are abandoned.
# Set 0 to disable (wait for ALL in-flight) only if you are sure no lane can wedge.
LOGOS_BENCH_DRAIN_CAP_S="${LOGOS_BENCH_DRAIN_CAP_S:-1800}"
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

# ── Campaign plan ─────────────────────────────────────────────────────────────
read -ra _rates <<< "$RATES"
_n_rates=${#_rates[@]}
_n_reps=$(( REPLICATES - REPLICATE_START + 1 ))
if (( _n_reps < 1 )); then
  echo "[run_bench] ERROR: REPLICATE_START ($REPLICATE_START) > REPLICATES ($REPLICATES)." >&2
  exit 1
fi
_total_runs=$(( _n_rates * _n_reps ))
echo "[run_bench] campaign: ${_n_rates} rate(s) [$RATES] × ${_n_reps} replicate(s)" \
     "(${REPLICATE_START}..${REPLICATES}) = ${_total_runs} run(s)," \
     "each all scenarios × patterns × ${NUM_SAMPLES:-ALL} requests"
if [[ "$SKIP_PREPARE" == "1" ]] && (( _total_runs > 1 )); then
  echo "[run_bench] WARNING: SKIP_PREPARE=1 with ${_total_runs} runs — every run" >&2
  echo "[run_bench]          reuses the SAME workload CSV (identical request→model" >&2
  echo "[run_bench]          assignment and arrival offsets across replicates/rates)." >&2
fi

# Static benchmark args; per-run args (--seed, --rps, --output-dir) are
# appended inside the loop.
bench_args_base=(
  --run-all-scenarios
  --logos-url "$LOGOS_URL"
  --workload "$WORKLOAD"
  --gpu-host $GPU_HOSTS
  --gpu-ssh-user "$GPU_SSH_USER"
  --request-timeout-s "$REQUEST_TIMEOUT_S"
  --settle-delay-s "$SETTLE_DELAY_S"
)
[[ -n "$LOGOS_KEY" ]] && bench_args_base+=(--logos-key "$LOGOS_KEY")
# Cell subsetting: SCENARIOS=kserve,ray PATTERNS=poisson,burst targets specific
# cells (e.g. the near-knee R=8-10 extension). Empty = all scenarios / patterns.
[[ -n "$SCENARIOS" ]] && bench_args_base+=(--scenarios "$SCENARIOS")
[[ -n "$PATTERNS" ]] && bench_args_base+=(--patterns "$PATTERNS")
[[ "$SKIP_WARMUP" == "1" ]] && bench_args_base+=(--skip-warmup)
[[ "$ONLY_OLLAMA" == "1" ]] && bench_args_base+=(--only-ollama)
[[ "$MANAGE_CALIB_WINDOW" == "0" ]] && bench_args_base+=(--no-manage-calibration-window)
[[ "$SHELLY" == "1" ]] && bench_args_base+=(--shelly --shelly-port "$SHELLY_PORT" --shelly-transport "$SHELLY_TRANSPORT" --shelly-ingest-image "$SHELLY_INGEST_IMAGE")
# Provider IDs are ALWAYS forwarded — they feed the live lane-state poller that
# fills model_timeline.csv, which is independent of calibration. (They are also
# used by --reset-calibration / ensure-calibrate when those run.) Split the
# space-separated list into a proper array so word boundaries are explicit and no
# glob expansion can sneak in.
if [[ -n "$CALIBRATION_PROVIDER_IDS" ]]; then
  read -ra _calib_provider_ids <<< "$CALIBRATION_PROVIDER_IDS"
  bench_args_base+=(--calibration-provider-ids "${_calib_provider_ids[@]}")
fi
# SKIP_CALIBRATION only gates the calibration step itself — NOT the lane poller.
[[ "$SKIP_CALIBRATION" == "1" ]] && bench_args_base+=(--skip-calibration)
[[ "$RESET_CALIBRATION" == "1" && "$SKIP_CALIBRATION" != "1" ]] && bench_args_base+=(--reset-calibration)
[[ -n "$BENCHMARK_LOCAL_CACHE" ]] && bench_args_base+=(--benchmark-local-cache "$BENCHMARK_LOCAL_CACHE")
# shellcheck disable=SC2206
[[ -n "$EXTRA_ARGS" ]] && bench_args_base+=($EXTRA_ARGS)

# ── Campaign loop: rates × replicates ─────────────────────────────────────────
_run_idx=0
for rate in "${_rates[@]}"; do
  for (( rep=REPLICATE_START; rep<=REPLICATES; rep++ )); do
    _run_idx=$(( _run_idx + 1 ))
    rep_seed=$(( SEED + rep - 1 ))
    rep_label="rep$(printf '%02d' "$rep")_seed${rep_seed}"
    out_dir="benchmark_results/rate_${rate}/${rep_label}"
    LOG="bench-rate${rate}-${rep_label}-$(date +%Y%m%d-%H%M%S).log"
    echo ""
    echo "[run_bench] ═══ run ${_run_idx}/${_total_runs}: rate=${rate} req/s," \
         "replicate ${rep}/${REPLICATES} (seed=${rep_seed}) → ${out_dir} (log=$LOG) ═══"

    # ── Step 1: regenerate the workload with the per-replicate seed ──────────
    if [[ "$SKIP_PREPARE" == "1" ]]; then
      echo "[run_bench] SKIP_PREPARE=1 — reusing existing workload CSVs."
    else
      echo "[run_bench] Preparing GSM8K workload (split=$GSM8K_SPLIT rps=$rate" \
           "num_samples=${NUM_SAMPLES:-ALL} seed=$rep_seed) ..."
      prepare_args=(--split "$GSM8K_SPLIT" --rps "$rate" --seed "$rep_seed")
      [[ -n "$NUM_SAMPLES" ]] && prepare_args+=(--num-samples "$NUM_SAMPLES")
      "$PYTHON" -u prepare_benchmark.py "${prepare_args[@]}"
    fi

    # ── Step 2: run the benchmark ─────────────────────────────────────────────
    bench_args=("${bench_args_base[@]}" --seed "$rep_seed" --rps "$rate" --output-dir "$out_dir")
    set +e
    "$PYTHON" -u benchmark_logos.py "${bench_args[@]}" 2>&1 | tee "$LOG"
    rc=${PIPESTATUS[0]}
    set -e
    echo "[run_bench] run ${_run_idx}/${_total_runs} exited rc=$rc (log=$LOG)"
    if (( rc != 0 )); then
      # Fail fast: a broken run usually means a broken cluster, and continuing
      # would contaminate later cells. Resume where it stopped with e.g.:
      #   RATES="<remaining rates>" REPLICATE_START=<this replicate> ...
      echo "[run_bench] ABORTING campaign at rate=${rate} replicate=${rep}." >&2
      echo "[run_bench] Resume with: RATES=\"...\" REPLICATE_START=${rep} REPLICATES=${REPLICATES}" >&2
      exit "$rc"
    fi
  done
done

echo ""
echo "[run_bench] campaign complete: ${_total_runs} run(s) finished."
exit 0
