# Quickstart

## 1. Prepare Logos
1. Run Logos on `http://localhost:18080`.
2. Register a provider with `provider_type=logosnode`.
3. Save `provider_id` and `shared_key`.
4. Connect at least one Logos model to that provider.

### Scheduling configuration (optional)

Logos uses ETTFT-aware scheduling and a background capacity planner by default. Both are on with zero configuration. To disable either subsystem, set env vars on the Logos server:

| Variable | Default | Effect when `false` |
|----------|---------|-------------------|
| `LOGOS_SCHEDULER_ETTFT_ENABLED` | `true` | Scheduler uses raw classification weights (no latency penalties) |
| `LOGOS_CAPACITY_PLANNER_ENABLED` | `true` | Background planner does not start (no automatic sleep/wake/stop) |

## 2. Configure the worker
Edit [config.yml](config.yml).

Required fields:
- `worker.api_key`: local admin token
- `logos.logos_url`
- `logos.provider_id`
- `logos.shared_key`
- `logos.worker_id`
- `lanes[]`

For Ollama lanes:
- set `vllm: false`

For vLLM lanes:
- set `vllm: true`
- add `vllm_config`
- ensure `nvidia-smi` works on the worker host before startup

Important:
- `nvidia-smi` is mandatory for vLLM mode.
- If any configured lane uses `vllm: true` and `nvidia-smi` is unavailable, LogosWorkerNode now fails startup with a clear error instead of running with optimistic VRAM accounting.

### Model profiles (automatic)

The worker automatically measures each model's VRAM footprint after loading and sleeping, then persists profiles in `config.yml` under a `model_profiles` section. These profiles are sent to Logos on every heartbeat (5s) so the capacity planner can make VRAM-safe decisions. No manual configuration needed — profiles build up over time and survive restarts.

## 3. Start it
Local dev:
```bash
./start.sh
```

GPU mode:
```bash
./start.sh --gpu
```

## 4. Verify local admin
```bash
curl http://localhost:8444/health
curl -H 'Authorization: Bearer <worker_api_key>' http://localhost:8444/admin/runtime
curl -H 'Authorization: Bearer <worker_api_key>' http://localhost:8444/admin/lanes
```

## 5. Verify Logos session
From Logos, call:
```bash
curl -X POST http://localhost:18080/logosdb/providers/logosnode/status \
  -H 'Content-Type: application/json' \
  -d '{"logos_key":"<root_key>","provider_id":<provider_id>}'
```

A healthy response contains:
- `worker_id`
- `capabilities_models`
- `runtime.devices`
- `runtime.capacity`
- `runtime.lanes`
- `model_profiles` (populated after first lane load)
