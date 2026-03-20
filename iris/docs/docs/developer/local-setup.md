---
title: Local Setup
---

# Local Setup

This guide walks you through setting up Iris for local development. By the end, you will have the server running on your machine with a Weaviate vector database and at least one LLM configured.

## Prerequisites

| Requirement                 | Version       | Notes                                                              |
| --------------------------- | ------------- | ------------------------------------------------------------------ |
| **Python**                  | 3.12+         | `python --version` to verify                                       |
| **Poetry**                  | 2.x           | [Installation guide](https://python-poetry.org/docs/#installation) |
| **Docker & Docker Compose** | Latest stable | Required for Weaviate                                              |
| **Git**                     | Any recent    | For cloning and pre-commit hooks                                   |

## 1. Clone the Repository

Iris lives inside the [Edutelligence monorepo](https://github.com/ls1intum/edutelligence):

```bash
git clone https://github.com/ls1intum/edutelligence.git
cd edutelligence/iris
```

All subsequent commands assume you are inside the `iris/` directory.

## 2. Install Dependencies

Iris uses [Poetry](https://python-poetry.org/) for dependency management and virtual environments:

```bash
poetry install
```

This creates a virtual environment and installs all production and development dependencies defined in `pyproject.toml`.

## 3. Set Up Pre-commit Hooks

The repository uses [pre-commit](https://pre-commit.com/) for automated code quality checks. Install the hooks from the **monorepo root** (one level above `iris/`):

```bash
cd ..  # back to edutelligence root
pre-commit install
cd iris
```

This ensures linters (`black`, `isort`, `pylint`, etc.) run automatically before each commit.

## 4. IDE Setup (PyCharm)

If you use PyCharm:

1. Open the `iris` folder as a new PyCharm project.
2. Go to **File > Settings > Project > Python Interpreter**.
3. Click the gear icon and select **Add...**.
4. Select **Poetry Environment** and choose the `poetry` executable.
5. Click **OK** and **Apply**.

You should also configure source roots:

1. Right-click the `src` folder > **Mark Directory as > Sources Root**.
2. Right-click the `tests` folder > **Mark Directory as > Test Sources Root**.
3. **File > Invalidate Caches...** and click **Invalidate and Restart**.

:::tip VS Code
If you use VS Code, set `"python.defaultInterpreterPath"` to the Poetry virtual environment path (find it with `poetry env info -p`).
:::

## 5. Create Configuration Files

Iris requires two YAML configuration files:

### Application Configuration

```bash
cp application.example.yml application.local.yml
```

The application config defines API keys, Weaviate connection settings, Memiris configuration, and optional LangFuse tracing:

```yaml title="application.local.yml"
api_keys:
  - token: "your-secret-token"

weaviate:
  host: "localhost"
  port: "8001"
  grpc_port: "50051"

memiris:
  enabled: true
  sleep_enabled: true

langfuse:
  enabled: false

env_vars:
```

### LLM Configuration

```bash
cp llm_config.example.yml llm_config.local.yml
```

This file defines which LLM models are available. Here is a minimal example using OpenAI directly:

```yaml title="llm_config.local.yml"
- id: "oai-gpt-5-mini"
  name: "GPT 5 Mini"
  description: "GPT 5 Mini on OpenAI"
  type: "openai_chat"
  model: "gpt-5-mini"
  api_key: "<your_openai_api_key>"
  tools: []
  cost_per_million_input_token: 0.4
  cost_per_million_output_token: 1.6
```

For Azure OpenAI, the format looks like:

```yaml title="llm_config.local.yml (Azure)"
- id: "azure-gpt-5-mini"
  name: "GPT 5 Mini (Azure)"
  description: "GPT 5 Mini on Azure"
  type: "azure_chat"
  endpoint: "<your-azure-endpoint>"
  api_version: "2025-04-01-preview"
  azure_deployment: "gpt-5-mini"
  model: "gpt-5-mini"
  api_key: "<your_azure_api_key>"
  tools: []
  cost_per_million_input_token: 0.4
  cost_per_million_output_token: 1.6
```

:::warning
Most Iris pipelines require specific model versions (e.g., the full GPT model family plus embeddings and a reranker). Watch the server logs for warnings about missing models.
:::

See [Configuration](./configuration.md) for full details on all configuration parameters.

## 6. Start Weaviate

Iris uses [Weaviate](https://weaviate.io/) as its vector database. Start it with Docker Compose:

```bash
docker compose -f docker/weaviate.yml up -d
```

This starts Weaviate on port `8001` (REST) and `50051` (gRPC) by default.

## 7. Run the Server

Start the Iris server with the local configuration files:

```bash
APPLICATION_YML_PATH=./application.local.yml \
LLM_CONFIG_PATH=./llm_config.local.yml \
uvicorn iris.main:app --reload
```

Or using Poetry directly:

```bash
APPLICATION_YML_PATH=./application.local.yml \
LLM_CONFIG_PATH=./llm_config.local.yml \
poetry run uvicorn iris.main:app --reload
```

The server starts at [http://localhost:8000](http://localhost:8000). The interactive API documentation is available at [http://localhost:8000/docs](http://localhost:8000/docs).

## 8. Docker Development Setup (Alternative)

If you prefer to run everything in Docker:

```bash
docker compose -f docker/pyris-dev.yml up --build
```

This builds the Iris application and starts it alongside Weaviate. Local configuration files are mounted into the container for easy modification.

## Troubleshooting

### Port Conflicts

If Weaviate or the app fails to start due to port conflicts, change the ports:

```bash
export PYRIS_PORT=8080
export WEAVIATE_PORT=8002
export WEAVIATE_GRPC_PORT=50052
```

### Missing Models

If you see warnings like `No ChatModel found with model name gpt-5-mini`, ensure your `llm_config.local.yml` has an entry whose `model` field matches the requested model name.

### Weaviate Connection Errors

Ensure Weaviate is running (`docker ps`) and the host/port in `application.local.yml` match the Docker Compose configuration.

### Import Errors

If imports fail, ensure you have activated the Poetry environment (`poetry shell`) or are running commands through `poetry run`.
