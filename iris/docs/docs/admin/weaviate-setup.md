---
title: Weaviate Setup
---

# Weaviate Setup

Iris uses [Weaviate](https://weaviate.io/) as its vector database to store and retrieve lecture content, transcriptions, and FAQ embeddings for Retrieval-Augmented Generation (RAG).

## Deployment Modes

Iris supports three Weaviate deployment modes. Choose one based on your infrastructure.

:::note
A Pyris-only administrator can complete setup using **Mode 1** or **Mode 2** entirely on their own — no Artemis documentation is required. Mode 3 involves a Weaviate instance provisioned by the Artemis team, but the Iris-side connection is self-contained and documented here.
:::

### Mode 1: Bundled Weaviate (Default)

The default and simplest option. Weaviate runs as a sidecar container in the same Docker Compose stack as Iris. Use this for any new standalone Iris deployment.

**Compose files that include bundled Weaviate:**

| File | Use case |
|------|----------|
| `iris/docker/weaviate.yml` | Base Weaviate service definition |
| `iris/docker/pyris-production.yml` | Production with Nginx — includes `weaviate` |
| `iris/docker/pyris-production-internal.yml` | Production without Nginx — includes `weaviate` |
| `iris/docker/pyris-dev.yml` | Local development — includes `weaviate` |

The `weaviate.yml` base service definition:

```yaml
services:
  weaviate:
    image: cr.weaviate.io/semitechnologies/weaviate:1.37.9
    command:
      - --host
      - 0.0.0.0
      - --port
      - "8001"
      - --scheme
      - http
    volumes:
      - ${WEAVIATE_VOLUME_MOUNT:-./.docker-data/weaviate-data}:/var/lib/weaviate
    restart: on-failure:3
    env_file:
      - ./weaviate/default.env
```

**`application.yml` — bundled Weaviate:**

```yaml
weaviate:
  host: "weaviate"    # Docker service name, not localhost
  port: "8001"
  grpc_port: "50051"
  http_secure: false
  grpc_secure: false
```

:::warning
When running inside Docker Compose, set `weaviate.host` to `"weaviate"` (the Docker service name). The containers communicate over the internal `pyris` bridge network. Use `"localhost"` only for bare-metal local development (without Docker).
:::

Weaviate ports are configurable via environment variables (see [Deployment](./deployment.md) for the full reference):

```bash
export WEAVIATE_PORT=8001        # REST API host port
export WEAVIATE_GRPC_PORT=50051  # gRPC host port
```

### Mode 2: External Weaviate

Use this when Weaviate is managed separately (e.g., a dedicated VM, a managed cloud instance, or a shared server behind a reverse proxy). The compose file `iris/docker/pyris-production-external-weaviate.yml` is identical to the standard production file but intentionally omits the `weaviate` service.

**Starting Iris with external Weaviate:**

```bash
PYRIS_DOCKER_TAG=latest \
PYRIS_APPLICATION_YML_FILE=$(pwd)/application.yml \
PYRIS_LLM_CONFIG_YML_FILE=$(pwd)/llm_config.yml \
NGINX_PROXY_SSL_CERTIFICATE_PATH=/path/to/fullchain.pem \
NGINX_PROXY_SSL_CERTIFICATE_KEY_PATH=/path/to/priv_key.pem \
docker compose -f iris/docker/pyris-production-external-weaviate.yml up -d
```

**`application.yml` — external Weaviate:**

```yaml
weaviate:
  host: "weaviate.internal.example.com"   # Hostname or IP of your Weaviate server
  port: "8080"                            # REST API port on the external server
  grpc_port: "50051"                      # gRPC port on the external server
  http_secure: false                      # Set true if Weaviate is behind HTTPS
  grpc_secure: false                      # Set true if gRPC uses TLS
  # api_key: "your-weaviate-api-key"      # Uncomment if Weaviate requires auth
```

| Field         | Default     | Description                                                              |
| ------------- | ----------- | ------------------------------------------------------------------------ |
| `host`        | `localhost` | Weaviate hostname or IP                                                  |
| `port`        | `8001`      | Weaviate REST API port                                                   |
| `grpc_port`   | `50051`     | Weaviate gRPC port (used for efficient batch operations)                 |
| `http_secure` | `false`     | Set `true` when Weaviate is TLS-terminated (HTTPS)                       |
| `grpc_secure` | `false`     | Set `true` when gRPC uses TLS                                            |
| `api_key`     | _(empty)_   | Optional Weaviate API key (omit for anonymous access on internal networks) |

### Mode 3: Shared with Artemis

Use this when Iris and Artemis both connect to the same Weaviate instance — for example, when Artemis uses Weaviate for global search and you want to avoid running a second Weaviate.

**Iris-side configuration** is identical to Mode 2 (external Weaviate). Configure `application.yml` with the shared Weaviate's connection details:

```yaml
weaviate:
  host: "weaviate.shared.example.com"
  port: "8080"
  grpc_port: "50051"
  http_secure: false
  grpc_secure: false
  # api_key: "your-weaviate-api-key"
```

Iris creates and manages its own collections (`Lectures`, `LectureTranscriptions`, `Faqs`, etc.) independently and will not interfere with Artemis's collections. There is no schema conflict.

**Provisioning the shared Weaviate server** is handled by the Artemis team. Refer to the Artemis admin documentation for server setup:
[https://docs.artemis.cit.tum.de/admin/global-search-weaviate](https://docs.artemis.cit.tum.de/admin/global-search-weaviate)

Once the server is running, complete the Iris-side connection using the `application.yml` block above — no further Artemis documentation is needed.

## Configuration Reference

Full `application.yml` connection block (all fields):

```yaml
weaviate:
  host: "weaviate"       # Use Docker service name in Docker Compose, hostname for external
  port: "8001"           # REST API port
  grpc_port: "50051"     # gRPC port
  http_secure: false     # Set true for HTTPS-terminated external Weaviate
  grpc_secure: false     # Set true for TLS-terminated gRPC
  # api_key: ""          # Optional: Weaviate API key for authenticated instances
```

## Weaviate Environment Variables

Weaviate's behavior is controlled by environment variables in `iris/docker/weaviate/default.env`:

| Variable                                  | Value               | Description                                                |
| ----------------------------------------- | ------------------- | ---------------------------------------------------------- |
| `QUERY_DEFAULTS_LIMIT`                    | `25`                | Default result limit for queries                           |
| `AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED` | `true`              | Allow unauthenticated access (safe on internal networks)   |
| `PERSISTENCE_DATA_PATH`                   | `/var/lib/weaviate` | Data storage path inside the container                     |
| `DEFAULT_VECTORIZER_MODULE`               | `none`              | No built-in vectorizer (Iris handles embedding externally) |
| `ENABLE_MODULES`                          | (empty)             | No additional Weaviate modules enabled                     |
| `CLUSTER_HOSTNAME`                        | `pyris`             | Cluster node name                                          |
| `LIMIT_RESOURCES`                         | `true`              | Enable resource limiting                                   |
| `DISK_USE_WARNING_PERCENTAGE`             | `80`                | Warn when disk usage exceeds 80%                           |
| `vectorCacheMaxObjects`                   | `1000000`           | Maximum objects in the vector cache                        |

## Collections

Iris automatically creates and manages Weaviate collections at startup. You do not need to manually create schemas. The following collections are used:

| Collection              | Purpose                                                                             |
| ----------------------- | ----------------------------------------------------------------------------------- |
| `Lectures`              | Lecture unit page chunks for RAG retrieval                                          |
| `LectureTranscriptions` | Lecture video transcription segments                                                |
| `LectureUnits`          | Lecture unit metadata                                                               |
| `LectureUnitSegments`   | Aggregated lecture segments with cross-references to transcriptions and page chunks |
| `Faqs`                  | Course FAQ entries                                                                  |

If a collection already exists when Iris starts, it is reused. If it does not exist, Iris creates it with the appropriate schema.

:::warning
Deleting Weaviate collections means losing all indexed content. Artemis will need to re-send ingestion requests to rebuild the data. Do not delete collections unless you intend a full re-index.
:::

## Data Persistence

Weaviate stores its data in a Docker volume mounted at `/var/lib/weaviate`. By default, the compose files map this to a local directory:

```
.docker-data/weaviate-data
```

You can override this with the `WEAVIATE_VOLUME_MOUNT` environment variable:

```bash
export WEAVIATE_VOLUME_MOUNT=/data/weaviate
```

:::danger
Losing the Weaviate data volume means losing all indexed lecture content and embeddings. Ensure this volume is backed up in production.
:::

## Backups

### Volume-Level Backups

The simplest backup strategy is to snapshot the Weaviate data volume:

```bash
# Stop Weaviate to ensure data consistency
docker compose -f <compose-file> stop weaviate

# Back up the data directory
tar czf weaviate-backup-$(date +%Y%m%d).tar.gz /path/to/weaviate-data

# Restart Weaviate
docker compose -f <compose-file> start weaviate
```

### Re-Indexing from Artemis

Since all content originates from Artemis, a full re-index is always possible as an alternative to backups. Artemis can re-send lecture content and FAQs to Iris through the ingestion pipeline. This is slower but guarantees data consistency.

## Port Configuration

If you need to change the default ports (e.g., to avoid conflicts):

```bash
export WEAVIATE_PORT=9001        # REST API
export WEAVIATE_GRPC_PORT=50052  # gRPC
```

Remember to update the corresponding values in your `application.yml` (`weaviate.port` and `weaviate.grpc_port`).

## Health Monitoring

Iris's health endpoint at `/api/v1/health/` includes a Weaviate connectivity check. If the Weaviate module reports `DOWN`, common causes include:

- Weaviate container is not running
- Incorrect `host`, `port`, or `grpc_port` in `application.yml`
- Network connectivity issues between the Iris and Weaviate containers

Check Weaviate's own logs for errors:

```bash
docker compose -f <compose-file> logs weaviate
```

For more details, see [Troubleshooting](./troubleshooting.md).

## Related

- **Want Artemis global search on this same Weaviate?** If you are running Mode 3 (shared instance), see the Artemis admin documentation for provisioning and configuring the Artemis side:
  [https://docs.artemis.cit.tum.de/admin/global-search-weaviate](https://docs.artemis.cit.tum.de/admin/global-search-weaviate)
