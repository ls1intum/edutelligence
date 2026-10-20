---
title: Self-hosted Installation
---

# Self-hosted installation

This guide shows how to deploy the complete Logos stack with Docker Compose.
The stack contains the web UI, the API service, the orchestrator, PostgreSQL
and Traefik. The development stack also runs a local Keycloak. Production
needs an external identity provider. Configure it with the `KEYCLOAK_*`
variables in `.env`.

## Prerequisites

- Docker Engine with the Compose plugin
- A domain name and an SMTP/identity-provider configuration for production
- Python 3.13 and `uv`, only if you develop Logos outside containers
- A GPU worker node, if you serve local models

Clone the repository and go to the service directory:

```bash
git clone https://github.com/ls1intum/edutelligence.git
cd edutelligence/logos
cp .env.example .env
```

## Development deployment

The development compose file builds all services locally. It includes a
development Keycloak realm:

```bash
docker compose -f docker-compose.dev.yaml up --build
```

The compose stack serves the API (Traefik at `http://localhost:18081`). It
does not serve the web UI. Also start the Angular dev server on the host:

```bash
cd logos-ui
npm ci
npm start
```

Then open `http://localhost:4200/` and sign in with one of the seeded
development accounts. `keycloak/tum-realm.json` defines these accounts and
their roles. Do not use them in a production deployment.

## Production deployment

For production, use `docker-compose.yaml`. Every image is on the public mirror
at `ghcr.io/ls1intum/edutelligence`. The compose file pulls from this mirror
by default. You do not need registry configuration or a login:

```bash
docker compose --env-file .env up -d
```

The mirror receives images from `main`, so it has one tag: `latest`. Version
tags go to the deployment registry of the project, which is team-internal. To
pull from that registry, or from your own mirror, set both variables in
`.env` and log in one time:

```bash
REGISTRY=<registry-host>/<namespace>
IMAGE_TAG=<published tag>
docker login <registry-host>         # host only, no path
```

To run images that you built yourself, build them from the Dockerfiles that
the build workflow uses. Tag them for a registry from which the host can pull,
for example a local registry:

```bash
# The build contexts below are relative to the repository root. Go there
# first (the working directory of this guide is edutelligence/logos):
cd ..
REGISTRY=localhost:5000
IMAGE_TAG=latest
docker build -t "$REGISTRY/logos:$IMAGE_TAG" -f logos/logos-orchestrator/Dockerfile .
docker build -t "$REGISTRY/logos-webservice:$IMAGE_TAG" logos/logos-webservice
docker build -t "$REGISTRY/logos-ui:$IMAGE_TAG" logos/logos-ui
docker build -t "$REGISTRY/logos-db:$IMAGE_TAG" logos/db
docker build -t "$REGISTRY/logos-agent:$IMAGE_TAG" -f logos/logos-agent/Dockerfile .
docker build -t "$REGISTRY/logos-agent-gateway:$IMAGE_TAG" -f logos/agent-gateway/Dockerfile .
docker build -t "$REGISTRY/logos-agent-workspace:$IMAGE_TAG" -f logos/logos-agent/workspace/Dockerfile .
docker build -t "$REGISTRY/logos-rate-gateway:$IMAGE_TAG" -f logos/rate-limit-gateway/Dockerfile .
```

The full stack needs all eight images. `logos-rate-gateway` is the only router
on the public entrypoints. Without it, the stack serves no public traffic. If
the `logos-agent-workspace` image is absent, the agent runner refuses to start
a session.

Set the same `REGISTRY` and `IMAGE_TAG` in `.env`, then start the stack. Build
the worker node image on the GPU host instead (see the worker node guide):

```bash
cd logos
docker compose --env-file .env up -d
```

Set real values for `LOGOS_DOMAIN`, `ACME_EMAIL` and
`LOGOS_CORS_ALLOWED_ORIGINS`. Set strong values for `LOGOS_INTERNAL_SECRET`
and `PROMETHEUS_API_KEY`. Make sure that ports 80, 443 and (if necessary) 8080
of the host are available. If you configure `ACME_EMAIL`, Traefik gets a
certificate through Let's Encrypt.

After startup, verify the UI at `https://<your-domain>/`. Verify the API
documentation at `https://<your-domain>/docs`.

## Persistent data and upgrades

The production stack keeps the following data:

| Storage | Type | Contents |
| --- | --- | --- |
| `postgres_data` | named volume | PostgreSQL data |
| `data_volume` | named volume | orchestrator working data (`/src/logos`) |
| `agent_artifacts` | named volume | agent session artifacts |
| `agent_state` (literal name `logos_agent_state`) | named volume | agent session state |
| `./letsencrypt` | bind mount | Traefik Let's Encrypt certificate state |

Before an upgrade, back up these volumes and the `./letsencrypt` directory.
Keycloak is external to the stack. Back up its realm export together with your
identity provider (for the realm format, see `keycloak/tum-realm.json` in this
repository). In the development stack, the Keycloak state is temporary. Pull
the necessary image tag and recreate the stack:

```bash
docker compose --env-file .env pull
docker compose --env-file .env up -d
```
