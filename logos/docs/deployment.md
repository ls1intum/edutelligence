# Logos deployment environments

Logos images are built by the `Logos - Build` workflow and pushed to the Harbor
registry (`${LOGOS_HARBOR_REGISTRY}/logos`). PR builds are tagged `pr-<number>`,
builds on `main` are tagged `latest`.

The vLLM worker image is always built on the first run of a PR (and when a PR is
reopened), which guarantees that its `pr-<number>` tag exists before a dev
deployment. On later PR updates, the workflow reuses that tag unless files in
the worker runtime (`logos_worker_node`), its copied tools, dependency list,
Dockerfile/build-context rules, or its build workflow changed since the last
successful worker build in that PR. Worker documentation, tests, research
results, Compose files, and host configuration do not trigger an image rebuild.
Pushes to `main` and releases continue to rebuild the worker image.

One exception: `logos-workernode-mlx` (Apple Silicon) is published to **public
GHCR** at `ghcr.io/ls1intum/logos-workernode-mlx` (org-level package, matching
the `build-workernode-mlx` job and the `bootstrap-macos.sh` default), so a Mac
can bootstrap without Harbor credentials. It is also the only image that is never
run as a container — see the MLX section below.

| Environment | Workflow | Trigger | Nodes (GitHub environments) |
|---|---|---|---|
| Prod | `Logos - Deploy to Prod` | auto after `Logos - Build` on `main`, or manual | `Logos - Prod`, `Logos Worker - Prod - deioma` |
| Test | `Logos - Deploy to Test` | manual (`workflow_dispatch`, image-tag input) | `Logos - Test`, `Logos Worker - Prod - deimama`, `Logos Worker - Prod - deipapa` |
| Dev | `Logos - Deploy to Dev` | manual (`workflow_dispatch`, image-tag input) | `Logos - Dev`, `Logos Worker - Test - hochbruegge` |

Each deploy job copies the docker compose file and a generated `.env` (all
environment vars/secrets except the SSH/registry plumbing) to the node and runs
`docker compose up -d` there. Core nodes use `logos/docker-compose.yaml` under
`/opt/logos`; worker nodes use `logos/logos-workernode/docker-compose.yml` under
`/opt/logos-workernode`.

## Security & rate limiting

The orchestrator's API surface is tiered:

- **User-facing** (`/v1`, `/openai`, `/jobs`) — any valid Logos API key.
- **Cluster-internal** (`/logosdb/scheduler_state`, `/internal/*`) — the shared
  `LOGOS_INTERNAL_SECRET`, never a user key. `/logosdb/scheduler_state` used
  to accept any Logos API key and was publicly routed; it is now secret-gated
  and only reachable from inside the stack (the agent runner polls it).
- **Operator** (`/logosdb/providers/logosnode/*`) — the root key, TLS only.
- **Monitoring** (`/metrics`) — `PROMETHEUS_API_KEY`; denies all when unset.

The API docs (`/docs`, `/redoc`, `/openapi.json`) publish the full endpoint map
and are **off by default**; set `LOGOS_DOCS_ENABLED=1` in `.env` only where
needed (the dev compose enables it).

### In-stack rate limits (Traefik)

Both compose files attach generous Traefik `rateLimit` middleware to the
API routers (429 when exceeded). The higher-priority routers that actually
serve `/api/*` (webservice, agent, the logosnode operator paths) carry the
limiter alongside their strip-prefix middleware, so no request reaches a
service unthrottled:

| Middleware | Routers | Default (avg rps / burst) |
|---|---|---|
| `rl-model` | `/v1`, `/openai`, and the orchestrator's `/api` fallback | 100 / 200 |
| `rl-jobs` | `/jobs` | 50 / 100 |
| `rl-admin` | `/health`, `/docs`, `/metrics`, `/logosdb/providers/logosnode`, and the higher-priority `/api/*` routers (webservice identity/config/admin/WebSocket, logosnode operator actions, agent) | 20 / 40 |

Tune per deployment via `.env`: `LOGOS_RATE_LIMIT_MODEL_AVG`,
`LOGOS_RATE_LIMIT_MODEL_BURST`, `LOGOS_RATE_LIMIT_JOBS_AVG`,
`LOGOS_RATE_LIMIT_JOBS_BURST`, `LOGOS_RATE_LIMIT_ADMIN_AVG`,
`LOGOS_RATE_LIMIT_ADMIN_BURST`. Note Traefik counts requests **per service,
not per client IP** — this layer stops floods, it does not isolate one
abusive client. The dev compose uses higher defaults (500/1000, 250/500,
100/200) so local benchmarking is not throttled.

Per-API-key request budgets on the model paths are enforced inside the
orchestrator (per key's configured `cloud_rl`/`local_rl`); the in-stack limits
are the backstop for unauthenticated or leaked-key abuse.

### Per-IP limits in the nginx in front

The stack sits behind the chair's nginx ingress, which is the right place for
per-client limiting (Traefik cannot do it natively). Recommended snippet for
the server/location that proxies to a Logos core node:

```nginx
# Per-client flood protection for the Logos API. Generous on purpose:
# real clients (coding assistants, benchmark drivers) stay far below these
# rates; this is a brake, not a budget.
limit_req_zone $binary_remote_addr zone=logos_api:10m rate=30r/s;
limit_req_zone $binary_remote_addr zone=logos_burst:10m rate=5r/s;

server {
    # ...
    location / {
        proxy_pass http://logos-core:443;
        # Model API: one assistant session bursts at most a few requests per
        # second at startup; 30 r/s per IP with a small burst headroom.
        limit_req zone=logos_api burst=60 nodelay;
    }
    # Control-plane paths (jobs, admin, docs, metrics) are hammered far less.
    location ~ ^/(jobs|api|docs|metrics|health)(/|$) {
        proxy_pass http://logos-core:443;
        limit_req zone=logos_burst burst=20 nodelay;
    }
}
```

Adjust the zones/rates to the deployment's traffic; `limit_req_status 429;`
keeps the status code aligned with the in-stack limits.

## Apple Silicon (MLX) worker nodes

MLX nodes do not follow the compose-based deploy path above, because Metal
cannot be passed into a container: Docker on macOS runs a Linux VM with no GPU
passthrough, so a containerised lane would silently fall back to the CPU.

Instead the image is a distribution artifact. On the Mac,
`scripts/bootstrap-macos.sh` pulls it, extracts the payload with `docker cp`
to `~/logos-workernode-mlx`, and runs the worker natively under a launchd
agent. Running natively is also what keeps the orchestrator in control — a
native process can fork `vllm serve` on command, which a container could not.

Deploying a new version means re-running the bootstrap script on the node; it
is idempotent and preserves `config.yml`, `.env` and `data/`. There is no
`Logos - Deploy` job for these nodes yet.

The orchestrator treats them as ordinary vLLM workers — no protocol change was
needed. Sleep/wake is unavailable (it requires CUDA virtual memory), so the
server reclaims memory by stopping and restarting lanes instead.

Full setup, sizing and troubleshooting: `logos/logos-workernode/MACOS.md`.

## Required configuration per GitHub environment

Repository-level (already configured): `LOGOS_HARBOR_REGISTRY`,
`LOGOS_HARBOR_USER` (vars), `LOGOS_HARBOR_PASSWORD` (secret), and the
`DEPLOYMENT_GATEWAY_*` vars/secrets inherited from the organization.

### Core node (e.g. `Logos - Dev`)

Variables:

- `VM_HOST`, `VM_USERNAME` — target VM and SSH user
- `LOGOS_DOMAIN`, `LOGOS_CERT_RESOLVER`, `LOGOS_CORS_ALLOWED_ORIGINS`, `ACME_EMAIL`
- `KEYCLOAK_ADMIN_BASE_URL`, `KEYCLOAK_AUDIENCE`, `KEYCLOAK_CLIENT_ID`,
  `KEYCLOAK_ISSUER_URI`, `KEYCLOAK_JWKS_URI`, `KEYCLOAK_ROLES_APP_ADMIN`,
  `KEYCLOAK_ROLES_LOGOS_ADMIN`, `KEYCLOAK_SYNC_CLIENT_ID`,
  `KEYCLOAK_SYNC_ENABLED`, `KEYCLOAK_TEAM_ROLE_SUFFIXES`

Secrets:

- `VM_SSH_PRIVATE_KEY`
- `LOGOS_INTERNAL_SECRET`
- `KEYCLOAK_SYNC_CLIENT_SECRET`
- `PROMETHEUS_API_KEY`

### Worker node (e.g. `Logos Worker - Test - hochbruegge`)

Variables:

- `VM_HOST`, `VM_USERNAME` — target GPU node and SSH user
- `LOGOS_URL` — URL of the core node's orchestrator this worker registers with
- `LOGOS_TMPFS_CACHE_PATH`, `TMPFS_SIZE`, `LOGOS_MODELS_MOUNT`

Secrets:

- `VM_SSH_PRIVATE_KEY`
- `LOGOS_API_KEY` — key the worker uses to authenticate against the orchestrator
- `HF_TOKEN`
