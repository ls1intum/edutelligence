# LogosWorkerNode Setup

This is the minimal local flow.

## 1. Start Logos locally
Expose Logos on `http://localhost:18080`.

## 2. Register the provider
```bash
curl -X POST http://localhost:18080/logosdb/providers/logosnode/register \
  -H 'Content-Type: application/json' \
  -d '{"logos_key":"<root_key>","provider_name":"kubaj-laptop-node","base_url":""}'
```

Save:
- `provider_id`
- `shared_key`

## 3. Connect a model to the provider
Use the normal Logos DB endpoints:
- `POST /logosdb/get_models`
- `POST /logosdb/connect_model_provider`
- `POST /logosdb/connect_profile_model`

## 4. Configure LogosWorkerNode
Edit [config.yml](/Users/kubaj/edutelligence/logos/logos-workernode/config.yml).

Required values:
- `logos.logos_url`
- `logos.provider_id`
- `logos.shared_key`
- `logos.worker_id`
- `lanes[]`

## 5. Start the worker
```bash
cd logos/logos-workernode
./start.sh
```

GPU-capable host:
```bash
./start.sh --gpu
```

## 6. Verify the local worker
```bash
curl http://localhost:8444/health
curl -H 'Authorization: Bearer <worker_api_key>' http://localhost:8444/admin/runtime
curl -H 'Authorization: Bearer <worker_api_key>' http://localhost:8444/admin/lanes
```

## 7. Verify the Logos session
```bash
curl -X POST http://localhost:18080/logosdb/providers/logosnode/status \
  -H 'Content-Type: application/json' \
  -d '{"logos_key":"<root_key>","provider_id":<provider_id>}'
```

## 8. Scheduling & Capacity Management

Once the worker is connected, Logos automatically uses two subsystems:

**ETTFT Scheduler** — re-ranks candidate models using estimated time-to-first-token. A loaded model with slightly lower classification weight beats a cold model that would take 30-90s to load. Disable with `LOGOS_SCHEDULER_ETTFT_ENABLED=false` on the Logos server.

**Capacity Planner** — background loop (30s cycles) that:
- Sleeps idle vLLM lanes after 60s of inactivity (level 1), then after 5min (level 2)
- Stops any lane idle for 15min
- Wakes sleeping lanes when demand is detected
- Tunes vLLM `gpu_memory_utilization` based on KV cache pressure
- Validates VRAM budgets before loading/waking (uses auto-calibrated model profiles from the worker)

Disable with `LOGOS_CAPACITY_PLANNER_ENABLED=false` on the Logos server.

Both are enabled by default. No worker-side configuration needed — VRAM profiles are measured automatically and sent via the existing heartbeat.

## 9. Troubleshooting
- `400 TLS is required for logosnode auth/session endpoints`
  Enable TLS in front of Logos and configure the worker to use an `https://` `logos_url`. Logos auth/session endpoints are intended to stay TLS-only.
- worker shows healthy locally but Logos reports offline
  Check `logos.provider_id`, `logos.shared_key`, and that the worker can reach `logos.logos_url`.
- lane never becomes `loaded`
  Call `GET /admin/runtime` and inspect `runtime.lanes[*].runtime_state`, `effective_vram_mb`, and `backend_metrics`.
