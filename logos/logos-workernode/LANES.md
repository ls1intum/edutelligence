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
- For vLLM, the saved lane config `num_parallel` is still used by Logos as a scheduling-capacity hint.
- vLLM requires a working `nvidia-smi`. If any configured lane has `vllm: true` and `nvidia-smi` is unavailable, worker startup and lane apply/reconfigure now fail immediately.
- Without `nvidia-smi`, use Ollama lanes only. Derived-device mode is not accepted for vLLM anymore.

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

### Automatic sleep/wake (Capacity Planner)

When `LOGOS_CAPACITY_PLANNER_ENABLED=true` (default) on the Logos server, sleep and wake are managed automatically:

| Idle duration | Action | Scope |
|--------------|--------|-------|
| 5min | Sleep level 1 | vLLM lanes with sleep mode enabled |
| 10min in L1 sleep | Sleep level 2 | vLLM lanes already at level 1 |

Lanes are woken automatically when demand is detected (exponential-decay demand score >= 1.0). New lanes can also be loaded preemptively when demand score >= 2.0, subject to VRAM budget validation.

The background planner does not automatically stop/remove idle lanes. Lane removal happens only as reclaim when another request or load actually needs the VRAM.

For vLLM lanes, the planner also auto-tunes `gpu_memory_utilization`:
- Increases by 0.05 when KV cache usage > 85%
- Decreases by 0.05 when KV cache usage < 40% and another model needs VRAM

## Model profiles

The worker automatically measures memory footprints:
- **loaded_vram_mb**: observed loaded reservation for the whole lane
- **sleeping_residual_mb**: observed reservation while the lane is sleeping
- **base_residency_mb**: estimated floor for weights + runtime overhead
- **kv_budget_mb**: observed reservation above the base floor, used as the KV/cache budget

For vLLM, Logos does not blindly reuse `loaded_vram_mb` as the next load cost. It uses `base_residency_mb` plus a scaled `kv_budget_mb`, then chooses a lower or higher automatic `gpu_memory_utilization` target based on how large the model is relative to the provider VRAM budget.

Profiles update via exponential moving average (alpha=0.3) and persist in the state directory (`/app/data/model_profiles.yml`). They survive restarts and are sent to Logos every 5s so the capacity planner can validate VRAM budgets before loading or waking lanes.

Example persisted profiles (saved automatically to the state directory):
```yaml
model_profiles:
  gemma2:2b:
    loaded_vram_mb: 2048.5
    sleeping_residual_mb: 256.0
    disk_size_bytes: 1629516544
    base_residency_mb: 1700.0
    measurement_count: 12
  llama3.1:latest:
    loaded_vram_mb: 4812.3
    base_residency_mb: 4300.0
    kv_budget_mb: 512.0
    measurement_count: 3
```
