---
title: Self-hosted Installation
---

# Self-hosted installation

This guide deploys the complete Logos stack with Docker Compose. The stack
contains the web UI, API service, orchestrator, PostgreSQL, Keycloak, and
Traefik.

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

Open `http://localhost:4200/` and sign in with one of the seeded development
accounts. These accounts and their roles are defined in
`keycloak/tum-realm.json`; never use them in a production deployment.

## Production deployment

For production, use `docker-compose.yaml` with images built and published by
the Logos build workflow:

```bash
docker compose --env-file .env up -d
```

Set a real `LOGOS_DOMAIN`, `ACME_EMAIL`, `LOGOS_CORS_ALLOWED_ORIGINS`, and
strong values for `LOGOS_INTERNAL_SECRET` and `PROMETHEUS_API_KEY`. Ensure
the host's ports 80, 443, and (if required) 8080 are available. Traefik
obtains a certificate through Let's Encrypt when `ACME_EMAIL` is configured.

After startup, verify the UI at `https://<your-domain>/` and the API
documentation at `https://<your-domain>/docs`.

## Persistent data and upgrades

PostgreSQL, Keycloak, and Traefik data are stored in Docker volumes. Back up
these volumes before upgrades. Pull the desired image tag and recreate the
stack:

```bash
docker compose --env-file .env pull
docker compose --env-file .env up -d
```
