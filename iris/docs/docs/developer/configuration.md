---
title: Configuration
---

# Configuration

Iris is configured through two YAML files and environment variables. This page documents all configuration options and how they are loaded.

## Configuration Files

| File                                        | Purpose                                             | Env Variable           |
| ------------------------------------------- | --------------------------------------------------- | ---------------------- |
| `application.yml` / `application.local.yml` | App settings: API keys, Weaviate, Memiris, LangFuse | `APPLICATION_YML_PATH` |
| `llm_config.yml` / `llm_config.local.yml`   | LLM model definitions                               | `LLM_CONFIG_PATH`      |

Both paths are specified via environment variables. The `.local.yml` variants are for development and are gitignored.

## Application Configuration

**Loaded by:** `src/iris/config.py`

The `Settings` class is a Pydantic model that validates the YAML file at startup:

```python
class Settings(BaseModel):
    api_keys: list[APIKeyConfig]
    env_vars: dict[str, str]
    weaviate: WeaviateSettings
    memiris: MemirisSettings
    langfuse: LangfuseSettings = Field(default_factory=LangfuseSettings)

    @classmethod
    def get_settings(cls):
        file_path_env = os.environ.get("APPLICATION_YML_PATH")
        if not file_path_env:
            raise EnvironmentError("APPLICATION_YML_PATH environment variable is not set.")
        file_path = Path(file_path_env)
        with open(file_path, "r", encoding="utf-8") as file:
            settings_file = yaml.safe_load(file)
        return cls.model_validate(settings_file)
```

The settings singleton is created at module load time:

```python
settings = Settings.get_settings()
```

### Full Example

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
  public_key: "pk-lf-..."
  secret_key: "sk-lf-..." # pragma: allowlist secret
  host: "https://cloud.langfuse.com"

env_vars:
  SENTRY_ENVIRONMENT: "development"
```

### Section Reference

#### `api_keys`

List of API tokens that Artemis uses to authenticate with Iris:

```yaml
api_keys:
  - token: "your-secret-token"
```

The token is validated by the `TokenValidator` FastAPI dependency on every pipeline request.

#### `weaviate`

Connection settings for the Weaviate vector database:

| Field       | Type   | Description                           |
| ----------- | ------ | ------------------------------------- |
| `host`      | string | Weaviate hostname (e.g., `localhost`) |
| `port`      | int    | REST API port (default: `8001`)       |
| `grpc_port` | int    | gRPC port (default: `50051`)          |

#### `memiris`

Settings for the Memiris memory system:

| Field           | Type | Default | Description                                       |
| --------------- | ---- | ------- | ------------------------------------------------- |
| `enabled`       | bool | `true`  | Whether Memiris memory creation is active         |
| `sleep_enabled` | bool | `true`  | Whether the nightly memory consolidation job runs |

#### `langfuse`

Optional [LangFuse](https://langfuse.com/) observability integration:

| Field        | Type   | Default                      | Description                                 |
| ------------ | ------ | ---------------------------- | ------------------------------------------- |
| `enabled`    | bool   | `false`                      | Enable/disable LangFuse tracing             |
| `public_key` | string | `null`                       | LangFuse public key (required when enabled) |
| `secret_key` | string | `null`                       | LangFuse secret key (required when enabled) |
| `host`       | string | `https://cloud.langfuse.com` | LangFuse server URL                         |

:::warning
When `enabled: true`, both `public_key` and `secret_key` must be provided. The Pydantic validator will reject the configuration otherwise.
:::

#### `env_vars`

Arbitrary environment variables set at startup. Useful for Sentry configuration and other runtime settings:

```yaml
env_vars:
  SENTRY_ENVIRONMENT: "staging"
  SENTRY_SERVER_NAME: "iris-staging-01"
```

## LLM Configuration

**Loaded by:** `src/iris/llm/llm_manager.py`

The `LlmManager` singleton reads the YAML file and creates typed model objects. The file is a YAML list where each entry defines one LLM:

### Full Example

```yaml title="llm_config.local.yml"
# Chat models
- id: oai-gpt-5-mini
  name: GPT 5 Mini
  description: GPT 5 Mini on OpenAI
  type: openai_chat
  model: gpt-5-mini
  api_key: "<your-key>"
  tools: []
  cost_per_million_input_token: 0.4
  cost_per_million_output_token: 1.6

# Azure chat model
- id: azure-gpt-5-mini
  name: GPT 5 Mini (Azure)
  description: GPT 5 Mini on Azure
  type: azure_chat
  endpoint: "<your-endpoint>"
  api_version: "2025-04-01-preview"
  azure_deployment: gpt-5-mini
  model: gpt-5-mini
  api_key: "<your-key>"
  cost_per_million_input_token: 0.4
  cost_per_million_output_token: 1.6

# Embedding model
- id: oai-embedding-small
  name: Embedding Small
  description: Embedding Small 8k
  type: openai_embedding
  model: text-embedding-3-small
  api_key: "<your-key>"
  cost_per_million_input_token: 0.02

# Reranker
- id: cohere
  name: Cohere Client V2
  description: Cohere V2 client
  type: cohere_azure
  model: rerank-multilingual-v3.5
  endpoint: "<your-endpoint>"
  api_key: "<your-key>"
  cost_per_1k_requests: 2
```

### Parameter Reference

| Parameter                       | Required     | Description                                                        |
| ------------------------------- | ------------ | ------------------------------------------------------------------ |
| `id`                            | Yes          | Unique identifier across all models                                |
| `name`                          | Yes          | Human-readable display name                                        |
| `description`                   | Yes          | Additional description                                             |
| `type`                          | Yes          | Model type (see below)                                             |
| `model`                         | Yes          | Vendor model name — used for version matching (e.g., `gpt-5-mini`) |
| `api_key`                       | Yes          | API key for the provider                                           |
| `endpoint`                      | Azure/Ollama | Provider endpoint URL                                              |
| `api_version`                   | Azure        | Azure API version                                                  |
| `azure_deployment`              | Azure        | Azure deployment name                                              |
| `tools`                         | No           | Supported tool types (default: `[]`)                               |
| `cost_per_million_input_token`  | No           | Cost tracking: input token price                                   |
| `cost_per_million_output_token` | No           | Cost tracking: output token price                                  |
| `cost_per_1k_requests`          | No           | Cost tracking: per-request price (rerankers)                       |

### Model Types

| Type                | Provider       | Class                                                     |
| ------------------- | -------------- | --------------------------------------------------------- |
| `openai_chat`       | OpenAI         | `DirectOpenAIChatModel` — Chat completions                |
| `azure_chat`        | Azure OpenAI   | `AzureOpenAIChatModel` — Chat completions via Azure       |
| `openai_embedding`  | OpenAI         | `DirectOpenAIEmbeddingModel` — Text embeddings            |
| `azure_embedding`   | Azure OpenAI   | `AzureOpenAIEmbeddingModel` — Text embeddings via Azure   |
| `openai_completion` | OpenAI         | `DirectOpenAICompletionModel` — Text completions          |
| `azure_completion`  | Azure OpenAI   | `AzureOpenAICompletionModel` — Text completions via Azure |
| `ollama`            | Ollama         | `OllamaModel` — Local model inference                     |
| `cohere_azure`      | Cohere (Azure) | `CohereAzureClient` — Reranking                           |

### How Models Are Selected

The `ModelVersionRequestHandler` selects models by matching the `model` field:

```python
class ModelVersionRequestHandler(RequestHandler):
    def _select_model(self, type_filter: type) -> LanguageModel:
        matching_llms = [
            llm for llm in self.llm_manager.entries
            if isinstance(llm, type_filter) and llm.model == self.version
        ]
        if not matching_llms:
            raise ValueError(f"No {type_filter.__name__} found with model name {self.version}")
        return matching_llms[0]
```

When a variant specifies `cloud_agent_model: "gpt-5-mini"`, the handler searches for the first entry in `llm_config.yml` where `model == "gpt-5-mini"` and the type is a `ChatModel`.

## Environment Variables

Beyond the two config file paths, Iris uses these environment variables:

| Variable                   | Purpose                           | Default       |
| -------------------------- | --------------------------------- | ------------- |
| `APPLICATION_YML_PATH`     | Path to application config        | _Required_    |
| `LLM_CONFIG_PATH`          | Path to LLM config                | _Required_    |
| `SENTRY_ENVIRONMENT`       | Sentry environment name           | `development` |
| `SENTRY_SERVER_NAME`       | Sentry server identifier          | `localhost`   |
| `SENTRY_RELEASE`           | Sentry release version            | `None`        |
| `SENTRY_ENABLE_TRACING`    | Enable Sentry performance tracing | `False`       |
| `SENTRY_ATTACH_STACKTRACE` | Attach stack traces to events     | `False`       |

Additional environment variables can be injected via the `env_vars` section of `application.yml`.

## Docker Configuration

When running with Docker, configuration files are mounted into the container. The Docker Compose environment variables control paths and ports:

| Variable                     | Default  | Purpose                            |
| ---------------------------- | -------- | ---------------------------------- |
| `PYRIS_DOCKER_TAG`           | `latest` | Docker image tag                   |
| `PYRIS_APPLICATION_YML_FILE` | —        | Path to application config on host |
| `PYRIS_LLM_CONFIG_YML_FILE`  | —        | Path to LLM config on host         |
| `PYRIS_PORT`                 | `8000`   | Host port for the Iris application |
| `WEAVIATE_PORT`              | `8001`   | Host port for Weaviate REST API    |
| `WEAVIATE_GRPC_PORT`         | `50051`  | Host port for Weaviate gRPC        |

See [Local Setup](./local-setup.md) for Docker setup instructions.
