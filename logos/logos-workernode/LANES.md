# Lane Guide

Each lane is one model-serving process.

## Lane shape
```yaml
lanes:
  - lane_id: gemma2-2b-l1
    model: gemma2:2b
    vllm: false
    num_parallel: 4
    context_length: 4096
    keep_alive: 5m
    kv_cache_type: q8_0
    flash_attention: true
    gpu_devices: ""
```

vLLM lane:
```yaml
lanes:
  - lane_id: qwen3-8b-v1
    model: Qwen/Qwen3-8B
    vllm: true
    context_length: 8192
    gpu_devices: "0"
    vllm_config:
      tensor_parallel_size: 1
      gpu_memory_utilization: 0.9
      enable_prefix_caching: true
      enable_sleep_mode: true
```

Notes:
- `num_parallel`, `keep_alive`, `kv_cache_type`, and `flash_attention` are Ollama-lane settings.
- vLLM lanes use continuous batching, so runtime status reports `num_parallel: 0` for `vllm: true`.

## Runtime states
- `cold`: process exists but the model is not warm
- `starting`: process spawn or preload in progress
- `loaded`: warm and idle
- `running`: serving at least one request
- `sleeping`: vLLM sleep mode engaged
- `stopped`: process not running
- `error`: unhealthy lane

## Local admin API
- `GET /health`
- `GET /admin/runtime`
- `GET /admin/lanes`
- `GET /admin/lanes/events`
- `GET /admin/lanes/{lane_id}`
- `POST /admin/lanes/apply`
- `PATCH /admin/lanes/{lane_id}`
- `POST /admin/lanes/{lane_id}/sleep`
- `POST /admin/lanes/{lane_id}/wake`
- `DELETE /admin/lanes/{lane_id}`

## Apply lanes
```bash
curl -X POST http://localhost:8444/admin/lanes/apply \
  -H 'Authorization: Bearer <worker_api_key>' \
  -H 'Content-Type: application/json' \
  -d '{"lanes":[{"lane_id":"gemma2-2b-l1","model":"gemma2:2b","vllm":false}]}'
```

## Sleep and wake
Only vLLM lanes with `vllm_config.enable_sleep_mode=true` support sleep.

Sleep requests take a JSON body:
```bash
curl -X POST http://localhost:8444/admin/lanes/qwen3-8b-v1/sleep \
  -H 'Authorization: Bearer <worker_api_key>' \
  -H 'Content-Type: application/json' \
  -d '{"level":1,"mode":"wait"}'
```
