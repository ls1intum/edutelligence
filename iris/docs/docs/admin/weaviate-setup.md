---
title: Weaviate Setup
---

# Weaviate Setup

Iris uses [Weaviate](https://weaviate.io/) as its vector database to store and retrieve lecture content, transcriptions, and FAQ embeddings for Retrieval-Augmented Generation (RAG).

## Deployment

Weaviate is deployed as part of the Iris Docker Compose stack. The base service definition is in `iris/docker/weaviate.yml`:

```yaml
services:
  weaviate:
    image: cr.weaviate.io/semitechnologies/weaviate:1.34.10
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

All Iris compose files (dev, production, production-internal) automatically include this Weaviate service. You do not need to deploy Weaviate separately.

## Configuration in Iris

Iris connects to Weaviate via settings in `application.yml`:

```yaml
weaviate:
  host: "localhost"
  port: "8001"
  grpc_port: "50051"
```

| Field       | Default     | Description                                                                            |
| ----------- | ----------- | -------------------------------------------------------------------------------------- |
| `host`      | `localhost` | Weaviate hostname. Use `weaviate` when running in Docker Compose (Docker network DNS). |
| `port`      | `8001`      | Weaviate REST API port                                                                 |
| `grpc_port` | `50051`     | Weaviate gRPC port (used for efficient batch operations)                               |

:::tip
When running via Docker Compose, the Weaviate service is accessible at hostname `weaviate` on the `pyris` bridge network. Use `host: "weaviate"` in your `application.yml`. Only use `localhost` for local development without Docker.
:::

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
