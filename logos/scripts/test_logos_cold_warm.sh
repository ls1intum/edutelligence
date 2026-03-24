#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:18080}"
TIMEOUT_S="${TIMEOUT_S:-150}"
OUTPUT_ROOT="${OUTPUT_ROOT:-scripts/results}"
PROMPT_TEXT="${PROMPT_TEXT:-Reply with exactly READY}"
MAX_TOKENS="${MAX_TOKENS:-8}"
WARM_REQUESTS="${WARM_REQUESTS:-1}"
PROVIDER_ID="${PROVIDER_ID:-}"
ENSURE_COLD=0
CAPTURE_LANES=1
MODELS=()

if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'
  C_BOLD=$'\033[1m'
  C_DIM=$'\033[2m'
  C_RED=$'\033[31m'
  C_GREEN=$'\033[32m'
  C_YELLOW=$'\033[33m'
  C_BLUE=$'\033[34m'
  C_CYAN=$'\033[36m'
else
  C_RESET=""
  C_BOLD=""
  C_DIM=""
  C_RED=""
  C_GREEN=""
  C_YELLOW=""
  C_BLUE=""
  C_CYAN=""
fi

usage() {
  cat <<EOF
Usage: $0 [options]

Options:
  --base-url URL        Logos API base URL (default: $BASE_URL)
  --model NAME          Model to test. Repeat for multiple models.
  --timeout SECONDS     Per-request timeout (default: $TIMEOUT_S)
  --output-dir DIR      Output root directory (default: $OUTPUT_ROOT)
  --prompt TEXT         Prompt text for the chat request
  --max-tokens N        max_tokens for each request (default: $MAX_TOKENS)
  --warm-requests N     Number of warm requests after the cold request (default: $WARM_REQUESTS)
  --provider-id ID      logosnode provider_id for lane admin calls
  --ensure-cold         Delete the planner lane before the first request for each model
  --no-capture-lanes    Skip /logosdb/providers/logosnode/lanes snapshots
  --help                Show this help

Environment:
  LOGOS_KEY             If unset, the script prompts for it securely.

Example:
  LOGOS_KEY=... $0 \\
    --model Qwen/Qwen2.5-0.5B-Instruct \\
    --model Qwen/Qwen2.5-Coder-7B-Instruct
EOF
}

log_line() {
  local level="$1"
  local color="$2"
  shift 2
  printf "%s[%s]%s %s\n" "$color" "$level" "$C_RESET" "$*"
}

info() { log_line "INFO" "$C_CYAN" "$@"; }
good() { log_line " OK " "$C_GREEN" "$@"; }
warn() { log_line "WARN" "$C_YELLOW" "$@"; }
fail() { log_line "FAIL" "$C_RED" "$@"; }

trim_preview() {
  python3 - "$1" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
if not path.exists():
    print("")
    raise SystemExit(0)
raw = path.read_text(encoding="utf-8", errors="replace").strip()
raw = " ".join(raw.split())
print(raw[:220])
PY
}

assistant_preview() {
  python3 - "$1" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
if not path.exists():
    print("")
    raise SystemExit(0)
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    print("")
    raise SystemExit(0)

text = ""
if isinstance(payload, dict):
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                text = str(message.get("content") or "")
            elif "text" in first:
                text = str(first.get("text") or "")
text = " ".join(text.split())
print(text[:220])
PY
}

planner_lane_id() {
  python3 - "$1" <<'PY'
import sys

model = sys.argv[1]
sanitized = model.replace("/", "_").replace(":", "_").replace(" ", "_")
print(f"planner-{sanitized}")
PY
}

write_payload() {
  local payload_path="$1"
  local model="$2"
  python3 - "$payload_path" "$model" "$PROMPT_TEXT" "$MAX_TOKENS" <<'PY'
import json
import pathlib
import sys

payload_path = pathlib.Path(sys.argv[1])
model = sys.argv[2]
prompt = sys.argv[3]
max_tokens = int(sys.argv[4])

payload = {
    "model": model,
    "messages": [
        {"role": "system", "content": "Be concise."},
        {"role": "user", "content": prompt},
    ],
    "temperature": 0,
    "max_tokens": max_tokens,
    "stream": False,
}
payload_path.write_text(json.dumps(payload), encoding="utf-8")
PY
}

capture_server_logs() {
  local target="$1"
  if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -qx 'logos-server'; then
    docker logs --tail 120 logos-server >"$target" 2>&1 || true
  fi
}

curl_json() {
  local method="$1"
  local url="$2"
  local payload_file="$3"
  local response_file="$4"
  local metrics_file="$5"

  local curl_status=0
  local curl_out=""
  if [[ -n "$payload_file" ]]; then
    if ! curl_out="$(
      curl -sS \
        --connect-timeout 5 \
        --max-time "$TIMEOUT_S" \
        -o "$response_file" \
        -w 'status=%{http_code} total=%{time_total}\n' \
        -H "logos_key: $LOGOS_KEY" \
        -H 'Content-Type: application/json' \
        -X "$method" "$url" \
        --data @"$payload_file"
    )"; then
      curl_status=$?
    fi
  else
    if ! curl_out="$(
      curl -sS \
        --connect-timeout 5 \
        --max-time "$TIMEOUT_S" \
        -o "$response_file" \
        -w 'status=%{http_code} total=%{time_total}\n' \
        -H "logos_key: $LOGOS_KEY" \
        -X "$method" "$url"
    )"; then
      curl_status=$?
    fi
  fi
  printf '%s\n' "$curl_out" >"$metrics_file"
  printf '%s\n' "$curl_status"
}

extract_http_status() {
  python3 - "$1" <<'PY'
import pathlib
import re
import sys

text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
match = re.search(r"status=(\d{3})", text)
print(match.group(1) if match else "000")
PY
}

extract_total_seconds() {
  python3 - "$1" <<'PY'
import pathlib
import re
import sys

text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
match = re.search(r"total=([0-9.]+)", text)
print(match.group(1) if match else "0")
PY
}

write_admin_payload() {
  local payload_path="$1"
  local provider_id="$2"
  local lane_id="$3"
  python3 - "$payload_path" "$provider_id" "$lane_id" <<'PY'
import json
import os
import pathlib
import sys

payload_path = pathlib.Path(sys.argv[1])
provider_id = int(sys.argv[2])
lane_id = sys.argv[3]
payload = {
    "logos_key": os.environ["LOGOS_KEY"],
    "provider_id": provider_id,
    "lane_id": lane_id,
}
payload_path.write_text(json.dumps(payload), encoding="utf-8")
PY
}

capture_lane_state() {
  local provider_id="$1"
  local target_prefix="$2"
  local response_file="${target_prefix}_lanes.json"
  local metrics_file="${target_prefix}_lanes_metrics.txt"
  local payload_file="${target_prefix}_lanes_payload.json"

  if [[ "$CAPTURE_LANES" -ne 1 || -z "$provider_id" ]]; then
    return 0
  fi

  python3 - "$payload_file" "$provider_id" <<'PY'
import json
import os
import pathlib
import sys

payload_path = pathlib.Path(sys.argv[1])
provider_id = int(sys.argv[2])
payload = {"logos_key": os.environ["LOGOS_KEY"], "provider_id": provider_id}
payload_path.write_text(json.dumps(payload), encoding="utf-8")
PY

  local curl_status
  curl_status="$(curl_json POST "$BASE_URL/logosdb/providers/logosnode/lanes" "$payload_file" "$response_file" "$metrics_file")"
  if [[ "$curl_status" -ne 0 ]]; then
    warn "Failed to capture lane snapshot (curl_exit=$curl_status)"
    return 0
  fi
  local http_status
  http_status="$(extract_http_status "$metrics_file")"
  if [[ "$http_status" != "200" ]]; then
    warn "Lane snapshot returned HTTP $http_status"
  fi
}

delete_lane_for_cold_start() {
  local provider_id="$1"
  local lane_id="$2"
  local run_dir="$3"
  local slug="$4"
  local payload_file="$run_dir/${slug}_delete_lane_payload.json"
  local response_file="$run_dir/${slug}_delete_lane_response.json"
  local metrics_file="$run_dir/${slug}_delete_lane_metrics.txt"

  write_admin_payload "$payload_file" "$provider_id" "$lane_id"
  info "Deleting lane ${lane_id} on provider ${provider_id} before cold request"
  local curl_status
  curl_status="$(curl_json POST "$BASE_URL/logosdb/providers/logosnode/lanes/delete" "$payload_file" "$response_file" "$metrics_file")"
  local http_status
  http_status="$(extract_http_status "$metrics_file")"
  local total_s
  total_s="$(extract_total_seconds "$metrics_file")"

  if [[ "$curl_status" -ne 0 ]]; then
    fail "Lane delete failed (curl_exit=${curl_status}, total=${total_s}s)"
    local response_preview
    response_preview="$(trim_preview "$response_file")"
    [[ -n "$response_preview" ]] && printf "    %sbody:%s %s\n" "$C_DIM" "$C_RESET" "$response_preview"
    return 1
  fi

  if [[ "$http_status" == "200" || "$http_status" == "502" ]]; then
    if [[ "$http_status" == "200" ]]; then
      good "Lane delete accepted in ${total_s}s"
    else
      warn "Lane delete returned HTTP 502 in ${total_s}s; continuing in case lane was already absent"
    fi
    return 0
  fi

  fail "Lane delete returned HTTP ${http_status} in ${total_s}s"
  local response_preview
  response_preview="$(trim_preview "$response_file")"
  [[ -n "$response_preview" ]] && printf "    %sbody:%s %s\n" "$C_DIM" "$C_RESET" "$response_preview"
  return 1
}

run_request() {
  local model="$1"
  local phase="$2"
  local run_dir="$3"
  local index="$4"

  local slug
  slug="$(printf '%s' "$model" | tr '/: .' '____')"
  local payload_file="$run_dir/${index}_${slug}_${phase}_payload.json"
  local response_file="$run_dir/${index}_${slug}_${phase}_response.json"
  local metrics_file="$run_dir/${index}_${slug}_${phase}_metrics.txt"
  local log_file="$run_dir/${index}_${slug}_${phase}_logos-server.log"

  write_payload "$payload_file" "$model"
  capture_lane_state "$PROVIDER_ID" "$run_dir/${index}_${slug}_${phase}_before"

  info "${model} :: ${phase} request"
  local curl_status
  curl_status="$(curl_json POST "$BASE_URL/v1/chat/completions" "$payload_file" "$response_file" "$metrics_file")"
  capture_server_logs "$log_file"
  capture_lane_state "$PROVIDER_ID" "$run_dir/${index}_${slug}_${phase}_after"

  local http_status
  http_status="$(extract_http_status "$metrics_file")"
  local total_s
  total_s="$(extract_total_seconds "$metrics_file")"

  local response_preview=""
  local assistant_text=""
  response_preview="$(trim_preview "$response_file")"
  assistant_text="$(assistant_preview "$response_file")"

  if [[ "$curl_status" -eq 0 && "$http_status" == "200" ]]; then
    good "${model} :: ${phase} completed in ${C_BOLD}${total_s}s${C_RESET}"
    if [[ -n "$assistant_text" ]]; then
      printf "    %sassistant:%s %s\n" "$C_DIM" "$C_RESET" "$assistant_text"
    fi
  else
    fail "${model} :: ${phase} failed (curl_exit=${curl_status}, http=${http_status}, total=${total_s}s)"
    if [[ -n "$response_preview" ]]; then
      printf "    %sbody:%s %s\n" "$C_DIM" "$C_RESET" "$response_preview"
    fi
  fi

  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$model" "$phase" "$curl_status" "$http_status" "$total_s" "$response_file" "$log_file" \
    >>"$run_dir/summary.tsv"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-url)
      BASE_URL="$2"
      shift 2
      ;;
    --model)
      MODELS+=("$2")
      shift 2
      ;;
    --timeout)
      TIMEOUT_S="$2"
      shift 2
      ;;
    --output-dir)
      OUTPUT_ROOT="$2"
      shift 2
      ;;
    --prompt)
      PROMPT_TEXT="$2"
      shift 2
      ;;
    --max-tokens)
      MAX_TOKENS="$2"
      shift 2
      ;;
    --warm-requests)
      WARM_REQUESTS="$2"
      shift 2
      ;;
    --provider-id)
      PROVIDER_ID="$2"
      shift 2
      ;;
    --ensure-cold)
      ENSURE_COLD=1
      shift
      ;;
    --no-capture-lanes)
      CAPTURE_LANES=0
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      fail "Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

if [[ ${#MODELS[@]} -eq 0 ]]; then
  MODELS=("Qwen/Qwen2.5-0.5B-Instruct")
fi

if [[ -z "${LOGOS_KEY:-}" ]]; then
  printf "%sEnter logos_key:%s " "$C_BOLD" "$C_RESET" >&2
  read -r -s LOGOS_KEY
  printf "\n" >&2
fi

if [[ -z "$LOGOS_KEY" ]]; then
  fail "LOGOS_KEY is required"
  exit 1
fi

timestamp="$(date '+%Y%m%d_%H%M%S')"
run_dir="${OUTPUT_ROOT%/}/logos_cold_warm_${timestamp}"
mkdir -p "$run_dir"
printf 'model\tphase\tcurl_exit\thttp_status\ttotal_seconds\tresponse_file\tlogos_server_log\n' >"$run_dir/summary.tsv"

info "Output directory: $run_dir"
info "Base URL: $BASE_URL"
info "Models: ${MODELS[*]}"
if [[ -n "$PROVIDER_ID" ]]; then
  info "Provider ID: $PROVIDER_ID"
fi

info "Preflight /v1/models"
models_status=0
models_status="$(curl_json GET "$BASE_URL/v1/models" "" "$run_dir/v1_models.json" "$run_dir/v1_models_metrics.txt")"
capture_server_logs "$run_dir/v1_models_logos-server.log"
if [[ "$models_status" != "0" ]]; then
  fail "Preflight /v1/models request failed (curl_exit=$models_status)"
  exit 1
fi
if [[ "$(extract_http_status "$run_dir/v1_models_metrics.txt")" == "200" ]]; then
  good "Preflight /v1/models succeeded"
else
  fail "Preflight /v1/models did not return HTTP 200"
  cat "$run_dir/v1_models_metrics.txt"
  exit 1
fi

request_index=1
for model in "${MODELS[@]}"; do
  printf "\n%s== %s ==%s\n" "$C_BOLD$C_BLUE" "$model" "$C_RESET"
  if [[ "$ENSURE_COLD" -eq 1 ]]; then
    if [[ -z "$PROVIDER_ID" ]]; then
      fail "--ensure-cold requires --provider-id"
      exit 1
    fi
    slug="$(printf '%s' "$model" | tr '/: .' '____')"
    lane_id="$(planner_lane_id "$model")"
    capture_lane_state "$PROVIDER_ID" "$run_dir/${slug}_pre_delete"
    delete_lane_for_cold_start "$PROVIDER_ID" "$lane_id" "$run_dir" "$slug"
    capture_lane_state "$PROVIDER_ID" "$run_dir/${slug}_post_delete"
  fi
  run_request "$model" "cold" "$run_dir" "$request_index"
  request_index=$((request_index + 1))

  warm_idx=1
  while [[ "$warm_idx" -le "$WARM_REQUESTS" ]]; do
    run_request "$model" "warm${warm_idx}" "$run_dir" "$request_index"
    request_index=$((request_index + 1))
    warm_idx=$((warm_idx + 1))
  done
done

printf "\n%sSummary%s\n" "$C_BOLD" "$C_RESET"
column -t -s $'\t' "$run_dir/summary.tsv" || cat "$run_dir/summary.tsv"
good "Artifacts written to $run_dir"
