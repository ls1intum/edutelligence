---
title: Deployment
---

# Deployment

This guide covers deploying Iris using Docker in both development and production environments.

## Prerequisites

- **Docker** and **Docker Compose** installed on the host machine
- Configuration files prepared (see [LLM Configuration](./llm-configuration.md) and [Artemis Integration](./artemis-integration.md))
- Network access to your LLM provider (OpenAI, Azure, or a local Ollama instance)

## Docker Image

Iris publishes container images to the GitHub Container Registry:

```
ghcr.io/ls1intum/edutelligence/iris:latest
```

The image is based on `python:3.12.3-slim` and runs a uvicorn server on port **8000**.

## Docker Compose Files

Iris ships several compose files under `iris/docker/`:

| File                            | Purpose                                                   |
| ------------------------------- | --------------------------------------------------------- |
| `pyris.yml`                     | Base service definition (extended by all others)          |
| `pyris-dev.yml`                 | Development: builds locally, mounts `*.local.yml` configs |
| `pyris-production.yml`          | Production with Nginx (SSL termination)                   |
| `pyris-production-internal.yml` | Production without Nginx (for reverse-proxy setups)       |
| `weaviate.yml`                  | Weaviate vector database service                          |
| `nginx.yml`                     | Nginx reverse proxy with SSL                              |

## Configuration Files

Before starting any deployment, create two YAML configuration files:

1. **`application.yml`** -- application settings (API keys, Weaviate connection, LangFuse)
2. **`llm_config.yml`** -- LLM model definitions

For local development, copy the example files:

```bash
cd iris
cp application.example.yml application.local.yml
cp llm_config.example.yml llm_config.local.yml
```

Edit both files with your actual values. See [LLM Configuration](./llm-configuration.md) for model setup details.

## Development Deployment

Start the development stack (builds the image locally):

```bash
docker compose -f iris/docker/pyris-dev.yml up --build
```

This mounts `application.local.yml` and `llm_config.local.yml` from the `iris/` directory and exposes:

- **Iris API**: `http://localhost:8000`
- **API Docs (Swagger)**: `http://localhost:8000/docs`
- **Weaviate REST**: `http://localhost:8001`
- **Weaviate gRPC**: `localhost:50051`

## Production Deployment

### Getting Started

Before launching any production compose file, clone the repository and create your configuration files:

```bash
git clone https://github.com/ls1intum/edutelligence.git
cd edutelligence
cp iris/application.example.yml iris/application.yml
cp iris/llm_config.example.yml iris/llm_config.yml
```

Edit `application.yml` with your API keys and Weaviate connection details. Edit `llm_config.yml` with your LLM model definitions. See [LLM Configuration](./llm-configuration.md) for model setup details and [Weaviate Setup](./weaviate-setup.md) for database options.

Create a protected `docker.env` file with the variables shared by every production profile. Use absolute host paths:

```dotenv
PYRIS_DOCKER_TAG=latest
PYRIS_APPLICATION_YML_FILE=/opt/edutelligence/iris/application.yml
PYRIS_LLM_CONFIG_YML_FILE=/opt/edutelligence/iris/llm_config.yml
```

```bash
chmod 600 docker.env
```

The commands below load this file with `--env-file docker.env`. Add the profile-specific variables shown for the option you choose.

### Option 1: With Nginx (SSL Termination)

Use this when Iris is directly exposed to the internet.

1. **Prepare SSL certificates** -- place `fullchain.pem` and `priv_key.pem` at known paths on the host.

2. **Add the Nginx variables to `docker.env`**:

```dotenv
NGINX_PROXY_SSL_CERTIFICATE_PATH=/path/to/fullchain.pem
NGINX_PROXY_SSL_CERTIFICATE_KEY_PATH=/path/to/priv_key.pem
```

3. **Start the stack**:

```bash
docker compose --env-file docker.env -f iris/docker/pyris-production.yml up -d
```

Nginx listens on ports **80** and **443** and proxies to the Iris application container.

### Option 2: Without Nginx (Behind Existing Reverse Proxy)

Use this when Iris sits behind an existing reverse proxy (e.g., Traefik, Caddy, or a load balancer).

Add the optional published port to `docker.env` if the default is unsuitable:

```dotenv
PYRIS_PORT=8000
```

```bash
docker compose --env-file docker.env -f iris/docker/pyris-production-internal.yml up -d
```

Iris is exposed directly on `PYRIS_PORT` (default `8000`).

### Option 3: External Weaviate (No Bundled Weaviate)

Use this when you connect to an externally-managed Weaviate instance (e.g., a separate VM or a shared Weaviate that also serves Artemis global search). The compose file is identical to Option 1 but intentionally omits the bundled `weaviate` service.

Configure your `application.yml` with the external Weaviate connection details (host, ports, TLS flags, API key). Add the Nginx certificate paths shown in Option 1 to `docker.env`, then start the stack:

```bash
docker compose --env-file docker.env -f iris/docker/pyris-production-external-weaviate.yml up -d
```

See [Weaviate Setup](./weaviate-setup.md) for all three Weaviate deployment modes.

## Verifying the Deployment

After starting a production profile, store the Iris API token in a protected curl configuration so it is not exposed in shell history or process arguments:

```bash
read -rsp "Iris API token: " PYRIS_API_TOKEN && printf '\n'
install -m 600 /dev/null .curl-pyris.conf
printf 'header = "Authorization: %s"\n' "$PYRIS_API_TOKEN" > .curl-pyris.conf
unset PYRIS_API_TOKEN

# Health check — Nginx profile (HTTPS)
curl --config .curl-pyris.conf https://pyris.your-domain.com/api/v1/health/

# Health check — internal profile (direct port)
curl --config .curl-pyris.conf http://localhost:${PYRIS_PORT:-8000}/api/v1/health/
```

For a bundled Weaviate profile, probe the locally published REST port:

```bash
curl http://localhost:${WEAVIATE_PORT:-8001}/v1/.well-known/ready
```

For an external or shared Weaviate profile, probe the host, REST port, and TLS scheme configured in `application.yml`. If the server requires an API key, put its `Authorization` header in a protected curl config as above and pass that file with `--config`:

```bash
WEAVIATE_SCHEME=https
WEAVIATE_HOST=weaviate.example.com
WEAVIATE_REST_PORT=443
curl "${WEAVIATE_SCHEME}://${WEAVIATE_HOST}:${WEAVIATE_REST_PORT}/v1/.well-known/ready"
```

The applicable endpoints should return HTTP 200. The Iris health response should show `"isHealthy": true` with both `Weaviate Vector Database` and `Pipelines` modules reporting `UP`. Remove `.curl-pyris.conf` when it is no longer needed.

**Managing a running stack:**

```bash
# View logs
docker compose --env-file docker.env -f iris/docker/pyris-production.yml logs -f pyris-app

# Pull new image and restart
PYRIS_DOCKER_TAG=latest docker compose --env-file docker.env -f iris/docker/pyris-production.yml up -d --pull always

# Stop all services
docker compose --env-file docker.env -f iris/docker/pyris-production.yml down
```

## Environment Variables

| Variable                               | Default                   | Description                                                        |
| -------------------------------------- | ------------------------- | ------------------------------------------------------------------ |
| `PYRIS_DOCKER_TAG`                     | `latest`                  | Docker image tag to pull (e.g., `latest`, `pr-123`, a branch name) |
| `PYRIS_APPLICATION_YML_FILE`           | --                        | **Required.** Absolute path to `application.yml` on the host       |
| `PYRIS_LLM_CONFIG_YML_FILE`            | --                        | **Required.** Absolute path to `llm_config.yml` on the host        |
| `PYRIS_PORT`                           | `8000`                    | Host port for Iris (production-internal compose only)              |
| `WEAVIATE_PORT`                        | `8001`                    | Host port for Weaviate REST API (bundled Weaviate only)            |
| `WEAVIATE_GRPC_PORT`                   | `50051`                   | Host port for Weaviate gRPC (bundled Weaviate only)                |
| `NGINX_PROXY_SSL_CERTIFICATE_PATH`     | --                        | **Required (Nginx).** Path to SSL certificate (`fullchain.pem`)    |
| `NGINX_PROXY_SSL_CERTIFICATE_KEY_PATH` | --                        | **Required (Nginx).** Path to SSL private key (`priv_key.pem`)     |
| `APPLICATION_YML_PATH`                 | `/config/application.yml` | Container-internal config path (set automatically by compose)      |
| `LLM_CONFIG_PATH`                      | `/config/llm_config.yml`  | Container-internal config path (set automatically by compose)      |

The following environment variables are used for monitoring (see [Monitoring](./monitoring.md)):

| Variable                   | Default       | Description                       |
| -------------------------- | ------------- | --------------------------------- |
| `SENTRY_ENVIRONMENT`       | `development` | Sentry environment tag            |
| `SENTRY_ENABLE_TRACING`    | `False`       | Enable Sentry performance tracing |
| `SENTRY_SERVER_NAME`       | `localhost`   | Server name reported to Sentry    |
| `SENTRY_RELEASE`           | `None`        | Release tag for Sentry            |
| `SENTRY_ATTACH_STACKTRACE` | `False`       | Attach stack traces to all events |

## Health Endpoint

Iris exposes a health check at:

```
GET /api/v1/health/
```

:::warning
The health endpoint requires authentication. Pass the API token in the `Authorization` header.
:::

The response includes the overall health status and per-module details (Weaviate connectivity, pipeline availability):

```json
{
  "isHealthy": true,
  "modules": {
    "Weaviate Vector Database": { "status": "UP" },
    "Pipelines": { "status": "UP" }
  }
}
```

Use this endpoint for Docker health checks or load balancer probes.

## Resource Considerations

- **Iris application**: Lightweight Python process. 1-2 CPU cores and 2 GB RAM is sufficient for moderate load.
- **Weaviate**: Resource usage depends on the volume of indexed lecture content. Weaviate persists data to a volume mount at `/var/lib/weaviate`. Allocate at least 4 GB RAM for production workloads.
- **Weaviate disk warnings**: Weaviate is configured to warn at 80% disk usage (`DISK_USE_WARNING_PERCENTAGE=80`).

:::tip
Monitor Weaviate's disk usage in production. If the disk fills up, ingestion operations will fail silently.
:::

## Managing Containers

**Stop all services:**

```bash
docker compose -f <compose-file> down
```

**View logs:**

```bash
docker compose -f <compose-file> logs -f pyris-app
```

**Rebuild after code or config changes:**

```bash
docker compose -f <compose-file> up --build
```

## Updating Iris

To update a production deployment:

1. Pull the new image tag:

```bash
export PYRIS_DOCKER_TAG=<new-tag>
```

2. Recreate the containers:

```bash
docker compose -f iris/docker/pyris-production.yml up -d
```

The production compose files use `pull_policy: always`, so Docker will fetch the latest image matching the tag.
