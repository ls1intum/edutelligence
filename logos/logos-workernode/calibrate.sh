#!/usr/bin/env bash
# calibrate.sh — Pre-calibrate model VRAM profiles for the Logos worker node.
#
# Loads each capabilities model from config.yml via vLLM, measures real awake
# and sleeping VRAM, and writes model_profiles.yml to the shared worker-state
# volume. The worker reads these values on next startup — no estimation needed.
#
# Usage:
#   ./calibrate.sh                          # use all models + settings from config.yml
#   ./calibrate.sh --kv-cache 6G           # override global KV cache default
#   ./calibrate.sh --models Org/A,Org/B    # restrict to specific models
#   ./calibrate.sh --sleep-level 2         # use sleep level 2 (offloads weights to CPU too)
#
# The worker (logos-workernode) must be stopped before running this script.
# Per-model overrides (tensor_parallel_size, kv_cache_memory_bytes, gpu_devices)
# are read directly from config.yml — no duplication needed here.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/config.yml"
LOG_DIR="${SCRIPT_DIR}/calibration_logs"
LOG_FILE="${LOG_DIR}/calibrate_$(date +%Y%m%d_%H%M%S).log"

# ── Colours ───────────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
    GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
    CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'
else
    GREEN=''; YELLOW=''; RED=''; CYAN=''; BOLD=''; DIM=''; RESET=''
fi

mkdir -p "$LOG_DIR"

_log()  { local msg="$*"; echo -e "${CYAN}[calibrate]${RESET} ${msg}" | tee -a "$LOG_FILE"; }
_ok()   { local msg="$*"; echo -e "${GREEN}[calibrate] OK${RESET}    ${msg}" | tee -a "$LOG_FILE"; }
_warn() { local msg="$*"; echo -e "${YELLOW}[calibrate] WARN${RESET}  ${msg}" | tee -a "$LOG_FILE"; }
_err()  { local msg="$*"; echo -e "${RED}[calibrate] ERROR${RESET} ${msg}" | tee -a "$LOG_FILE" >&2; }
_sep()  { echo -e "${DIM}$(printf -- '─%.0s' {1..64})${RESET}" | tee -a "$LOG_FILE"; }

# ── Argument parsing ──────────────────────────────────────────────────────────
KV_CACHE_OVERRIDE=""   # empty = read from config.yml
MODELS_FILTER=""
SLEEP_LEVEL=1   # matches the worker default (lane_manager sleep_lane level=1)
IMAGE_TAG="${IMAGE_TAG:-latest}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --kv-cache)     KV_CACHE_OVERRIDE="$2";  shift 2 ;;
        --models)       MODELS_FILTER="$2";       shift 2 ;;
        --sleep-level)  SLEEP_LEVEL="$2";         shift 2 ;;
        --help|-h)      sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) _err "Unknown argument: $1  (try --help)"; exit 1 ;;
    esac
done

# ── Config reading via Python ─────────────────────────────────────────────────
# Returns lines: model<TAB>tp<TAB>gpu_devices<TAB>kv_cache_bytes
# where kv_cache_bytes is the per-model override or the global default.
_read_config() {
    local global_default="$1"
    python3 - "$CONFIG_FILE" "$global_default" <<'PYEOF'
import sys, pathlib

config_file = pathlib.Path(sys.argv[1])
global_default_kv = sys.argv[2]

try:
    import yaml
except ImportError:
    sys.exit(0)

if not config_file.exists():
    sys.exit(0)

with open(config_file) as f:
    raw = yaml.safe_load(f) or {}

logos     = raw.get("logos") or {}
caps_raw  = logos.get("capabilities_models") or []
overrides = logos.get("capabilities_overrides") or {}

for entry in caps_raw:
    if isinstance(entry, str):
        name = entry
        per_model = dict(overrides.get(name) or {})
    elif isinstance(entry, dict):
        name = entry.get("model", "")
        per_model = {**entry, **(overrides.get(name) or {})}
        per_model.pop("model", None)
    else:
        continue
    if not name:
        continue
    tp         = per_model.get("tensor_parallel_size", 1)
    gpu_dev    = per_model.get("gpu_devices", "") or ""
    kv         = per_model.get("kv_cache_memory_bytes") or global_default_kv
    print(f"{name}\t{tp}\t{gpu_dev or 'all'}\t{kv}")
PYEOF
}

# Derive global KV default from config (most common per-model value, or 4G).
_resolve_kv_default() {
    python3 - "$CONFIG_FILE" <<'PYEOF'
import sys, pathlib, collections

config_file = pathlib.Path(sys.argv[1])
try:
    import yaml
except ImportError:
    print("4G"); sys.exit(0)

if not config_file.exists():
    print("4G"); sys.exit(0)

with open(config_file) as f:
    raw = yaml.safe_load(f) or {}

logos    = raw.get("logos") or {}
caps_raw = logos.get("capabilities_models") or []
overrides = logos.get("capabilities_overrides") or {}
kvs = []
for entry in caps_raw:
    if isinstance(entry, str):
        per = overrides.get(entry) or {}
    elif isinstance(entry, dict):
        name = entry.get("model", "")
        per = {**entry, **(overrides.get(name) or {})}
    else:
        continue
    kv = per.get("kv_cache_memory_bytes")
    if kv:
        kvs.append(str(kv))
if kvs:
    print(collections.Counter(kvs).most_common(1)[0][0])
else:
    print("4G")
PYEOF
}

# ── Resolve KV cache default ──────────────────────────────────────────────────
if [[ -n "$KV_CACHE_OVERRIDE" ]]; then
    KV_CACHE="$KV_CACHE_OVERRIDE"
elif ! command -v python3 &>/dev/null; then
    KV_CACHE="${CALIBRATION_KV_CACHE:-4G}"
else
    KV_CACHE="$(_resolve_kv_default)"
fi

# ── Pre-flight ────────────────────────────────────────────────────────────────
_sep
_log "${BOLD}Logos Worker Node — VRAM Calibration${RESET}"
_log "Started:      $(date '+%Y-%m-%d %H:%M:%S')"
_log "Config:       ${CONFIG_FILE}"
_log "Log:          ${LOG_FILE}"
_log "KV cache:     ${BOLD}${KV_CACHE}${RESET} (global default; per-model overrides from config.yml apply)"
_log "Sleep level:  ${SLEEP_LEVEL}"
_sep

if [[ ! -f "$CONFIG_FILE" ]]; then
    _err "config.yml not found: ${CONFIG_FILE}"
    exit 1
fi

if ! docker compose version &>/dev/null 2>&1; then
    _err "docker compose not found — is Docker installed?"
    exit 1
fi

# Warn if the worker is running (it holds the GPUs).
if docker compose ps --status running logos-workernode 2>/dev/null | grep -q "logos-workernode"; then
    _err "logos-workernode is currently running and holds the GPUs."
    _err "Stop it first:  docker compose stop logos-workernode"
    exit 1
fi

# ── Show models from config ───────────────────────────────────────────────────
_log "Capabilities models from config.yml:"

declare -a PLAN_MODELS=()

if ! command -v python3 &>/dev/null; then
    _warn "python3 not found on host — cannot parse config.yml for pre-flight listing."
    _warn "Calibration will still run (the container has Python)."
else
    while IFS=$'\t' read -r name tp gpu kv; do
        [[ -z "$name" ]] && continue
        if [[ -n "$MODELS_FILTER" ]] && [[ ",${MODELS_FILTER}," != *",${name},"* ]]; then
            _log "  ${DIM}${name}${RESET}  (skipped — not in --models filter)"
            continue
        fi
        PLAN_MODELS+=("$name")
        _log "  ${BOLD}${name}${RESET}"
        _log "      tp=${tp}  gpu_devices=${gpu}  kv_cache=${BOLD}${kv}${RESET}"
    done < <(_read_config "$KV_CACHE")

    if [[ ${#PLAN_MODELS[@]} -eq 0 && -z "$MODELS_FILTER" ]]; then
        _warn "No capabilities_models found in config.yml — nothing to calibrate."
        exit 0
    fi
fi

_sep

# ── Run calibration ───────────────────────────────────────────────────────────
_log "Starting calibration — models are loaded one at a time."
_log "Do not start the worker until this script exits."
_sep

# Build the full command to run inside the container, overriding the service default.
# This gives us control over all flags from this script rather than docker-compose.yml.
CONTAINER_CMD=(
    python3 /app/tools/calibrate_vram_profiles.py
    --config    /app/config.yml
    --state-dir /app/data
    --kv-cache-memory-bytes "${KV_CACHE}"
    --sleep-level "${SLEEP_LEVEL}"
)
[[ -n "$MODELS_FILTER" ]] && CONTAINER_CMD+=(--models "${MODELS_FILTER}")

CALIBRATION_EXIT=0
docker compose \
    --profile calibrate \
    run --rm \
    logos-workernode-calibrate \
    "${CONTAINER_CMD[@]}" \
    2>&1 | tee -a "$LOG_FILE" \
    || CALIBRATION_EXIT=$?

# ── Parse results from captured log ──────────────────────────────────────────
_sep
_log "Parsing results..."

# Models that were attempted (each emits "Calibrating: <model>" at start).
mapfile -t ATTEMPTED < <(
    grep "^Calibrating: " "$LOG_FILE" | sed 's/^Calibrating: //' | sed 's/[[:space:]]*$//'
)

# Succeeded: lines in the summary table that end with "MB"
# Format: "  {model:<40} {loaded}  {kv_sent}    {base}  {sleeping}  MB"
mapfile -t SUCCEEDED < <(
    awk '
        /CALIBRATION SUMMARY/  { in_summary=1 }
        in_summary && /[0-9]  MB$/ {
            # first non-space token is the model name
            sub(/^[[:space:]]+/, ""); print $1
        }
    ' "$LOG_FILE"
)

# Failed: lines under "Failed models:" section, format "    <model>: <reason>"
mapfile -t FAILED_LINES < <(
    awk '
        /^  Failed models:/ { in_failed=1; next }
        in_failed && /^    [A-Za-z]/ { sub(/^[[:space:]]+/, ""); print }
        in_failed && /^$/ { in_failed=0 }
    ' "$LOG_FILE"
)

# Models that were attempted but appear in neither table (e.g. container crash).
declare -a MISSING=()
for model in "${ATTEMPTED[@]}"; do
    found=0
    for s in "${SUCCEEDED[@]}";  do [[ "$s" == "$model" ]] && found=1; done
    for f in "${FAILED_LINES[@]}"; do [[ "$f" == "$model:"* ]] && found=1; done
    [[ $found -eq 0 ]] && MISSING+=("$model")
done

# ── Summary ───────────────────────────────────────────────────────────────────
_sep
_log "${BOLD}SUMMARY${RESET}"
_sep

TOTAL_ATTEMPTED=${#ATTEMPTED[@]}
TOTAL_OK=${#SUCCEEDED[@]}
TOTAL_FAIL=$(( ${#FAILED_LINES[@]} + ${#MISSING[@]} ))

_log "Attempted: ${TOTAL_ATTEMPTED} models   OK: ${TOTAL_OK}   Failed: ${TOTAL_FAIL}"
echo | tee -a "$LOG_FILE"

if [[ ${#SUCCEEDED[@]} -gt 0 ]]; then
    _log "Calibrated successfully:"
    for model in "${SUCCEEDED[@]}"; do
        _ok "  ${model}"
    done
    echo | tee -a "$LOG_FILE"
fi

if [[ ${#FAILED_LINES[@]} -gt 0 ]]; then
    _warn "Could not be calibrated:"
    for line in "${FAILED_LINES[@]}"; do
        _warn "  ${line}"
    done
    _warn ""
    _warn "Possible causes: insufficient VRAM, model not downloaded, vLLM startup timeout."
    _warn "These models will be skipped during worker placement until manually overridden"
    _warn "in config.yml under model_profile_overrides."
    echo | tee -a "$LOG_FILE"
fi

if [[ ${#MISSING[@]} -gt 0 ]]; then
    _warn "Started but no result recorded (container may have crashed):"
    for model in "${MISSING[@]}"; do
        _warn "  ${model}"
    done
    _warn "Check the full log: ${LOG_FILE}"
    echo | tee -a "$LOG_FILE"
fi

_sep
_log "Full log: ${LOG_FILE}"
_sep

if [[ $TOTAL_OK -gt 0 && $TOTAL_FAIL -eq 0 ]]; then
    _ok "All models calibrated. Start the worker:"
    _ok "  docker compose up -d logos-workernode"
    exit 0
elif [[ $TOTAL_OK -gt 0 ]]; then
    _warn "Partial calibration — ${TOTAL_OK} succeeded, ${TOTAL_FAIL} failed."
    _warn "The worker can start; uncalibrated models will not have placement data."
    _warn "  docker compose up -d logos-workernode"
    exit 1
else
    _err "All models failed. The worker will have no calibrated profiles."
    _err "Check the log for details: ${LOG_FILE}"
    exit 2
fi
