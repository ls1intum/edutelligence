---
title: Self-hosted Installation
---

# Self-hosted installation

This guide deploys the complete Logos stack with Docker Compose. The stack
contains the web UI, API service, orchestrator, PostgreSQL, and Traefik.
The development stack additionally runs a local Keycloak; production expects
an external identity provider configured via the `KEYCLOAK_*` variables in
`.env`.

## Prerequisites

- Docker Engine with the Compose plugin
- A domain name and an SMTP/identity-provider setup for production
- Python 3.13 and `uv` only when developing Logos outside containers
- A GPU worker node when serving local models

Clone the repository and enter the service directory:

```bash
git clone https://github.com/ls1intum/edutelligence.git
cd edutelligence/logos
cp .env.example .env
```

## Development deployment

The development compose file builds all services locally and includes a
development Keycloak realm:

```bash
docker compose -f docker-compose.dev.yaml up --build
```

The compose stack serves the API (Traefik at `http://localhost:18081`) but
not the web UI. Start the Angular dev server on the host as well:

```bash
cd logos-ui
npm ci
npm start
```

Then open `http://localhost:4200/` and sign in with one of the seeded
development accounts. These accounts and their roles are defined in
`keycloak/tum-realm.json`; never use them in a production deployment.

## Production deployment

For production, use `docker-compose.yaml` with images built and published by
the Logos build workflow. The workflow publishes the core images to the
project's Harbor registry (team-internal), not to the GHCR default the
compose file falls back to, so set both in `.env` and log in to the registry
before pulling:

```bash
REGISTRY=<your-harbor>/logos
IMAGE_TAG=<published tag>
docker login <your-harbor>
```

If you do not have access to that registry, build the same images locally
from the Dockerfiles the workflow uses and tag them for a registry the host
can pull from (e.g. a local registry):

```bash
# The build contexts below are repository-root relative — return there
# first (the guide's working directory is edutelligence/logos):
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
```

(All seven images are required to run the full stack: the agent runner
refuses to start a session when the `logos-agent-workspace` image is absent.)

Set the same `REGISTRY` and `IMAGE_TAG` in `.env`, then start the stack
(the worker node image is built on the GPU host instead — see the worker
node guide):

```bash
cd logos
docker compose --env-file .env up -d
```

Set a real `LOGOS_DOMAIN`, `ACME_EMAIL`, `LOGOS_CORS_ALLOWED_ORIGINS`, and
strong values for `LOGOS_INTERNAL_SECRET` and `PROMETHEUS_API_KEY`. Ensure
the host's ports 80, 443, and (if required) 8080 are available. Traefik
obtains a certificate through Let's Encrypt when `ACME_EMAIL` is configured.

After startup, verify the UI at `https://<your-domain>/` and the API
documentation at `https://<your-domain>/docs`.

## Persistent data and upgrades

The production stack persists the following:

| Storage | Type | Contents |
| --- | --- | --- |
| `postgres_data` | named volume | PostgreSQL data |
| `data_volume` | named volume | orchestrator working data (`/src/logos`) |
| `agent_artifacts` | named volume | agent session artifacts |
| `agent_state` (literal name `logos_agent_state`) | named volume | agent session state |
| `./letsencrypt` | bind mount | Traefik Let's Encrypt certificate state |

Back up these volumes and the `./letsencrypt` directory before upgrades.
Keycloak is external to the stack, so back up its realm export (see
`keycloak/tum-realm.json` in this repository for the realm format) together
with your identity provider; in the development stack Keycloak state is
ephemeral. Pull the desired image tag and recreate the stack:

```bash
docker compose --env-file .env pull
docker compose --env-file .env up -d
```
