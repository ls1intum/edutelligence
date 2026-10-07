# Logos deployment

Logos deployments use pull. The project publishes prebuilt images to its Harbor
registry (`${LOGOS_HARBOR_REGISTRY}/logos`). The tag `latest` follows `main`.
A pinned tag selects one specific build. Logos also mirrors builds of `main` to
public GHCR. A self-hosted installation can therefore pull images without
credentials (see the [installation guide](admin/installation.md)). Deployments
use Harbor. A deployment is the compose file plus a `.env` file on each node. To
update, run `docker compose pull` and `docker compose up -d`. CI sends nothing to
a node. A worker node needs no inbound port (see the
[architecture overview](developer/architecture) for the subsystem breakdown).

A deployment consists of:

- One **core node** that runs the core stack: Traefik, the rate-limit gateway,
  the orchestrator, the web service, the UI, and PostgreSQL.
- Zero or more **worker nodes**. A worker node is a GPU machine that runs local
  vLLM models and connects out to the core node (see the
  [worker node guide](admin/worker-node.md)).
- Optionally, the **agent stack** on the core node. It runs coding agents on
  spare serving capacity (see the
  [agent runner reference](https://github.com/ls1intum/edutelligence/blob/main/logos/logos-agent/README.md)).
  It is opt-in. To enable it, set `COMPOSE_PROFILES=agent`.

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
| `logos-workernode-mlx` | the Apple Silicon worker. Logos does not push this image to Harbor, and nobody runs it as a container (see the MLX section below) |

`REGISTRY` (default `ghcr.io/ls1intum/edutelligence`, the public mirror) and
`IMAGE_TAG` (default `latest`) in the `.env` select the source. The deploy
workflows write `${LOGOS_HARBOR_REGISTRY}/logos` and the deployed tag into the
`.env` that they send. Every node therefore pulls from Harbor, and you log in
once (`docker login`). The default is for installations that have no Harbor
account.

Only pushes to `main` write to the mirror. A pull request builds to Harbor only.
There, the cleanup workflow prunes its `pr-<number>` tag. A release also
publishes its version tag to Harbor. Nothing prunes a public package, so PR
builds and release builds do not go to the mirror. When a package appears for the
first time, check that it is public. A private package gives a 403 to a
self-hosted installation. To fix this, use Package settings → Change visibility.

## Updating

The core node updates in place. Change the tag:

```bash
# in the .env next to docker-compose.yaml
IMAGE_TAG=<new tag>   # or keep "latest"
```

```bash
docker compose --env-file .env pull
docker compose --env-file .env up -d
```

The web service applies pending Liquibase migrations at startup, so a version
jump is a normal event. First, back up the persistent volumes (see the
[installation guide](admin/installation.md#persistent-data-and-upgrades)).

Worker nodes update in the same way from their worker directory. Change
`IMAGE_TAG` in the `.env` of the worker. Then run `docker compose pull` and
`docker compose up -d`. The lane configuration and the calibrated model profiles
stay in the `data/` volume of the worker. An update does not reset them.

Each worker image has the commit that it was built from. The Statistics page
shows the commit beside the name of the worker as `version: <commit>`. To see the
full commit and a button to copy it, hover over the info icon next to it, or tap
it on a touch screen. Compare the versions of the workers to find the workers
that did not get an update. A worker that was built outside CI, or that is older
than this function, shows `version: unknown`. To give your own build a commit,
pass `--build-arg GIT_SHA=$(git rev-parse HEAD)`. For a pull-request build, the
version is the commit of the pull request. The image is that pull request merged
into `main` as of the build.

## Security & rate limiting

The API surface of the orchestrator has tiers:

- **User-facing** (`/v1`, `/openai`, `/jobs`) — any valid Logos API key.
  Traefik sends these requests to **logos-webservice** (inference gateway). The
  gateway answers pure-cloud named-model requests. It reverse-proxies local/logosnode
  traffic and mixed traffic to the orchestrator on the compose network.
- **Cluster-internal** (`/logosdb/scheduler_state`, `/internal/*`) — the shared
  `LOGOS_INTERNAL_SECRET`, never a user key. In the past, `/logosdb/scheduler_state`
  accepted any Logos API key and had a public route. Now the secret protects it,
  and only a client inside the stack can reach it (the agent runner polls it).
- **Operator** (`/logosdb/providers/logosnode/*`) — the root key, TLS only.
- **Monitoring** (`/metrics`) — `PROMETHEUS_API_KEY`. If it is not set, all
  requests are denied.

The API docs (`/docs`, `/redoc`, `/openapi.json`) publish the full endpoint map.
They are **off by default**. Set `LOGOS_DOCS_ENABLED=1` in `.env` only where
necessary (the dev compose enables it).

### Layer 1: per-IP limits (nginx rate gateway, in-stack)

The `logos-rate-gateway` container is an nginx. Every public request (443 and
8080) passes it first. It enforces a request budget **for each client IP**.
Traefik cannot do this natively, because its `rateLimit` middleware counts for
each service and not for each client. Then the gateway forwards the request to
the *internal* entrypoint of Traefik (`:8090`, no published host port). The
normal routers apply there. The public entrypoint terminates TLS and signals it
again with `X-Forwarded-Proto`, so services continue to see `https`.

There are two budget classes. When a client exceeds a budget, the answer is 429:

| Class | Paths | Default (avg rps / burst) |
|---|---|---|
| model | `/v1`, `/openai`, `/logosdb/...`, the UI, everything else | 30 / 60 |
| control | `/jobs`, `/api`, `/docs`, `/metrics`, `/health`, `/ws` | 5 / 20 |

Tune the limits for each deployment in the `.env` of the node (all optional):

- `LOGOS_IP_RATE_LIMIT_AVG` / `LOGOS_IP_RATE_LIMIT_BURST` — the model budget.
- `LOGOS_IP_CONTROL_RATE_LIMIT_AVG` / `LOGOS_IP_CONTROL_RATE_LIMIT_BURST` —
  the control-plane budget.
- `LOGOS_RATE_LIMIT_WHITELISTED_IPS` — frees specific IPs from **all**
  limits, for example the benchmark rig of the chair or an office egress IP.
  Use IPv4 addresses and CIDRs that a space separates:

  ```env
  # .env on the core node
  LOGOS_RATE_LIMIT_WHITELISTED_IPS="129.79.32.0/20 1.2.3.4"
  ```

  The gateway skips malformed entries and writes a line to `docker logs
  logos-rate-gateway`. A typo in the `.env` gives "no whitelist". It cannot
  crash-loop the gateway (and with it the whole stack).
- `LOGOS_GATEWAY_TRUSTED_PROXY_CIDRS` — the source ranges that can carry
  `X-Forwarded-For`. The default is `172.16.0.0/12` (the Docker bridge ranges).
  This range matches no public client. A header that someone forges from the
  internet is therefore removed before it reaches the gateway. **If the node is
  behind the nginx of the chair (or any other reverse proxy), then add the CIDR
  of that proxy here too.** If you do not, every client counts as that one proxy
  IP, and the isolation for each IP is lost. **Use a comma to separate the
  values.** Logos passes the value directly to `--forwardedHeaders.trustedIPs` of
  Traefik. The CLI of Traefik expects a comma list. A value that a space separates
  leaves the outer proxy untrusted, or makes the static config of Traefik
  invalid. The nginx gateway in the stack changes commas to spaces itself, so the
  same value works for both:

  ```env
  LOGOS_GATEWAY_TRUSTED_PROXY_CIDRS="172.16.0.0/12,129.79.32.0/20"
  ```

  This value covers the **public** entrypoints only. The hop from the gateway to
  Traefik has its own list (below). A new value here can therefore not cut the
  chain in the stack.
- `LOGOS_INTERNAL_HOP_TRUSTED_CIDRS` — the sources that the internal entrypoint
  (`:8090`) trusts, that is, the rate gateway. The default is the private
  address space (`10.0.0.0/8,172.16.0.0/12,192.168.0.0/16`). The address of the
  gateway comes from the network pool of Docker, and it is not necessarily in
  `172.16.0.0/12`. Do not change it, unless the networks of the stack use known
  subnets. The entrypoint has no published host port, so only containers of this
  stack can reach it.
- `LOGOS_GATEWAY_UPSTREAM` — the address where the gateway forwards (default
  `traefik:8090`). Change it only if the internal entrypoint moves.

**Symptom to watch for:** If Traefik does not trust the internal hop, then Traefik
changes the `X-Forwarded-Proto` of the gateway to `http`. Every service then
loses the TLS signal. The most visible result is that worker nodes fail to
attach in a loop:

```text
BRIDGE ERROR ══ /auth rejected with HTTP 400:
{"error":{"message":"TLS is required for logosnode auth/session endpoints ...
```

The 400 body names the scheme and the `X-Forwarded-Proto` that the orchestrator
saw. To verify the chain, check the address of the gateway and the trusted list:

```bash
docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' logos-rate-gateway
docker inspect traefik | grep -- '--entrypoints.internal8090.forwardedHeaders'
```

The dev compose runs the same gateway with higher defaults (300/600 and 50/100).
This prevents throttling during local benchmarks. The direct ports 18080 and
18082 bypass the gateway completely (for debugging).

### Layer 2: per-service limits (Traefik)

Both compose files attach generous Traefik `rateLimit` middleware to the API
routers (429 when exceeded). These limits count for each service and not for
each client. They limit one service when many IPs share the same key. The
per-IP layer above cannot see this case. The higher-priority routers that serve
`/api/*` (webservice, agent, the logosnode operator paths) carry the limiter
together with their strip-prefix middleware. No request therefore reaches a
service without a limit:

| Middleware | Routers | Default (avg rps / burst) |
|---|---|---|
| `rl-model` | `/v1`, `/openai` | 100 / 200 |
| `rl-jobs` | `/jobs` | 50 / 100 |
| `rl-admin` | `/health`, `/docs`, `/metrics`, `/logosdb/providers/logosnode`, the orchestrator's `/api` fallback, and the higher-priority `/api/*` routers (webservice identity/config/admin/WebSocket, logosnode operator actions, agent) | 20 / 40 |

The limiters are defined on the Traefik container itself and not on one of the
services. Every app container references at least one of them. They must
therefore stay when a single service restarts (`strip-api` is there for the same
reason).

Tune the limits for each deployment in `.env`: `LOGOS_RATE_LIMIT_MODEL_AVG`,
`LOGOS_RATE_LIMIT_MODEL_BURST`, `LOGOS_RATE_LIMIT_JOBS_AVG`,
`LOGOS_RATE_LIMIT_JOBS_BURST`, `LOGOS_RATE_LIMIT_ADMIN_AVG`,
`LOGOS_RATE_LIMIT_ADMIN_BURST`. The dev compose uses higher defaults
(500/1000, 250/500, 100/200). This prevents throttling during local benchmarks.

The orchestrator enforces the request budgets for each API key on the model
paths (from the `cloud_rl`/`local_rl` of the key). The limits in the stack are
the backstop against abuse with unauthenticated requests or leaked keys.

### Optional: an additional per-client brake in the nginx in front

The stack does not *need* limits for each client in the nginx ingress of the
chair. The limits are now in the stack and move with the deployment. You can
still add a second brake there. Use it to protect other vhosts on the same
machine, or to stop a flood before it reaches the IP of the node. The same nginx
pattern applies:

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

Adjust the zone and the rate to the traffic of the deployment. Use
`limit_req_status 429;` to keep the status code the same as the limits in the
stack.

## Apple Silicon (MLX) worker nodes

MLX nodes do not use the compose-based deploy path above. Metal cannot pass into
a container. Docker on macOS runs a Linux VM with no GPU passthrough, so a
containerized lane would use the CPU without a warning.

Here, the image is a distribution artifact. On the Mac, `scripts/bootstrap-macos.sh`
pulls the image and extracts the payload with `docker cp` to
`~/logos-workernode-mlx`. Then it runs the worker natively under a launchd
agent. A native run also keeps the orchestrator in control, because a native
process can fork `vllm serve` on command. A container cannot do this.

To update to a new version, run the bootstrap script on the node again. Do not
use `docker compose pull`. The script is idempotent and keeps `config.yml`,
`.env` and `data/`.

The orchestrator treats these nodes as ordinary vLLM workers. The protocol did
not change. Sleep/wake is not available, because it needs CUDA virtual memory.
The server therefore frees memory when it stops and restarts lanes.

Full setup, sizing and troubleshooting: `logos/logos-workernode/MACOS.md`.

## Inference gateway replicas

Public `/v1`, `/openai`, and `/jobs` traffic goes to **logos-webservice**. The
service has no fixed `container_name`, so Compose can run more than one
replica. Traefik load-balances the replicas under `logos-webservice-svc`.

On every deploy, the deploy workflows (`logos_deploy-{dev,test,prod}.yml`) scale
to this count automatically. The default is **1** when `.env` does not set
`LOGOS_WEBSERVICE_REPLICAS`. More replicas hide crashes and routine deploys from
the inference gateway. Cloud RPM and TPM stay shared across replicas through
Redis (see the options below). Set the count in the `.env` of the core node:

```bash
# in the .env next to docker-compose.yaml
LOGOS_WEBSERVICE_REPLICAS=2

# Pass the same .env into Compose so the scale count is not expanded by the
# host shell (a bare ${LOGOS_WEBSERVICE_REPLICAS:-1} would default to 1 when
# the variable is only set in .env and not exported).
docker compose --env-file .env up -d --scale logos-webservice=2
```

Alternatively, let Compose use the values from `.env`:

```bash
# docker-compose.yaml (or a compose override) already uses:
#   deploy.replicas / scale via env — prefer an explicit count on --scale,
#   or export before invoking:
set -a && source .env && set +a
docker compose --env-file .env up -d \
  --scale "logos-webservice=${LOGOS_WEBSERVICE_REPLICAS:-1}"
```

On the **dev** compose, remove or change the host publish `18082:8081` before
you scale. Replicas cannot share published host ports. Liquibase serializes the
schema apply with its changelog lock. Open SSE streams and the short-TTL budget
cache stay per-instance state (see `gateway/InferenceGatewayController`).

Optional `.env` options:

- `LOGOS_WEBSERVICE_REPLICAS` (default `1`) — the number of webservice replicas
  for the core `docker-compose.yaml`. Redis (`logos-redis`, sliding 60 s window)
  enforces cloud RPM and TPM, and all replicas share the limits.
- `REDIS_HOST` / `REDIS_PORT` (default `logos-redis` / `6379` in compose) —
  the shared rate-limit store for the inference gateway. It is ephemeral. A
  Redis restart clears the window (the limits reset for up to 60 s). If a per-key
  limit is set and Redis is not reachable, then cloud admission fails closed
  (503).
- `LOGOS_GATEWAY_ENABLED` (default `true`) — if the value is `false`, the gateway
  still accepts the public paths. It proxies every request to the orchestrator
  after the API-key authentication.
- `LOGOS_GATEWAY_BUDGET_CACHE_TTL_SECONDS` (default `15`) — the approximate
  limit of the budget overshoot (see `GatewayBudgetService`).
- `LOGOS_GATEWAY_BUDGET_RESERVATION_MICRO_CENTS` (default `1000000`) — the flat
  cost that the gateway reserves in `log_entry` before each direct-cloud
  forward. Concurrent admissions then see the spend. When the stream completes,
  the priced token usage replaces the reserve (or the reserve becomes zero after a
  failure). Admission takes no lock. It does no work that grows with the size of
  the log. Requests on one key run in parallel on every replica. The budget is
  approximate within the cache TTL.
- `LOGOS_GATEWAY_BUDGET_RESERVATION_STALE_MINUTES` (default `30`) — if a
  reservation is still in progress after this time, it belongs to a process that
  is gone. The gateway sets it to zero.
- `LOGOS_GATEWAY_BUDGET_RESERVATION_RECONCILE_SECONDS` (default `60`) — the
  interval at which each replica looks for such stale reservations.

### Failover verification

A configuration with 2 replicas does not prove that a kill of one replica is
harmless for every request. Run `scripts/gateway-failover-demo.sh` against a
stack that has 2 or more webservice replicas. The script sends a steady stream
of short unauthenticated requests to `/v1/models`. During the run, it kills one
replica with `docker kill`. The script fails unless every probe returns the
expected `401` (no API key) of the webservice. These results count as failures:
connection errors (`000`), `5xx`, and other statuses (including rate-gateway
`429`). This check covers new requests only. A killed replica can lose an
inference stream that it holds. The check does not test client recovery. The
script restarts the killed container on exit.

On the dev compose, first comment out the fixed `127.0.0.1:18082:8081` host
publish under `logos-webservice: ports:`. Scaled replicas cannot share a fixed
host port (see the comment above it):

```bash
docker compose -f docker-compose.dev.yaml up -d --build --scale logos-webservice=2
scripts/gateway-failover-demo.sh http://localhost:18081 30
```

Run the script again against the core `docker-compose.yaml` stack (or a staging
deployment) before you use 2 or more replicas in PROD. Set `COMPOSE_FILE`
explicitly. The script then does not kill a replica from the default dev
compose while it probes a different URL:

```bash
COMPOSE_FILE=docker-compose.yaml \
  scripts/gateway-failover-demo.sh https://logos.example.org 30
```

## Environment variables

All runtime configuration is in the `.env` file next to the compose file. The
[`.env.example` in the repository](https://github.com/ls1intum/edutelligence/blob/main/logos/.env.example)
documents every variable with its default. A new deployment must set these
variables:

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

The hardware configuration of the worker is in its `config.yml`, never in `.env`.
It includes the models, the lane port range and the vLLM overrides. See the
[worker node guide](admin/worker-node.md) and the
[detailed worker setup](https://github.com/ls1intum/edutelligence/blob/main/logos/logos-orchestrator/docs/node-provider-setup.md)
for the registration request and troubleshooting.
