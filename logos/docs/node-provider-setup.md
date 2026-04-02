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

## Configuration split

| Source | What | Managed by |
|---|---|---|
| `.env` | Credentials (`LOGOS_URL`, `LOGOS_API_KEY`) | GitHub secrets/variables |
| `config.yml` | Hardware & tuning (capabilities, vLLM overrides, NCCL/FlashInfer, port ranges) | Ansible |
| `/app/data/` | Runtime state (lane config, model profiles) | Auto-managed (Docker volume) |

No overlap between `.env` and `config.yml`.

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

## 3. Configure credentials (.env)

Copy `.env.example` to `.env` and fill in the required values:

```bash
cp .env.example .env
```

```dotenv
LOGOS_URL=https://logos.example.com
LOGOS_API_KEY=<shared_key from step 2>
```

That's it. The server resolves the provider identity from the API key.
In production, these are set as GitHub environment secrets and written to `.env` automatically by the deploy workflow.

## 4. Configure hardware (config.yml)

`config.yml` is managed by Ansible and contains hardware-specific settings:

```yaml
worker:
  gpu_poll_interval: 5
  lane_port_start: 11436
  lane_port_end: 11499

logos:
  enabled: true
  capabilities_models:
    - Qwen/Qwen2.5-Coder-7B-Instruct-AWQ
    - model: Qwen/Qwen2.5-Coder-14B-Instruct-AWQ
      tensor_parallel_size: 2

engines:
  vllm:
    nccl_debug: WARN
    nccl_debug_subsys: INIT
    model_overrides:
      Qwen/Qwen2.5-Coder-14B-Instruct-AWQ:
        quantization: awq
        disable_custom_all_reduce: true
```

**Do not** put credentials in `config.yml`. They come from `.env`.

## 5. Start the worker

```bash
docker compose up -d
```

## 6. Verify the local worker

```bash
curl http://localhost:8444/health
curl http://localhost:8444/admin/runtime
curl http://localhost:8444/admin/lanes
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
  Check `LOGOS_API_KEY` in `.env` — the server could not find a logosnode provider matching this key.

- **worker shows healthy locally but Logos reports offline**
  Check that `LOGOS_URL` is reachable from the worker host and that the URL is `https://`.

- **lane never becomes `loaded`**
  Call `GET /admin/runtime` and inspect `runtime.lanes[*].runtime_state`, `effective_vram_mb`, and `backend_metrics`.

- **`IsADirectoryError: /app/config.yml`**
  The `config.yml` file is missing on the host. Ansible must create it before the first deploy.
