---
title: LLM Configuration
---

# LLM Configuration

Iris connects to Large Language Models through a configuration file that defines all available models, their providers, and cost tracking information. This page is a deep dive into `llm_config.yml`.

## File Location

The LLM config file path is set via the `LLM_CONFIG_PATH` environment variable:

```bash
export LLM_CONFIG_PATH=/path/to/llm_config.yml
```

In Docker deployments, this is mounted to `/config/llm_config.yml` inside the container automatically.

For local development, create a `llm_config.local.yml` in the `iris/` directory:

```bash
cp llm_config.example.yml llm_config.local.yml
```

## File Structure

The file is a YAML list of model definitions. Each entry defines a single model:

```yaml
- id: "oai-gpt-5-mini"
  name: "GPT 5 Mini"
  description: "GPT 5 Mini on OpenAI"
  type: "openai_chat"
  model: "gpt-5-mini"
  api_key: "<your-api-key>"
  tools: []
  cost_per_million_input_token: 0.4
  cost_per_million_output_token: 1.6
```

## Model Types

Iris supports the following model types, each connecting to a different provider:

| Type               | Provider        | Purpose                          |
| ------------------ | --------------- | -------------------------------- |
| `openai_chat`      | OpenAI API      | Chat completion models           |
| `azure_chat`       | Azure OpenAI    | Chat completion models via Azure |
| `ollama`           | Ollama (local)  | Locally hosted models            |
| `openai_embedding` | OpenAI API      | Text embedding models            |
| `azure_embedding`  | Azure OpenAI    | Text embedding models via Azure  |
| `cohere_azure`     | Cohere on Azure | Reranking models                 |

## Common Fields

These fields are shared across all model types:

| Field         | Required | Description                                                                              |
| ------------- | -------- | ---------------------------------------------------------------------------------------- |
| `id`          | Yes      | Unique identifier across all models (e.g., `oai-gpt-5-mini`)                             |
| `name`        | Yes      | Human-readable display name                                                              |
| `description` | Yes      | Additional information about the model                                                   |
| `type`        | Yes      | Model type (see table above)                                                             |
| `model`       | Yes      | Official model name as used by the vendor (e.g., `gpt-5-mini`, `text-embedding-3-large`) |
| `api_key`     | Yes      | API key for authentication with the provider                                             |

## Type-Specific Fields

### OpenAI Chat (`openai_chat`)

Uses the common fields only. No additional fields required.

```yaml
- id: "oai-gpt-52"
  name: "GPT 5.2"
  description: "GPT 5.2"
  type: "openai_chat"
  model: "gpt-5.2"
  api_key: "<your-openai-api-key>"
  tools: []
  cost_per_million_input_token: 3.0
  cost_per_million_output_token: 12.0
```

### Azure Chat (`azure_chat`)

Requires additional Azure-specific fields:

| Field              | Required | Description                                    |
| ------------------ | -------- | ---------------------------------------------- |
| `endpoint`         | Yes      | Azure OpenAI endpoint URL                      |
| `api_version`      | Yes      | Azure API version (e.g., `2025-04-01-preview`) |
| `azure_deployment` | Yes      | Deployment name in Azure                       |

```yaml
- id: "azure-gpt-5-mini"
  name: "GPT 5 Mini (Azure)"
  description: "GPT 5 Mini on Azure"
  type: "azure_chat"
  model: "gpt-5-mini"
  api_key: "<your-azure-api-key>"
  endpoint: "https://your-resource.openai.azure.com/"
  api_version: "2025-04-01-preview"
  azure_deployment: "gpt-5-mini"
  tools: []
  cost_per_million_input_token: 0.4
  cost_per_million_output_token: 1.6
```

### Ollama (`ollama`)

For locally hosted models via [Ollama](https://ollama.ai/):

| Field      | Required | Description                                        |
| ---------- | -------- | -------------------------------------------------- |
| `endpoint` | Yes      | Ollama server URL (e.g., `http://localhost:11434`) |

```yaml
- id: "ollama-llama3"
  name: "Llama 3"
  description: "Llama 3 via Ollama"
  type: "ollama"
  model: "llama3"
  api_key: ""
  endpoint: "http://localhost:11434"
  tools: []
  cost_per_million_input_token: 0
  cost_per_million_output_token: 0
```

### OpenAI Embedding (`openai_embedding`)

For OpenAI text embedding models:

```yaml
- id: "oai-embedding-small"
  name: "Embedding Small"
  description: "Embedding Small 8k"
  type: "openai_embedding"
  model: "text-embedding-3-small"
  api_key: "<your-openai-api-key>"
  cost_per_million_input_token: 0.02
```

### Azure Embedding (`azure_embedding`)

For Azure-hosted embedding models:

```yaml
- id: "azure-embedding-large"
  name: "Embedding Large"
  description: "Embedding Large 8k Azure"
  type: "azure_embedding"
  model: "text-embedding-3-large"
  api_key: "<your-azure-api-key>"
  endpoint: "https://your-resource.openai.azure.com/"
  api_version: "2023-05-15"
  azure_deployment: "te-3-large"
  cost_per_million_input_token: 0.13
```

### Cohere Azure Reranker (`cohere_azure`)

For Cohere reranking models hosted on Azure:

| Field                  | Required | Description                             |
| ---------------------- | -------- | --------------------------------------- |
| `endpoint`             | Yes      | Cohere Azure endpoint URL               |
| `cost_per_1k_requests` | No       | Cost tracking per 1,000 rerank requests |

```yaml
- id: "cohere"
  name: "Cohere Client V2"
  description: "Cohere V2 client"
  type: "cohere_azure"
  model: "rerank-multilingual-v3.5"
  api_key: "<your-cohere-api-key>"
  endpoint: "https://your-cohere-endpoint"
  cost_per_1k_requests: 2
```

## Cost Tracking

Cost fields are optional but recommended for monitoring usage:

| Field                           | Description                                      |
| ------------------------------- | ------------------------------------------------ |
| `cost_per_million_input_token`  | Cost in USD per million input tokens             |
| `cost_per_million_output_token` | Cost in USD per million output tokens            |
| `cost_per_1k_requests`          | Cost per 1,000 API requests (used for rerankers) |

These values are used by Iris's observability layer (see [Monitoring](./monitoring.md)) to track and report LLM spending.

## Tools Field

The `tools` field is a list that specifies which tools (function calling capabilities) the model supports. For most configurations, use an empty list:

```yaml
tools: []
```

## Required Models

:::warning
Most Iris pipelines require specific model families to be configured. At minimum, you need:

- A **chat model** (e.g., GPT-4.1 or GPT-5 family)
- An **embedding model** (e.g., `text-embedding-3-small` or `text-embedding-3-large`)

Some features additionally require a **reranker model**. Watch the Iris logs at startup for warnings about missing models.
:::

## Hot Reloading

:::tip
Changes to `llm_config.yml` require a restart of the Iris application to take effect. The file is read once at startup.
:::

## Validating Configuration

After starting Iris, check the logs for any model loading errors:

```bash
docker compose -f <compose-file> logs pyris-app | grep -i "model\|llm\|config"
```

You can also verify the health endpoint to confirm pipelines loaded correctly:

```bash
curl -H "Authorization: <your-token>" http://localhost:8000/api/v1/health/
```

If the `Pipelines` module shows `DOWN`, there is likely a model configuration issue.
