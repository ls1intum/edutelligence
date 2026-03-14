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

## 8. Troubleshooting
- `400 TLS is required for logosnode auth/session endpoints`
  Enable TLS in front of Logos and configure the worker to use an `https://` `logos_url`. Logos auth/session endpoints are intended to stay TLS-only.
- worker shows healthy locally but Logos reports offline
  Check `logos.provider_id`, `logos.shared_key`, and that the worker can reach `logos.logos_url`.
- lane never becomes `loaded`
  Call `GET /admin/runtime` and inspect `runtime.lanes[*].runtime_state`, `effective_vram_mb`, and `backend_metrics`.
