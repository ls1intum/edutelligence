#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CONTROLLER_URL="http://127.0.0.1:8444"
API_KEY="${API_KEY:-RANDOM_DEFAULT_KEY}"
MODEL="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B"
VLLM_BINARY="vllm"
PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
GPU_DEVICES="0,1"
TENSOR_PARALLEL_SIZE="2"
MAX_MODEL_LEN="4096"
MAX_TOKENS="200"
WARMUP="1"
CONCURRENCY="32,64"
MEMORY_UTILIZATION="0.70"
IDLE_VRAM_MB_PER_GPU="1200"
VRAM_WAIT_TIMEOUT_S="300"
REQUEST_TIMEOUT_S="900"
BATCH_TIMEOUT_S="0"
OUTPUT_ROOT="$SCRIPT_DIR/bench_results/memory_constrained"
KEEP_LAST_LANE="0"

usage() {
  cat <<'USAGE'
DeepSeek vLLM memory-constrained benchmark runner.

Usage:
  ./bench_deepseek_vllm_mem.sh [options]

Options:
  --controller-url URL           Node Controller base URL (default: http://127.0.0.1:8444)
  --api-key KEY                  Controller API key (default: $API_KEY or RANDOM_DEFAULT_KEY)
  --model NAME                   vLLM model (default: deepseek-ai/DeepSeek-R1-0528-Qwen3-8B)
  --memory-util FLOAT            vLLM gpu_memory_utilization, 0 < x <= 1 (default: 0.70)
  --concurrency LIST             Comma list, e.g. 32,64 (default: 32,64)
  --max-model-len N              vLLM max model length (default: 4096)
  --max-tokens N                 Max generation tokens per request (default: 200)
  --warmup N                     Warmup requests before benchmark (default: 1)
  --gpu-devices LIST             GPU device list for lane (default: 0,1)
  --tensor-parallel-size N       vLLM tensor parallel size (default: 2)
  --vllm-binary PATH             vLLM executable path (default: vllm)
  --python-bin PATH              Python executable for benchmark runner (default: .venv/bin/python)
  --idle-vram-mb-per-gpu N       Target idle VRAM threshold per GPU in MB (default: 1200)
  --vram-wait-timeout-s N        Timeout waiting for idle VRAM (default: 300)
  --request-timeout-s N          Per-request timeout in seconds (default: 900)
  --batch-timeout-s N            Whole-batch timeout in seconds, 0 disables (default: 0)
  --output-root DIR              Root output dir (default: bench_results/memory_constrained)
  --keep-last-lane               Keep the vLLM lane running after benchmark
  -h, --help                     Show this help

What this script does:
  1) Clears all Node Controller lanes.
  2) Calls /admin/ollama/destroy to release managed Ollama resources.
  3) Waits for lanes to be empty and VRAM to fall below threshold.
  4) Runs varied requests at concurrency 32 and 64 through a DeepSeek vLLM lane.
  5) Writes benchmark JSON/CSV plus:
     - summary_tokps_latency.csv
     - summary_tokps_latency.md
     - requests_used.csv
  in a memory-scoped output folder.
USAGE
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing required command: $cmd" >&2
    exit 1
  fi
}

has_cmd() {
  command -v "$1" >/dev/null 2>&1
}

controller_get() {
  local path="$1"
  curl -fsS \
    -H "Authorization: Bearer $API_KEY" \
    "${CONTROLLER_URL%/}${path}"
}

controller_post_json() {
  local path="$1"
  local body="$2"
  curl -fsS -X POST \
    -H "Authorization: Bearer $API_KEY" \
    -H "Content-Type: application/json" \
    -d "$body" \
    "${CONTROLLER_URL%/}${path}"
}

controller_post_no_body() {
  local path="$1"
  curl -fsS -X POST \
    -H "Authorization: Bearer $API_KEY" \
    "${CONTROLLER_URL%/}${path}"
}

clear_all_lanes() {
  controller_post_json "/admin/lanes/apply" '{"lanes":[]}' >/dev/null
}

destroy_managed_ollama_best_effort() {
  controller_post_no_body "/admin/ollama/destroy" >/dev/null 2>&1 || true
}

wait_for_empty_lanes() {
  local timeout_s="$1"
  local deadline=$((SECONDS + timeout_s))

  while (( SECONDS < deadline )); do
    local lanes_json
    lanes_json="$(controller_get "/admin/lanes" 2>/dev/null || echo "[]")"
    local lane_count
    lane_count="$(jq -r 'if type=="array" then length else 999 end' <<<"$lanes_json" 2>/dev/null || echo "999")"
    if [[ "$lane_count" == "0" ]]; then
      return 0
    fi
    echo "Waiting for lanes to clear. Active lanes: $lane_count"
    sleep 2
  done

  echo "Timed out waiting for lanes to become empty." >&2
  return 1
}

print_gpu_mem_snapshot() {
  local mem_csv
  mem_csv="$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits | awk -F',' '{gsub(/ /,"",$1); gsub(/ /,"",$2); printf "GPU%s=%sMB ", $1, $2}')"
  echo "${mem_csv:-unknown}"
}

wait_for_idle_vram() {
  local threshold_mb="$1"
  local timeout_s="$2"
  local deadline=$((SECONDS + timeout_s))

  while (( SECONDS < deadline )); do
    mapfile -t used_mb < <(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | awk '{print int($1)}')
    if (( ${#used_mb[@]} == 0 )); then
      echo "Could not read GPU memory usage yet; retrying..."
      sleep 3
      continue
    fi

    local max_used=0
    for mb in "${used_mb[@]}"; do
      if (( mb > max_used )); then
        max_used="$mb"
      fi
    done

    echo "Current VRAM usage: $(print_gpu_mem_snapshot) (max=${max_used}MB, target<=${threshold_mb}MB)"
    if (( max_used <= threshold_mb )); then
      return 0
    fi

    sleep 3
  done

  echo "VRAM did not reach idle threshold within timeout." >&2
  echo "Active GPU processes:" >&2
  nvidia-smi --query-compute-apps=pid,process_name,used_gpu_memory --format=csv,noheader || true
  return 1
}

latest_file_for_pattern() {
  local dir="$1"
  local pattern="$2"
  local files=()
  shopt -s nullglob
  files=("${dir}"/${pattern})
  shopt -u nullglob
  if (( ${#files[@]} == 0 )); then
    return 1
  fi
  printf '%s\n' "${files[@]}" | sort | tail -n 1
}

latest_benchmark_json() {
  local dir="$1"
  local files=()
  shopt -s nullglob
  files=("${dir}"/lane_benchmark_*.json)
  shopt -u nullglob
  if (( ${#files[@]} == 0 )); then
    return 1
  fi

  # Exclude payload sample dumps; they are arrays and not benchmark summary JSON.
  printf '%s\n' "${files[@]}" \
    | grep -v '/lane_benchmark_payloads_' \
    | sort \
    | tail -n 1
}

generate_summary_csv() {
  local benchmark_json="$1"
  local summary_csv="$2"
  jq -r '
    . as $root
    | ["run_label","concurrency","aggregate_tok_s","avg_latency_s","p95_latency_s","avg_ttft_ms","error_rate"] | @csv,
    ($root.backends[] as $b
      | $b.results[]
      | [
          ($b.run_label // ""),
          (.concurrency // ""),
          (.aggregate_tok_s // ""),
          (.avg_latency_s // ""),
          (.p95_latency_s // ""),
          (.avg_ttft_ms // ""),
          (.error_rate // "")
        ]
      | @csv
    )
  ' "$benchmark_json" > "$summary_csv"
}

generate_summary_md() {
  local benchmark_json="$1"
  local summary_md="$2"
  local utc_now
  utc_now="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"

  {
    echo "# DeepSeek vLLM Benchmark Summary"
    echo
    echo "- Timestamp (UTC): $utc_now"
    echo "- Model: $MODEL"
    echo "- Concurrency: $CONCURRENCY"
    echo "- Memory Utilization: $MEMORY_UTILIZATION"
    echo "- Prompt Mode: varied_unique_prefix"
    echo
    echo "| Run | Concurrency | Tok/s | Avg Latency (s) | P95 Latency (s) | Avg TTFT (ms) | Error Rate |"
    echo "|---|---:|---:|---:|---:|---:|---:|"
    jq -r '
      .backends[] as $b
      | $b.results[]
      | "| \($b.run_label // "n/a") | \(.concurrency // "n/a") | \(.aggregate_tok_s // "n/a") | \(.avg_latency_s // "n/a") | \(.p95_latency_s // "n/a") | \(.avg_ttft_ms // "n/a") | \(.error_rate // "n/a") |"
    ' "$benchmark_json"
  } > "$summary_md"
}

generate_requests_csv() {
  local payload_json="$1"
  local requests_csv="$2"
  jq -r '
    . as $root
    | ["run_label","request_index","model","max_tokens","temperature","system_prompt","user_prompt"] | @csv,
    ($root.runs[] as $run
      | ($run.payload_samples // [])
      | to_entries[]
      | [
          ($run.run_label // ""),
          (.key | tostring),
          (.value.model // ""),
          ((.value.max_tokens // "") | tostring),
          ((.value.temperature // "") | tostring),
          (.value.messages[0].content // ""),
          (.value.messages[1].content // "")
        ]
      | @csv
    )
  ' "$payload_json" > "$requests_csv"
}

detect_node_controller_container() {
  if ! has_cmd docker; then
    return 1
  fi

  local name
  name="$(docker ps --format '{{.Names}}' 2>/dev/null | awk '$0=="node-controller"{print $0; exit}')"
  [[ "$name" == "node-controller" ]]
}

preflight_vllm_runtime() {
  local configured="$1"
  local controller_hint=""

  if detect_node_controller_container; then
    controller_hint="docker"
    if ! docker exec node-controller sh -lc 'command -v vllm >/dev/null 2>&1'; then
      cat >&2 <<'PREFLIGHT'
Detected containerized Node Controller ('node-controller') without a 'vllm' executable.
vLLM lanes cannot be created in this runtime.

Fix one of these before rerunning:
1) Run Node Controller on host .venv (recommended for vLLM lanes):
   cd /home/ge84ciq/node-controller-test/edutelligence/logos/node-controller
   docker compose down
   source .venv/bin/activate
   python -m node_controller.main
2) Or rebuild Docker mode with vLLM enabled:
   cd /home/ge84ciq/node-controller-test/edutelligence/logos/node-controller
   echo "INSTALL_VLLM=1" >> .env
   ./start.sh
PREFLIGHT
      exit 1
    fi
    if ! docker exec node-controller sh -lc 'command -v nvcc >/dev/null 2>&1 || test -x /usr/local/cuda-12.8/bin/nvcc || test -x /usr/local/cuda/bin/nvcc'; then
      cat >&2 <<'PREFLIGHT'
Detected containerized Node Controller ('node-controller') without CUDA nvcc visibility.
This runtime can start vLLM but DeepSeek lane startup may fail during worker compilation.

Fix before rerunning:
1) Ensure host CUDA toolkit is installed and nvcc exists:
   /usr/local/cuda-12.8/bin/nvcc --version
2) Ensure docker-compose mounts CUDA toolkit into node-controller:
   /usr/local/cuda-12.8:/usr/local/cuda-12.8:ro
3) Rebuild/restart:
   cd /home/ge84ciq/node-controller-test/edutelligence/logos/node-controller
   ./start.sh
PREFLIGHT
      exit 1
    fi
  fi

  if [[ "$configured" == "vllm" ]]; then
    if [[ "$controller_hint" == "docker" ]]; then
      echo "Preflight: using controller runtime vLLM binary resolution (docker PATH: vllm)."
    else
      echo "Preflight: using controller runtime vLLM binary resolution (PATH + interpreter sibling)."
    fi
    return 0
  fi

  if [[ "$controller_hint" == "docker" ]]; then
    if ! docker exec node-controller sh -lc "test -x '$configured'"; then
      echo "Configured --vllm-binary '$configured' is not executable inside node-controller container." >&2
      echo "Use --vllm-binary vllm (with vllm installed in container) or run host-mode controller." >&2
      exit 1
    fi
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --controller-url)
      CONTROLLER_URL="$2"
      shift 2
      ;;
    --api-key)
      API_KEY="$2"
      shift 2
      ;;
    --model)
      MODEL="$2"
      shift 2
      ;;
    --memory-util)
      MEMORY_UTILIZATION="$2"
      shift 2
      ;;
    --concurrency)
      CONCURRENCY="$2"
      shift 2
      ;;
    --max-model-len)
      MAX_MODEL_LEN="$2"
      shift 2
      ;;
    --max-tokens)
      MAX_TOKENS="$2"
      shift 2
      ;;
    --warmup)
      WARMUP="$2"
      shift 2
      ;;
    --gpu-devices)
      GPU_DEVICES="$2"
      shift 2
      ;;
    --tensor-parallel-size)
      TENSOR_PARALLEL_SIZE="$2"
      shift 2
      ;;
    --vllm-binary)
      VLLM_BINARY="$2"
      shift 2
      ;;
    --python-bin)
      PYTHON_BIN="$2"
      shift 2
      ;;
    --idle-vram-mb-per-gpu)
      IDLE_VRAM_MB_PER_GPU="$2"
      shift 2
      ;;
    --vram-wait-timeout-s)
      VRAM_WAIT_TIMEOUT_S="$2"
      shift 2
      ;;
    --request-timeout-s)
      REQUEST_TIMEOUT_S="$2"
      shift 2
      ;;
    --batch-timeout-s)
      BATCH_TIMEOUT_S="$2"
      shift 2
      ;;
    --output-root)
      OUTPUT_ROOT="$2"
      shift 2
      ;;
    --keep-last-lane)
      KEEP_LAST_LANE="1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

require_cmd curl
require_cmd jq
require_cmd nvidia-smi

controller_in_docker="0"
if detect_node_controller_container; then
  controller_in_docker="1"
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python executable not found or not executable: $PYTHON_BIN" >&2
  exit 1
fi

if [[ "$VLLM_BINARY" != "vllm" && "$controller_in_docker" != "1" && ! -x "$VLLM_BINARY" ]]; then
  echo "Configured --vllm-binary is not executable on host: $VLLM_BINARY" >&2
  echo "Use --vllm-binary vllm (recommended) or an absolute executable path." >&2
  exit 1
fi

if [[ ! -f "$SCRIPT_DIR/bench_lane_backends.py" ]]; then
  echo "Missing benchmark runner: $SCRIPT_DIR/bench_lane_backends.py" >&2
  exit 1
fi

if ! awk 'BEGIN { exit !('"$MEMORY_UTILIZATION"' > 0 && '"$MEMORY_UTILIZATION"' <= 1) }'; then
  echo "--memory-util must be in (0, 1], got: $MEMORY_UTILIZATION" >&2
  exit 1
fi

if ! curl -fsS "${CONTROLLER_URL%/}/health" >/dev/null; then
  echo "Node Controller health check failed at ${CONTROLLER_URL%/}/health" >&2
  exit 1
fi

preflight_vllm_runtime "$VLLM_BINARY"

echo "Clearing Node Controller lanes..."
clear_all_lanes
wait_for_empty_lanes 120

echo "Destroying managed Ollama (best effort) to release Node Controller resources..."
destroy_managed_ollama_best_effort

echo "Re-clearing lanes after Ollama destroy..."
clear_all_lanes
wait_for_empty_lanes 120

echo "Waiting for VRAM to become idle..."
wait_for_idle_vram "$IDLE_VRAM_MB_PER_GPU" "$VRAM_WAIT_TIMEOUT_S"

mem_tag="$(printf '%s' "$MEMORY_UTILIZATION" | tr '.' 'p')"
stamp="$(date -u +'%Y%m%d_%H%M%S')"
OUT_DIR="${OUTPUT_ROOT%/}/mem_${mem_tag}/${stamp}"
mkdir -p "$OUT_DIR"

payload_sample_count="$(tr ',' '\n' <<<"$CONCURRENCY" | awk 'NF {s += $1} END {print (s > 0 ? s : 1)}')"

echo "Running benchmark..."
echo "  output dir:   $OUT_DIR"
echo "  model:        $MODEL"
echo "  concurrency:  $CONCURRENCY"
echo "  memory util:  $MEMORY_UTILIZATION"

bench_cmd=(
  "$PYTHON_BIN" -u "$SCRIPT_DIR/bench_lane_backends.py"
  --controller-url "$CONTROLLER_URL"
  --api-key "$API_KEY"
  --output-dir "$OUT_DIR"
  --include-vllm
  --no-include-ollama
  --concurrency "$CONCURRENCY"
  --warmup "$WARMUP"
  --max-tokens "$MAX_TOKENS"
  --prompt-mode varied_unique_prefix
  --vllm-model "$MODEL"
  --vllm-binary "$VLLM_BINARY"
  --vllm-gpu-devices "$GPU_DEVICES"
  --tensor-parallel-size "$TENSOR_PARALLEL_SIZE"
  --max-model-len "$MAX_MODEL_LEN"
  --vllm-dtype float16
  --vllm-quantization none
  --vllm-gpu-memory-utilization "$MEMORY_UTILIZATION"
  --vllm-enforce-eager
  --vllm-prefix-caching-modes off
  --collect-gpu-memory
  --request-timeout-s "$REQUEST_TIMEOUT_S"
  --batch-timeout-s "$BATCH_TIMEOUT_S"
  --payload-sample-count "$payload_sample_count"
)

if [[ "$KEEP_LAST_LANE" == "1" ]]; then
  bench_cmd+=(--keep-last-lane)
fi

PYTHONUNBUFFERED=1 "${bench_cmd[@]}" | tee "$OUT_DIR/benchmark.log"

benchmark_json="$(latest_benchmark_json "$OUT_DIR")"
benchmark_csv="$(latest_file_for_pattern "$OUT_DIR" "lane_benchmark_*.csv")"
payload_json="$(latest_file_for_pattern "$OUT_DIR" "lane_benchmark_payloads_*.json")"

summary_csv="$OUT_DIR/summary_tokps_latency.csv"
summary_md="$OUT_DIR/summary_tokps_latency.md"
requests_csv="$OUT_DIR/requests_used.csv"

generate_summary_csv "$benchmark_json" "$summary_csv"
generate_summary_md "$benchmark_json" "$summary_md"
generate_requests_csv "$payload_json" "$requests_csv"

echo
echo "Benchmark completed."
echo "Artifacts:"
echo "  Benchmark JSON:   $benchmark_json"
echo "  Benchmark CSV:    $benchmark_csv"
echo "  Payload JSON:     $payload_json"
echo "  Summary CSV:      $summary_csv"
echo "  Summary Markdown: $summary_md"
echo "  Requests CSV:     $requests_csv"
