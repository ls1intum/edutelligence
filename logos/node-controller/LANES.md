# Lane Operations Guide

This guide is the operator-facing reference for Node Controller lane mode.

## 1. What a lane is

A lane is one isolated inference process dedicated to one model:
- `backend: "ollama"` => one Ollama server process with fixed `num_parallel` slots.
- `backend: "vllm"` => one vLLM server process with continuous batching (dynamic concurrency).

Node Controller applies lanes declaratively via `POST /admin/lanes/apply`.

## 2. Quick start (Docker, no host venv)

```bash
cd /home/ge84ciq/node-controller-test/edutelligence/logos/node-controller
./start.sh
```

`./start.sh` auto-creates `.env` on first run and builds with bundled `ollama` + `vllm` by default.
It prints `Ollama lanes`, `vLLM lanes`, `C compiler`, and `CUDA nvcc`.
For reliable vLLM lane startup, `vLLM lanes`, `C compiler`, and `CUDA nvcc` should be `true`.

## 3. Core lane workflow

In another shell:

```bash
export API_KEY=RANDOM_DEFAULT_KEY
export CTRL=http://127.0.0.1:8444

curl -s "$CTRL/health" | jq .
curl -s -H "Authorization: Bearer $API_KEY" "$CTRL/admin/lanes/templates" | jq .
```

Apply desired lanes:

```bash
curl -s -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"lanes":[]}' \
  "$CTRL/admin/lanes/apply" | jq .
```

Check active lanes:

```bash
curl -s -H "Authorization: Bearer $API_KEY" "$CTRL/admin/lanes" | jq .
```

Check lane transition history:

```bash
curl -s -H "Authorization: Bearer $API_KEY" "$CTRL/admin/lanes/events?limit=100" | jq .
```

Clear all lanes:

```bash
curl -s -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"lanes":[]}' \
  "$CTRL/admin/lanes/apply" | jq .
```

## 4. Example payloads

### 4.1 Single Ollama lane

```json
{
  "lanes": [
    {
      "model": "qwen2.5-coder:32b",
      "backend": "ollama",
      "num_parallel": 8,
      "context_length": 4096,
      "keep_alive": "10m",
      "kv_cache_type": "q8_0",
      "flash_attention": true,
      "gpu_devices": "0,1"
    }
  ]
}
```

### 4.2 Single vLLM lane

```json
{
  "lanes": [
    {
      "model": "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
      "backend": "vllm",
      "context_length": 4096,
      "flash_attention": true,
      "gpu_devices": "0,1",
      "vllm": {
        "vllm_binary": "vllm",
        "tensor_parallel_size": 2,
        "max_model_len": 4096,
        "dtype": "float16",
        "quantization": "",
        "gpu_memory_utilization": 0.70,
        "enforce_eager": true,
        "enable_prefix_caching": true,
        "disable_custom_all_reduce": false,
        "disable_nccl_p2p": false,
        "enable_sleep_mode": false,
        "server_dev_mode": false,
        "extra_args": []
      }
    }
  ]
}
```

### 4.3 Mixed lanes (Ollama + vLLM)

```json
{
  "lanes": [
    {
      "model": "qwen2.5-coder:32b",
      "backend": "ollama",
      "num_parallel": 8,
      "context_length": 4096,
      "keep_alive": "10m",
      "kv_cache_type": "q8_0",
      "flash_attention": true,
      "gpu_devices": "0"
    },
    {
      "model": "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
      "backend": "vllm",
      "context_length": 4096,
      "flash_attention": true,
      "gpu_devices": "1",
      "vllm": {
        "tensor_parallel_size": 1,
        "gpu_memory_utilization": 0.70,
        "enforce_eager": true,
        "enable_prefix_caching": true,
        "extra_args": []
      }
    }
  ]
}
```

## 5. Validation rules (important)

Node Controller now rejects invalid lane payloads early:
- `backend` must be exactly `"ollama"` or `"vllm"`.
- `gpu_devices` must be one of:
  - `"all"`
  - `"none"`
  - comma-separated integers like `"0,1"`
  - empty string (`""`, inherit global)
- Duplicate lanes (same normalized model lane-id) are rejected.
- `backend: "ollama"` cannot include custom `vllm` settings.
- For `backend: "vllm"`, `tensor_parallel_size` cannot exceed explicit lane GPU count when `gpu_devices` is set.

## 6. Stability controls for vLLM lanes

In `lanes[].vllm`:
- `disable_custom_all_reduce: true`
  - Adds `--disable-custom-all-reduce`.
  - May improve stability on some driver/NCCL setups.
  - Can reduce throughput depending on topology.
- `disable_nccl_p2p: true`
  - Sets `NCCL_P2P_DISABLE=1`.
  - Sometimes avoids NCCL hangs.
  - Can hurt multi-GPU bandwidth.
- `enable_sleep_mode: true`
  - Adds `--enable-sleep-mode` (sleep/wake APIs).
- `server_dev_mode: true`
  - Sets `VLLM_SERVER_DEV_MODE=1` (required for some dev endpoints).

## 7. Benchmark recipe: memory-floor sweep at concurrency 32/64/128

Use repeated runs with decreasing vLLM memory utilization:

```bash
for util in 0.70 0.65 0.60 0.55 0.50; do
  python bench_lane_backends.py \
    --controller-url "$CTRL" \
    --api-key "$API_KEY" \
    --output-dir bench_results/mem_sweep \
    --include-vllm --no-include-ollama \
    --vllm-model deepseek-ai/DeepSeek-R1-0528-Qwen3-8B \
    --vllm-binary vllm \
    --vllm-quantization none \
    --vllm-gpu-devices 0,1 \
    --tensor-parallel-size 2 \
    --vllm-dtype float16 \
    --vllm-gpu-memory-utilization "$util" \
    --vllm-enforce-eager \
    --vllm-prefix-caching-modes off,on \
    --concurrency 32,64,128 \
    --warmup 1 \
    --max-tokens 200 \
    --prompt-mode varied_unique_prefix \
    --collect-gpu-memory

done
```

Interpretation guidance:
- If a utilization value starts and survives 128 concurrency without OOM, KV cache was allocated sufficiently for that configuration.
- Still run a longer soak (20-60 min) at your target concurrency mix to catch fragmentation/drift issues not visible in a short burst.

## 8. Troubleshooting

Check lane errors:

```bash
curl -s -H "Authorization: Bearer $API_KEY" "$CTRL/admin/lanes/events?limit=200" | jq .
```

Force-stop stale worker processes if required:

```bash
pkill -f "vllm serve"
pkill -f "ollama serve"
```

Verify GPU memory and process holders:

```bash
nvidia-smi
```
