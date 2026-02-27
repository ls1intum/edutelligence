# Iris (Pyris)

Iris is an intelligent virtual AI tutor integrated into [Artemis](https://github.com/ls1intum/Artemis). It provides
one-on-one programming assistance, course content support, and competency generation for students.

Pyris is the backend service that powers Iris. It acts as an intermediary between Artemis and various Large Language
Models (LLMs), exposing a REST API built with FastAPI.

## Features

- **Exercise Support**: Analyzes submitted code, feedback, and build logs to provide detailed insights on programming
  exercises.
- **Course Content Support**: Uses RAG (Retrieval-Augmented Generation) to explain course content based on
  instructor-provided learning materials.
- **Competency Generation**: Automates the creation of course competencies, reducing manual effort.

## Prerequisites

- **Python 3.12**
- **[Poetry](https://python-poetry.org/)** for dependency management
- **Docker and Docker Compose** for running Weaviate (and optionally Pyris itself)

## Local Development Setup

### 1. Clone and Navigate

```bash
git clone https://github.com/ls1intum/edutelligence.git
cd edutelligence/iris
```

### 2. Install Dependencies

```bash
poetry install
```

### 3. Install Pre-Commit Hooks

Run this from the **edutelligence repository root** (not the `iris` directory):

```bash
cd ..
pre-commit install
cd iris
```

### 4. Start Weaviate

Pyris requires a [Weaviate](https://weaviate.io/) vector database for RAG functionality. Start it using the provided
Docker Compose file:

```bash
docker compose -f docker/weaviate.yml up -d
```

Verify it is running:

```bash
curl http://localhost:8001/v1/.well-known/ready
```

This starts Weaviate on port **8001** (REST) and **50051** (gRPC).

### 5. Create Configuration Files

#### Application Configuration

```bash
cp application.example.yml application.local.yml
```

Edit `application.local.yml`. The minimal configuration looks like this:

```yaml
api_keys:
  - token: "secret" # Must match the secret configured in Artemis

weaviate:
  host: "localhost"
  port: "8001"
  grpc_port: "50051"

env_vars:
```

The example file also contains optional sections for **Memiris** (long-term memory) and **Langfuse** (LLM tracing).
Enable them as needed.

#### LLM Configuration

```bash
cp llm_config.example.yml llm_config.local.yml
```

Edit `llm_config.local.yml` and add your API keys. You need to configure **three types of models**:

1. **Chat models** (required) — for all pipeline conversations
2. **Embedding models** (required) — for RAG vector storage and retrieval
3. **Reranker models** (optional) — for improved retrieval quality

**OpenAI chat model example:**

```yaml
- id: "oai-gpt-41-mini"
  name: "GPT 4.1 Mini"
  description: "GPT 4.1 Mini on OpenAI"
  type: "openai_chat"
  model: "gpt-4.1-mini"
  api_key: "<your_openai_api_key>"
  tools: []
  cost_per_million_input_token: 0.4
  cost_per_million_output_token: 1.6
```

**Azure OpenAI chat model example:**

```yaml
- id: "azure-gpt-41-mini"
  name: "GPT 4.1 Mini"
  description: "GPT 4.1 Mini on Azure"
  type: "azure_chat"
  endpoint: "<your_azure_endpoint>"
  api_version: "2024-05-01-preview"
  azure_deployment: "gpt-41-mini"
  model: "gpt-4.1-mini"
  api_key: "<your_azure_api_key>"
  tools: []
  cost_per_million_input_token: 0.4
  cost_per_million_output_token: 1.6
```

**Embedding model example (required for RAG):**

```yaml
- id: "oai-embedding-small"
  name: "Embedding Small"
  description: "Embedding Small 8k"
  type: "openai_embedding"
  model: "text-embedding-3-small"
  api_key: "<your_openai_api_key>"
  cost_per_million_input_token: 0.02
```

See `llm_config.example.yml` for the full list of model configurations including Azure embeddings and Cohere reranker.

**Configuration parameter reference:**

| Parameter                       | Description                                                                                                   |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `id`                            | Unique identifier across all configured models                                                                |
| `model`                         | Official model name as used by the vendor (e.g. `gpt-4.1-mini`)                                               |
| `type`                          | Client selector: `openai_chat`, `azure_chat`, `ollama`, `openai_embedding`, `azure_embedding`, `cohere_azure` |
| `api_key`                       | API key for the model provider                                                                                |
| `endpoint`                      | Provider URL (required for Azure and Cohere)                                                                  |
| `api_version`                   | API version (Azure only)                                                                                      |
| `azure_deployment`              | Deployment name (Azure only)                                                                                  |
| `tools`                         | Tools supported by the model (usually `[]`)                                                                   |
| `cost_per_million_input_token`  | Input token cost, used for model routing decisions                                                            |
| `cost_per_million_output_token` | Output token cost, used for model routing decisions                                                           |

> **Note:** Most pipelines require the GPT-4.1 model family (`gpt-4.1`, `gpt-4.1-mini`, `gpt-4.1-nano`) to be
> configured. Watch the logs for warnings about missing models.

### 6. Run the Server

```bash
APPLICATION_YML_PATH=./application.local.yml \
LLM_CONFIG_PATH=./llm_config.local.yml \
poetry run uvicorn iris.main:app --reload
```

The server starts at [http://localhost:8000](http://localhost:8000).
Interactive API docs are available at [http://localhost:8000/docs](http://localhost:8000/docs).

### 7. Configure Artemis

For Iris to work end-to-end, Artemis must be configured to communicate with Pyris. In your Artemis
`application-artemis.yml` (or `application-local.yml`), add:

```yaml
artemis:
  iris:
    enabled: true
    url: http://localhost:8000
    secret-token: secret # Must match the token in Pyris application.local.yml
```

> For the full Artemis-side setup (including Spring profiles), see the
> [Artemis Extension Services documentation](https://docs.artemis.cit.tum.de/admin/extension-services).

## IDE Setup (PyCharm)

1. Open the `iris` folder as a PyCharm project.
2. Go to **File > Settings > Project: iris > Python Interpreter**.
3. Click the gear icon, select **Add...**, choose **Poetry Environment**, and point to your `poetry` executable.
4. Mark `src` as **Sources Root** (right-click > Mark Directory as > Sources Root).
5. Mark `tests` as **Test Sources Root**.
6. Invalidate caches and restart: **File > Invalidate Caches... > Invalidate and Restart**.

## Testing

```bash
poetry run pytest
```

With coverage:

```bash
poetry run coverage run -m pytest
poetry run coverage html
```

## Linting

Run all pre-commit hooks from the **edutelligence repository root**:

```bash
pre-commit run --all-files
```

## Detect Secrets

Scan all tracked files for accidentally committed secrets:

```bash
git ls-files -z | xargs -0 detect-secrets-hook --baseline .secrets.baseline
```

Update the baseline:

```bash
git ls-files -z | xargs -0 detect-secrets scan --baseline .secrets.baseline
```

## Docker Setup

For containerized deployment, Pyris provides several Docker Compose configurations in the `docker/` directory.

### Prerequisites

- Docker and Docker Compose installed
- Configuration files created (see [Create Configuration Files](#5-create-configuration-files) above)

### Docker Compose Files

| File                                   | Use Case                                                                     |
| -------------------------------------- | ---------------------------------------------------------------------------- |
| `docker/pyris-dev.yml`                 | Local development (builds from source, mounts local config)                  |
| `docker/pyris-production.yml`          | Production with Nginx (SSL termination, reverse proxy)                       |
| `docker/pyris-production-internal.yml` | Production without Nginx (direct access, e.g. behind existing reverse proxy) |

### Development

```bash
docker compose -f docker/pyris-dev.yml up --build
```

This builds Pyris from source, starts it alongside Weaviate, and mounts your `application.local.yml` and
`llm_config.local.yml` from the `iris/` directory.

### Production with Nginx

1. Place your SSL certificate (`fullchain.pem`) and private key (`priv_key.pem`) in the paths specified in the compose
   file, or override them via environment variables.

2. Start the stack:

   ```bash
   PYRIS_DOCKER_TAG=latest \
   PYRIS_APPLICATION_YML_FILE=/path/to/application.yml \
   PYRIS_LLM_CONFIG_YML_FILE=/path/to/llm_config.yml \
   docker compose -f docker/pyris-production.yml up -d
   ```

### Production without Nginx

```bash
PYRIS_DOCKER_TAG=latest \
PYRIS_APPLICATION_YML_FILE=/path/to/application.yml \
PYRIS_LLM_CONFIG_YML_FILE=/path/to/llm_config.yml \
docker compose -f docker/pyris-production-internal.yml up -d
```

### Environment Variables

| Variable                     | Default  | Description                                    |
| ---------------------------- | -------- | ---------------------------------------------- |
| `PYRIS_DOCKER_TAG`           | `latest` | Docker image tag for Pyris                     |
| `PYRIS_APPLICATION_YML_FILE` | —        | Path to your `application.yml`                 |
| `PYRIS_LLM_CONFIG_YML_FILE`  | —        | Path to your `llm_config.yml`                  |
| `PYRIS_PORT`                 | `8000`   | Host port for Pyris (production-internal only) |
| `WEAVIATE_PORT`              | `8001`   | Host port for Weaviate REST API                |
| `WEAVIATE_GRPC_PORT`         | `50051`  | Host port for Weaviate gRPC                    |

### Managing Containers

```bash
# View logs
docker compose -f docker/<compose-file> logs -f pyris-app

# Stop
docker compose -f docker/<compose-file> down

# Rebuild after code changes
docker compose -f docker/<compose-file> up --build
```

## Troubleshooting

- **Port conflicts**: Change host ports via environment variables (e.g. `PYRIS_PORT=8080`).
- **Permission issues**: Ensure correct permissions on SSL certificates and config files.
- **Docker resources**: Ensure Docker has sufficient memory allocated (at least 4 GB recommended).
- **Missing models**: Check Pyris logs for warnings like `No model found for ...` and add the missing model to your
  `llm_config.local.yml`.
