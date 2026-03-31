# LogosWorkerNode Setup

## How the connection works

The worker connects to the Logos server over a secure WebSocket (`wss://`).

1. On startup the worker POSTs its `provider_id` and `api_key` to the Logos auth endpoint.
2. If the credentials are valid the server issues a short-lived session token.
3. The worker opens a `wss://` connection using that token — the session is established.
4. If the credentials are wrong the server returns a 403 and the worker will not connect.

The worker only makes **outbound** connections; it does not need TLS certificates of its own.
TLS is terminated by the Logos server's reverse proxy (Traefik).

---

## 1. Start Logos

Start the Logos server and make sure it is reachable over HTTPS (e.g. `https://logos.example.com`).

## 2. Register the provider

```bash
curl -X POST https://logos.example.com/logosdb/providers/logosnode/register \
  -H 'Content-Type: application/json' \
  -d '{"logos_key":"<root_key>","provider_name":"my-worker-node","base_url":""}'
```

Save the response values — you will need both:
- `provider_id`
- `shared_key`  ← this is the provider API key

## 3. Configure the worker credentials

Copy `.env.example` to `.env` and fill in the three required values:

```bash
cp .env.example .env
```

```dotenv
LOGOS_URL=https://logos.example.com
LOGOS_PROVIDER_ID=<provider_id from step 2>
LOGOS_API_KEY=<shared_key from step 2>
LOGOS_WORKER_NODE_ID=my-worker-node   # optional, defaults to "worker-<id>"
```

These env vars are picked up by `start.sh` automatically and passed into the container.
**Do not** put these credentials in `config.yml`.

## 4. Configure models and engine settings

Edit [config.yml](../logos-workernode/config.yml) — set the worker name, capability model list,
and any engine overrides. Connection credentials are intentionally absent from this file.

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
curl -H 'Authorization: Bearer <worker.api_key from config.yml>' http://localhost:8444/admin/runtime
curl -H 'Authorization: Bearer <worker.api_key from config.yml>' http://localhost:8444/admin/lanes
```

## 7. Verify the Logos session

```bash
curl -X POST https://logos.example.com/logosdb/providers/logosnode/status \
  -H 'Content-Type: application/json' \
  -d '{"logos_key":"<root_key>","provider_id":<provider_id>}'
```

## 8. Connect a model to the provider

Use the normal Logos DB endpoints:
- `POST /logosdb/get_models`
- `POST /logosdb/connect_model_provider`
- `POST /logosdb/connect_profile_model`

## 9. Scheduling & Capacity Management

Once the worker is connected, Logos automatically uses two subsystems:

**ETTFT Scheduler** — re-ranks candidate models using estimated time-to-first-token. A loaded model with slightly lower classification weight beats a cold model that would take 30-90s to load. Disable with `LOGOS_SCHEDULER_ETTFT_ENABLED=false` on the Logos server.

**Capacity Planner** — background loop (30s cycles) that:
- Sleeps idle vLLM lanes after 5min of inactivity (level 1), then after 10min already in L1 sleep (level 2)
- Wakes sleeping lanes when demand is detected
- Reclaims lanes only when another request/load actually needs the VRAM
- Tunes vLLM `gpu_memory_utilization` based on KV cache pressure
- Validates VRAM budgets before loading/waking (uses auto-calibrated model profiles from the worker)

Disable with `LOGOS_CAPACITY_PLANNER_ENABLED=false` on the Logos server.

Both are enabled by default. No worker-side configuration needed.

## 10. Troubleshooting

- **`403` on startup / "Invalid provider shared key"**
  Check `LOGOS_API_KEY` in `.env` — it must match the `shared_key` from the registration response.

- **`404` / "Provider not found"**
  Check `LOGOS_PROVIDER_ID` in `.env`.

- **worker shows healthy locally but Logos reports offline**
  Check that `LOGOS_URL` is reachable from the worker host and that the URL is `https://`.

- **lane never becomes `loaded`**
  Call `GET /admin/runtime` and inspect `runtime.lanes[*].runtime_state`, `effective_vram_mb`, and `backend_metrics`.
