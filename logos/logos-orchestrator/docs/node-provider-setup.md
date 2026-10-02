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

Start the Logos server and make sure it is reachable over HTTPS (e.g. `https://logos.aet.cit.tum.de`).

## 2. Register the provider

```bash
curl -X POST https://logos.aet.cit.tum.de/logosdb/providers/logosnode/register \
  -H 'Content-Type: application/json' \
  -d '{"logos_key":"<root_key>","provider_name":"my-worker-node","base_url":"","privacy_level":"LOCAL"}'
```

`privacy_level` is required and states how far this node may be trusted with
data. There is deliberately no default:

| Value | Use for |
|-------|---------|
| `LOCAL` | Hardware you operate — your own datacentre. The most trusted tier. |
| `THIRD_PARTY_HARDWARE` | Hardware outside your control: a rented GPU, or a personal machine running the MLX worker. Its owner can inspect the running processes. |

Registering a rented or personal machine as `LOCAL` makes it eligible for
requests that are restricted to operator-controlled hardware, so pick the tier
that matches reality rather than the one that unblocks the setup.

Save the response values — you will need both:
- `provider_id`
- `shared_key`  ← this is the provider API key

## 3. Configure credentials (.env)

If you are following this guide from a repository checkout, enter the
worker directory first — the Compose file, `.env` and `config.yml` all live
there (in production deployments it is already the working directory):

```bash
cd logos/logos-workernode
```

Copy `.env.example` to `.env` and fill in the required values:

```bash
cp .env.example .env
```

```dotenv
LOGOS_URL=https://logos.aet.cit.tum.de
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

(From the worker directory entered in step 3.) The production Compose file
pulls `${REGISTRY}/logos-workernode-vllm` from
the project's registry (Harbor for team deployments — set `REGISTRY` and
`IMAGE_TAG` in `.env` and log in). Without registry access, build the image
first (this directory is the build context). Put the values in `.env` and
export them in the shell as well — the Docker CLI does not read `.env`:

```bash
export REGISTRY=<your-registry> IMAGE_TAG=<tag>
docker build -t "$REGISTRY/logos-workernode-vllm:$IMAGE_TAG" .
```

Then start the worker:

```bash
docker compose up -d
```

## 6. Verify the local worker

The worker API only exposes its root (plus FastAPI's `/docs`); it has no
`/health` or `/admin/*` endpoints. Runtime state is pushed to Logos over the
outbound session — check it on the server side in step 7:

```bash
# Service info (the production worker listens on port 80)
curl http://localhost:80/
```

## 7. Verify the Logos session

```bash
curl -X POST https://logos.aet.cit.tum.de/logosdb/providers/logosnode/status \
  -H 'Content-Type: application/json' \
  -d '{"logos_key":"<root_key>","provider_id":<provider_id>}'
```

## 8. Connect a model to the provider

Use the Logos UI (Providers → connect model) or the webservice's admin API
(`/api/logosdb/connect_model_provider`, Keycloak-authenticated — the
orchestrator no longer exposes these paths with a plain API key).

## 9. Scheduling & Capacity Management

Once the worker is connected, Logos automatically uses the Capacity Planner subsystem:

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
  Call `POST /logosdb/providers/logosnode/status` (step 7) and inspect `runtime.lanes[*].runtime_state`, `effective_vram_mb`, and `backend_metrics` in the returned snapshot.

- **`IsADirectoryError: /app/config.yml`**
  The `config.yml` file is missing on the host. Ansible must create it before the first deploy.
