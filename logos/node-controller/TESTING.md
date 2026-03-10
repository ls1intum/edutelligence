# Node Controller Ops and Benchmark Runbook

This runbook is the operational reference for:
- managing Ollama and vLLM lanes from Node Controller,
- running repeatable backend benchmarks,
- collecting artifacts for throughput, latency, TTFT, and GPU memory.

Use this document with `RESEARCH_SUMMARY.md` for historical findings and interpretation.
For day-to-day lane operations and validated payload templates, see `LANES.md`.

## 1. Runtime Modes

Two valid deployment paths exist:
- Host `.venv` mode (recommended for vLLM benchmarking and lane experiments).
- Docker mode (controller containerized; useful for API smoke tests).

For benchmark work in this repository, use host `.venv` mode.

## 2. Host Preflight

```bash
cd /home/ge84ciq/node-controller-test/edutelligence/logos/node-controller
source .venv/bin/activate
```

Check controller config:

```bash
sed -n '1,220p' config.yml
```

Important defaults:
- Legacy Ollama endpoint: `ollama.port=11435`
- Lane range: `controller.lane_port_start=11436`, `lane_port_end=11499`

Verify no stale GPU pressure:

```bash
nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader
```

Optional cache/log cleanup (no model deletion):

```bash
rm -rf ~/.cache/pip ~/.cache/huggingface ~/.cache/flashinfer
sudo journalctl --vacuum-size=1G
```

## 3. Start Controller (Host `.venv`)

```bash
python -m node_controller.main
```

In another shell:

```bash
export API_KEY=RANDOM_DEFAULT_KEY
curl -s http://127.0.0.1:8444/health | jq .
curl -s -H "Authorization: Bearer $API_KEY" http://127.0.0.1:8444/status | jq .
curl -s -H "Authorization: Bearer $API_KEY" http://127.0.0.1:8444/admin/lanes | jq .
```

## 4. Lane Orchestration API

Apply vLLM lane (Qwen AWQ):

```bash
curl -s -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "lanes": [{
      "model": "Qwen/Qwen2.5-Coder-32B-Instruct-AWQ",
      "backend": "vllm",
      "context_length": 4096,
      "flash_attention": false,
      "gpu_devices": "0,1",
      "vllm": {
        "vllm_binary": "/home/ge84ciq/node-controller-test/edutelligence/logos/node-controller/.venv/bin/vllm",
        "tensor_parallel_size": 2,
        "max_model_len": 4096,
        "dtype": "float16",
        "quantization": "awq",
        "gpu_memory_utilization": 0.90,
        "enforce_eager": true,
        "enable_prefix_caching": true,
        "extra_args": []
      }
    }]
  }' \
  http://127.0.0.1:8444/admin/lanes/apply | jq .
```

Apply Ollama lane:

```bash
curl -s -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "lanes": [{
      "model": "qwen2.5-coder:32b",
      "backend": "ollama",
      "num_parallel": 8,
      "context_length": 4096,
      "keep_alive": "10m",
      "kv_cache_type": "q8_0",
      "flash_attention": true,
      "gpu_devices": "0,1"
    }]
  }' \
  http://127.0.0.1:8444/admin/lanes/apply | jq .
```

Inspect lanes and event history:

```bash
curl -s -H "Authorization: Bearer $API_KEY" http://127.0.0.1:8444/admin/lanes | jq .
curl -s -H "Authorization: Bearer $API_KEY" "http://127.0.0.1:8444/admin/lanes/events?limit=50" | jq .
```

Clear all lanes:

```bash
curl -s -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"lanes":[]}' \
  http://127.0.0.1:8444/admin/lanes/apply | jq .
```

## 5. Benchmark Execution

`bench_lane_backends.py` runs lane endpoints directly (not Logos scheduler), sequentially by backend so VRAM is not shared across backends.

### 5.1 Qwen Coder: vLLM vs Ollama

Varied/cache-hostile load:

```bash
python bench_lane_backends.py \
  --controller-url http://127.0.0.1:8444 \
  --api-key "$API_KEY" \
  --output-dir bench_results \
  --concurrency 1,4,8,16,32 \
  --warmup 1 \
  --max-tokens 200 \
  --prompt-mode varied_unique_prefix \
  --vllm-model Qwen/Qwen2.5-Coder-32B-Instruct-AWQ \
  --vllm-binary vllm \
  --vllm-quantization awq \
  --vllm-prefix-caching-modes off,on \
  --ollama-model qwen2.5-coder:32b \
  --ollama-num-parallel-values 1,4,8,16,32
```

Fixed/cache-friendly load:

```bash
python bench_lane_backends.py \
  --controller-url http://127.0.0.1:8444 \
  --api-key "$API_KEY" \
  --output-dir bench_results \
  --concurrency 1,4,8,16,32 \
  --warmup 1 \
  --max-tokens 200 \
  --prompt-mode fixed_shared_prefix \
  --vllm-model Qwen/Qwen2.5-Coder-32B-Instruct-AWQ \
  --vllm-binary vllm \
  --vllm-quantization awq \
  --vllm-prefix-caching-modes off,on \
  --ollama-model qwen2.5-coder:32b \
  --ollama-num-parallel-values 1,4,8,16,32
```

### 5.2 DeepSeek-R1-0528-Qwen3-8B (full precision) vLLM-only

Use this when validating memory floor and high concurrency:

```bash
python bench_lane_backends.py \
  --controller-url http://127.0.0.1:8444 \
  --api-key "$API_KEY" \
  --output-dir bench_results \
  --include-vllm --no-include-ollama \
  --vllm-model deepseek-ai/DeepSeek-R1-0528-Qwen3-8B \
  --vllm-binary vllm \
  --vllm-quantization none \
  --vllm-gpu-devices 0,1 \
  --tensor-parallel-size 2 \
  --vllm-dtype float16 \
  --vllm-gpu-memory-utilization 0.70 \
  --vllm-enforce-eager \
  --vllm-prefix-caching-modes off,on \
  --concurrency 32,64 \
  --warmup 1 \
  --max-tokens 200 \
  --prompt-mode varied_unique_prefix \
  --collect-gpu-memory
```

## 6. Output Artifacts

Each run writes:
- `bench_results/lane_benchmark_<timestamp>.json`
- `bench_results/lane_benchmark_<timestamp>.csv`
- `bench_results/lane_benchmark_payloads_<timestamp>.json`

Primary metrics:
- `aggregate_tok_s` (throughput),
- `avg_ttft_ms`,
- `p95_latency_s`,
- `error_rate`,
- `gpu_mem_peak_total_mb` and `gpu_mem_peak_per_gpu_mb`.

## 7. Plotting

Dual-load throughput/memory chart:

```bash
python plot_lane_benchmark_dual_loads.py \
  --varied bench_results/lane_benchmark_<varied>.json \
  --fixed bench_results/lane_benchmark_<fixed>.json \
  --output bench_results/qwen_coder_dual_loads_toks_mem.svg
```

Detailed clear report (throughput + latency in one SVG):

```bash
python plot_lane_benchmark_report.py \
  --input bench_results/lane_benchmark_<timestamp>.json \
  --output bench_results/qwen_coder_varied_clear_report.svg
```

## 8. Troubleshooting

`Lane apply failed: Could not find vLLM executable`
- Set explicit `vllm.vllm_binary` in lane config or CLI `--vllm-binary`.
- Controller now resolves in this order: configured path, `PATH`, interpreter sibling (`<venv>/bin/vllm`).

`Cannot find the config file for awq`
- You launched a full-precision model with AWQ quantization enabled.
- Use `--vllm-quantization none` (or lane `quantization: ""`).

`PermissionError` on `.../.hf_cache`
- Preferred cache path under Ollama model dir is not writable for current user.
- Controller falls back to `~/.cache/huggingface`.
- You can also export `HF_HOME` before starting controller.

`vLLM startup failed: Failed to find C compiler`
- vLLM/Triton may JIT-compile kernels and requires a compiler toolchain.
- Rebuild Node Controller image with `INSTALL_VLLM=1` (runtime now installs `build-essential`).
- `POST /admin/lanes/apply` now fails fast if vLLM lane startup fails, instead of leaving a stopped lane.

`vLLM worker failed: Could not find nvcc ... /usr/local/cuda ... doesn't exist`
- Containerized Node Controller cannot see CUDA toolkit (`nvcc`) from host.
- Mount host CUDA toolkit into container (for example `/usr/local/cuda-12.8:/usr/local/cuda-12.8:ro`).
- Set `CUDA_HOME` inside container (for example `/usr/local/cuda-12.8`) and restart (`./start.sh`).

No lane startup on expected port
- Check lane port range and collisions:
  - `controller.lane_port_start`
  - `controller.lane_port_end`
  - `ollama.port` must stay outside lane range
- Port allocator skips reserved ports and already-bound host ports.

## 9. API Quick Checks

Public:

```bash
curl -s http://127.0.0.1:8444/health | jq .
```

Authenticated:

```bash
curl -s -H "Authorization: Bearer $API_KEY" http://127.0.0.1:8444/status | jq .
curl -s -H "Authorization: Bearer $API_KEY" http://127.0.0.1:8444/gpu | jq .
curl -s -H "Authorization: Bearer $API_KEY" http://127.0.0.1:8444/models/loaded | jq .
curl -s -H "Authorization: Bearer $API_KEY" http://127.0.0.1:8444/models/available | jq .
curl -s -H "Authorization: Bearer $API_KEY" http://127.0.0.1:8444/config | jq .
```

Ollama management:

```bash
curl -s -X POST -H "Authorization: Bearer $API_KEY" http://127.0.0.1:8444/admin/ollama/start | jq .
curl -s -X POST -H "Authorization: Bearer $API_KEY" http://127.0.0.1:8444/admin/ollama/stop | jq .
curl -s -X POST -H "Authorization: Bearer $API_KEY" http://127.0.0.1:8444/admin/ollama/restart | jq .
curl -s -X POST -H "Authorization: Bearer $API_KEY" http://127.0.0.1:8444/admin/ollama/destroy | jq .
```

## 10. External `/ollama` HTTPS Request Flow

For a request like:

```bash
curl https://hochbruegge.aet.cit.tum.de/ollama/api/generate \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemma3:27b",
    "prompt": "Why is the sky blue?"
  }'
```

the handling path is:

1. Request hits `nginx` on `:443` (`hochbruegge.aet.cit.tum.de`).
2. Nginx matches `location /ollama/` in `/etc/nginx/sites-enabled/hochbruegge.aet.cit.tum.de:443.conf`.
3. Nginx proxies to `http://127.0.0.1:11434/` via:
   - `proxy_pass http://127.0.0.1:11434/;`
4. Because both location and proxy target end with `/`, URI `/ollama/api/generate` is forwarded upstream as `/api/generate`.
5. Upstream is the host `ollama.service` (systemd), listening on port `11434` (`OLLAMA_HOST=0.0.0.0:11434`).

So this request is handled by the host Ollama instance on `11434`, not the Node Controller-managed Ollama on `11435`.

Quick wiring view:

```text
Client
  -> https://hochbruegge.aet.cit.tum.de/ollama/api/generate
  -> nginx :443 (location /ollama/)
  -> proxy_pass http://127.0.0.1:11434/api/generate
  -> host ollama.service (PID from systemd, port 11434)
```

Related but separate Ollama endpoints on this VM:

- `11434`: host `ollama.service` (used by nginx `/ollama/` and Open WebUI config)
- `11435`: Node Controller-managed Ollama child process (used by Node Controller internals)
