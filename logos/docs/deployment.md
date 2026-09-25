# Logos deployment

Logos deploys pull-based. Prebuilt images are published to the public GHCR
registry `ghcr.io/ls1intum/edutelligence` — `latest` tracks `main`, and a
pinned tag pins a specific build. A deployment is the compose file plus a
`.env` on each node, and an update is `docker compose pull` and
`docker compose up -d`. Nothing is pushed to a node from CI, and a worker
node needs no inbound port at all (see the
[architecture overview](developer/architecture) for the subsystem
breakdown).

A deployment consists of:

- One **core node** running the core stack: Traefik, the rate-limit gateway,
  orchestrator, web service, UI, and PostgreSQL.
- Zero or more **worker nodes** — GPU machines that run local vLLM models
  and connect out to the core node (see the
  [worker node guide](admin/worker-node.md)).
- Optionally, the **agent stack** on the core node, which runs coding agents
  on spare serving capacity (see the
  [agent runner reference](https://github.com/ls1intum/edutelligence/blob/main/logos/logos-agent/README.md)).
  It is opt-in: enable it with `COMPOSE_PROFILES=agent`.

## Images and registry

| Image | Contents |
|---|---|
| `logos` | orchestrator |
| `logos-webservice` | Spring admin/statistics service and public inference gateway (`/v1`, `/openai`, `/jobs`) |
| `logos-ui` | Angular frontend |
| `logos-db` | PostgreSQL 17 plus `pg_cron` |
| `logos-rate-gateway` | per-IP rate limiting (nginx) |
| `logos-agent`, `logos-agent-gateway`, `logos-agent-workspace` | the agent stack (only with the `agent` profile) |
| `logos-workernode-vllm` | the worker node runtime (on the GPU host) |
| `logos-workernode-mlx` | the Apple Silicon worker — published to **public GHCR** at `ghcr.io/ls1intum/logos-workernode-mlx`, and the only image that is never run as a container (see the MLX section below) |

`REGISTRY` (default `ghcr.io/ls1intum/edutelligence`) and `IMAGE_TAG`
(default `latest`) in the `.env` select the source. The public registry needs
no login; a deployment with a private mirror sets `REGISTRY` and logs in once
(`docker login`).

## Updating

The core node updates in place:

```bash
# in the .env next to docker-compose.yaml
IMAGE_TAG=<new tag>   # or keep "latest"
```

```bash
docker compose --env-file .env pull
docker compose --env-file .env up -d
```

The web service applies pending Liquibase migrations at startup, so a version
jump is a normal event. Back up the persistent volumes first (see the
[installation guide](admin/installation.md#persistent-data-and-upgrades)).

Worker nodes update the same way from their worker directory: bump
`IMAGE_TAG` in the worker's `.env`, then `docker compose pull` and
`docker compose up -d`. Lane configuration and calibrated model profiles
persist in the worker's `data/` volume, so an update does not reset them.

## Security & rate limiting

The orchestrator's API surface is tiered:

- **User-facing** (`/v1`, `/openai`, `/jobs`) — any valid Logos API key.
  Traefik sends these to **logos-webservice** (inference gateway). Pure-cloud
  named-model requests are answered there; local/logosnode and mixed traffic
  is reverse-proxied to the orchestrator on the compose network.
- **Cluster-internal** (`/logosdb/scheduler_state`, `/internal/*`) — the shared
  `LOGOS_INTERNAL_SECRET`, never a user key. `/logosdb/scheduler_state` used
  to accept any Logos API key and was publicly routed; it is now secret-gated
  and only reachable from inside the stack (the agent runner polls it).
- **Operator** (`/logosdb/providers/logosnode/*`) — the root key, TLS only.
- **Monitoring** (`/metrics`) — `PROMETHEUS_API_KEY`; denies all when unset.

The API docs (`/docs`, `/redoc`, `/openapi.json`) publish the full endpoint map
and are **off by default**; set `LOGOS_DOCS_ENABLED=1` in `.env` only where
needed (the dev compose enables it).

### Layer 1: per-IP limits (nginx rate gateway, in-stack)

Every public request (443 and 8080) first passes the `logos-rate-gateway`
container — an nginx that enforces a request budget **per client IP**,
which Traefik cannot do natively (its `rateLimit` middleware counts per
service, not per client). Only then does the gateway forward to Traefik's
*internal* entrypoint (`:8090`, no published host port), where the normal
routers apply. TLS is terminated at the public entrypoint and re-signalled
via `X-Forwarded-Proto`, so services still see `https`.

Two budget classes, both answered with 429 when exceeded:

| Class | Paths | Default (avg rps / burst) |
|---|---|---|
| model | `/v1`, `/openai`, `/logosdb/...`, the UI, everything else | 30 / 60 |
| control | `/jobs`, `/api`, `/docs`, `/metrics`, `/health`, `/ws` | 5 / 20 |

Tune per deployment in the node's `.env` (all optional):

- `LOGOS_IP_RATE_LIMIT_AVG` / `LOGOS_IP_RATE_LIMIT_BURST` — the model budget.
- `LOGOS_IP_CONTROL_RATE_LIMIT_AVG` / `LOGOS_IP_CONTROL_RATE_LIMIT_BURST` —
  the control-plane budget.
- `LOGOS_RATE_LIMIT_WHITELISTED_IPS` — frees specific IPs from **all**
  limits, e.g. the chair's benchmark rig or an office egress IP. Space-
  separated IPv4 addresses and CIDRs:

  ```env
  # .env on the core node
  LOGOS_RATE_LIMIT_WHITELISTED_IPS="129.79.32.0/20 1.2.3.4"
  ```

  Malformed entries are skipped with a line in `docker logs
  logos-rate-gateway` — a typo in the `.env` degrades to "no whitelist",
  it cannot crash-loop the gateway (and with it the whole stack).
- `LOGOS_GATEWAY_TRUSTED_PROXY_CIDRS` — the source ranges allowed to carry
  `X-Forwarded-For`. Defaults to `172.16.0.0/12` (the Docker bridge
  ranges), which matches no public client, so a header forged from the
  internet is stripped before it reaches the gateway. **If the node sits
  behind the chair's nginx (or any other reverse proxy), add that proxy's
  CIDR here too** — otherwise every client counts as that one proxy IP and
  the per-IP isolation is lost. **Comma-delimited**: the value is passed
  straight to Traefik's `--forwardedHeaders.trustedIPs`, whose CLI expects a
  comma list — a space-delimited value would leave the outer proxy untrusted
  (or invalidate Traefik's static config). The in-stack nginx gateway
  normalises commas to spaces itself, so the same value works for both:

  ```env
  LOGOS_GATEWAY_TRUSTED_PROXY_CIDRS="172.16.0.0/12,129.79.32.0/20"
  ```

  This value covers the **public** entrypoints only. The gateway → Traefik
  hop has its own list (below), so replacing the default here can never cut
  the in-stack chain.
- `LOGOS_INTERNAL_HOP_TRUSTED_CIDRS` — the sources trusted on the internal
  entrypoint (`:8090`), i.e. the rate gateway. Defaults to the private
  address space (`10.0.0.0/8,172.16.0.0/12,192.168.0.0/16`) because the
  gateway's address comes from Docker's network pool and is not necessarily
  a `172.16.0.0/12` one. Leave it alone unless the stack's networks are
  pinned to known subnets; the entrypoint has no published host port, so
  only containers of this stack can reach it.
- `LOGOS_GATEWAY_UPSTREAM` — where the gateway forwards (default
  `traefik:8090`); only change if the internal entrypoint moves.

**Symptom to watch for:** if the internal hop is not trusted, Traefik
rewrites the gateway's `X-Forwarded-Proto` to `http` and every service
loses the TLS signal. The loudest consequence is worker nodes failing to
attach in a loop:

```text
BRIDGE ERROR ══ /auth rejected with HTTP 400:
{"error":{"message":"TLS is required for logosnode auth/session endpoints ...
```

The 400 body names the scheme and `X-Forwarded-Proto` the orchestrator
actually saw. Verify the chain with the gateway's address and the trusted
list:

```bash
docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' logos-rate-gateway
docker inspect traefik | grep -- '--entrypoints.internal8090.forwardedHeaders'
```

The dev compose runs the same gateway with looser defaults (300/600 and
50/100) so local benchmarking is not throttled; the direct ports 18080 and
18082 bypass it entirely (debugging).

### Layer 2: per-service limits (Traefik)

Both compose files attach generous Traefik `rateLimit` middleware to the
API routers (429 when exceeded). These count per service rather than per
client — they cap one service even when many IPs share the same key, which
the per-IP layer above cannot see. The higher-priority routers that actually
serve `/api/*` (webservice, agent, the logosnode operator paths) carry the
limiter alongside their strip-prefix middleware, so no request reaches a
service unthrottled:

| Middleware | Routers | Default (avg rps / burst) |
|---|---|---|
| `rl-model` | `/v1`, `/openai` | 100 / 200 |
| `rl-jobs` | `/jobs` | 50 / 100 |
| `rl-admin` | `/health`, `/docs`, `/metrics`, `/logosdb/providers/logosnode`, the orchestrator's `/api` fallback, and the higher-priority `/api/*` routers (webservice identity/config/admin/WebSocket, logosnode operator actions, agent) | 20 / 40 |

The limiters are defined on the Traefik container itself, not on one of
the services: every app container references at least one of them, so
they must survive any single service's restarts (the same reason
`strip-api` lives there).

Tune per deployment via `.env`: `LOGOS_RATE_LIMIT_MODEL_AVG`,
`LOGOS_RATE_LIMIT_MODEL_BURST`, `LOGOS_RATE_LIMIT_JOBS_AVG`,
`LOGOS_RATE_LIMIT_JOBS_BURST`, `LOGOS_RATE_LIMIT_ADMIN_AVG`,
`LOGOS_RATE_LIMIT_ADMIN_BURST`. The dev compose uses higher defaults
(500/1000, 250/500, 100/200) so local benchmarking is not throttled.

Per-API-key request budgets on the model paths are enforced inside the
orchestrator (per key's configured `cloud_rl`/`local_rl`); the in-stack limits
are the backstop for unauthenticated or leaked-key abuse.

### Optional: an additional per-client brake in the nginx in front

The stack no longer *needs* per-client limits in the chair's nginx ingress —
they now live in the stack and travel with the deployment. If you still want
a second brake there (to protect other vhosts on the same box, or to shed a
flood before it reaches the node's IP at all), the same nginx pattern
applies:

```nginx
# Per-client flood protection for the Logos API. Generous on purpose:
# real clients (coding assistants, benchmark drivers) stay far below these
# rates; this is a brake, not a budget.
limit_req_zone $binary_remote_addr zone=logos_api:10m rate=30r/s;

server {
    # ...
    location / {
        proxy_pass http://logos-core:443;
        limit_req zone=logos_api burst=60 nodelay;
    }
}
```

Adjust the zone/rate to the deployment's traffic; `limit_req_status 429;`
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

Updating to a new version means re-running the bootstrap script on the node
instead of `docker compose pull`; it is idempotent and preserves `config.yml`,
`.env` and `data/`.

The orchestrator treats them as ordinary vLLM workers — no protocol change was
needed. Sleep/wake is unavailable (it requires CUDA virtual memory), so the
server reclaims memory by stopping and restarting lanes instead.

Full setup, sizing and troubleshooting: `logos/logos-workernode/MACOS.md`.

## Inference gateway replicas

Public `/v1`, `/openai`, and `/jobs` traffic lands on **logos-webservice**.
The service has no fixed `container_name`, so Compose can run more than one
replica; Traefik load-balances them under `logos-webservice-svc`.

The deploy workflows (`logos_deploy-{dev,test,prod}.yml`) scale to this count
automatically on every deploy, defaulting to **2** when `.env` does not set
`LOGOS_WEBSERVICE_REPLICAS` — a single replica means a crash or a routine
deploy is user-visible on the inference gateway. Set the desired count in the
core node's `.env` explicitly if you want something other than 2:

```bash
# in the .env next to docker-compose.yaml
LOGOS_WEBSERVICE_REPLICAS=2

# Pass the same .env into Compose so the scale count is not expanded by the
# host shell (a bare ${LOGOS_WEBSERVICE_REPLICAS:-2} would default to 2 when
# the variable is only set in .env and not exported).
docker compose --env-file .env up -d --scale logos-webservice=2
```

Or, with Compose interpolating from `.env`:

```bash
# docker-compose.yaml (or a compose override) already uses:
#   deploy.replicas / scale via env — prefer an explicit count on --scale,
#   or export before invoking:
set -a && source .env && set +a
docker compose --env-file .env up -d \
  --scale "logos-webservice=${LOGOS_WEBSERVICE_REPLICAS:-2}"
```

On the **dev** compose, drop or retarget the host publish `18082:8081` before
scaling — published host ports cannot be shared across replicas. Liquibase
serialises schema apply via its changelog lock; open SSE streams and the
short-TTL budget cache are the remaining per-instance state (see
`gateway/InferenceGatewayController`).

Optional `.env` knobs:

- `LOGOS_WEBSERVICE_REPLICAS` (default `2`) — webservice replica count for the
  core `docker-compose.yaml`. Cloud RPM is enforced shared across replicas
  (a DB row-lock in `GatewayCloudAccounting`); cloud TPM stays per-replica
  (`GatewayCloudRateLimiter`), so a key's effective TPM ceiling scales with
  the replica count. Set this back to `1` on a deployment where a tight
  per-key TPM limit matters more than gateway failover.
- `LOGOS_GATEWAY_ENABLED` (default `true`) — when `false`, the gateway still
  accepts the public paths but proxies every request to the orchestrator after
  API-key auth.
- `LOGOS_GATEWAY_BUDGET_CACHE_TTL_SECONDS` (default `15`) — approximate budget
  overshoot bound; see `GatewayBudgetService`.
- `LOGOS_GATEWAY_BUDGET_RESERVATION_MICRO_CENTS` (default `1000000`) — finalized
  cost reserved in `log_entry_cost` before each direct-cloud forward so
  concurrent admissions see the spend; reconciled (kept or zeroed) when the
  stream completes.

### Failover verification

Configuring 2 replicas is not the same as proving that killing one is
harmless. Run `scripts/gateway-failover-demo.sh` against a stack already
scaled to 2+ webservice replicas — it fires a steady stream of requests at
`/v1/models`, kills one replica mid-run with `docker kill`, and fails if any
request gets a `000` (connection refused/timeout) or `5xx` response instead of
a normal reply:

On the dev compose, first comment out the fixed `127.0.0.1:18082:8081` host
publish under `logos-webservice: ports:` — a fixed host port cannot be shared
across scaled replicas (see the comment above it):

```bash
docker compose -f docker-compose.dev.yaml up -d --build --scale logos-webservice=2
scripts/gateway-failover-demo.sh http://localhost:18081 30
```

Re-run it against the core `docker-compose.yaml` stack (or a staging
deployment) before relying on 2+ replicas in PROD — the dev compose's rate
gateway and Traefik timeouts are more forgiving than PROD's.

## Environment variables

All runtime configuration lives in the `.env` file next to the compose file.
The [`.env.example` in the repository](https://github.com/ls1intum/edutelligence/blob/main/logos/.env.example)
documents every variable with its default; the ones a fresh deployment must
set:

| Variable | Core node | Worker node |
|---|---|---|
| `LOGOS_DOMAIN` | the core node's fully qualified domain | — |
| `ACME_EMAIL` | the Let's Encrypt contact address | — |
| `LOGOS_INTERNAL_SECRET` | a strong random string — the shared secret between web service and orchestrator | — |
| `KEYCLOAK_ISSUER_URI` | your identity provider's issuer (`https://<idp>/realms/<realm>`) | — |
| `KEYCLOAK_ROLES_LOGOS_ADMIN` / `KEYCLOAK_ROLES_APP_ADMIN` | the OIDC role names that map to the Logos roles (see [roles](developer/architecture#roles)) | — |
| `PROMETHEUS_API_KEY` | optional — gates `/metrics`; unset denies all | — |
| `HF_TOKEN` | optional — HuggingFace token for gated models; also distributed to connected workers | or set per worker |
| `LOGOS_URL` | — | the core node's URL, e.g. `https://logos.example.org` |
| `LOGOS_API_KEY` | — | the worker's shared key from the registration response |

The worker's hardware configuration — models, lane port range, vLLM
overrides — lives in its `config.yml`, never in `.env`. See the
[worker node guide](admin/worker-node.md) and the
[detailed worker setup](https://github.com/ls1intum/edutelligence/blob/main/logos/logos-orchestrator/docs/node-provider-setup.md)
for the registration request and troubleshooting.
