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

| Type                   | Provider                                      | Purpose                                        |
| ---------------------- | --------------------------------------------- | ---------------------------------------------- |
| `openai_chat`          | OpenAI API                                    | Chat completion models                         |
| `azure_chat`           | Azure OpenAI                                  | Chat completion models via Azure               |
| `ollama`               | Ollama (local)                                | Locally hosted models                          |
| `openai_embedding`     | OpenAI API or an OpenAI-compatible gateway    | Text embedding models                          |
| `azure_embedding`      | Azure OpenAI                                  | Text embedding models via Azure                |
| `cohere_azure`         | Cohere on Azure                               | Reranking models                               |
| `vllm_rerank`          | vLLM-served cross-encoder, e.g. through Logos | Reranking models                               |
| `passthrough_reranker` | Local                                         | Preserve vector-search order without reranking |

## Common Fields

These fields are shared across all model types:

| Field         | Required | Description                                                                              |
| ------------- | -------- | ---------------------------------------------------------------------------------------- |
| `id`          | Yes      | Unique identifier across all models (e.g., `oai-gpt-5-mini`)                             |
| `name`        | Yes      | Human-readable display name                                                              |
| `description` | Yes      | Additional information about the model                                                   |
| `type`        | Yes      | Model type (see table above)                                                             |
| `model`       | Yes      | Official model name as used by the vendor (e.g., `gpt-5-mini`, `text-embedding-3-large`) |
| `api_key`     | Provider | API key for external providers; omit for the passthrough reranker                        |

## Type-Specific Fields

### OpenAI Chat (`openai_chat`)

Needs only the common fields. A reasoning model additionally declares the reasoning effort it accepts; see
[Reasoning Effort](#reasoning-effort).

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

### Reasoning Effort

Reasoning models such as the GPT-5 family trade answer latency for reasoning tokens. How much they reason is set per
model entry, so one model can appear several times with different efforts, for example a fast `minimal` entry for the
global search answer and a `medium` entry for the chat. The fields apply to `openai_chat` and `azure_chat`:

| Field                       | Default | Description                                                                                                  |
| --------------------------- | ------- | ------------------------------------------------------------------------------------------------------------ |
| `supports_reasoning_effort` | `false` | Whether the model accepts the `reasoning_effort` request parameter.                                          |
| `reasoning_effort`          | none    | The effort sent when a pipeline requests none itself: `none`, `minimal`, `low`, `medium`, `high` or `xhigh`. |
| `reasoning_effort_values`   | none    | The efforts this model accepts. A requested effort outside the list is clamped to the nearest listed one.    |

```yaml
- id: "oai-gpt-5-mini-minimal"
  type: "openai_chat"
  model: "gpt-5-mini"
  api_key: "<your-openai-api-key>"
  supports_temperature: false
  supports_reasoning_effort: true
  reasoning_effort: minimal
  reasoning_effort_values: [minimal, low, medium, high]
  cost_per_million_input_token: 0.4
  cost_per_million_output_token: 1.6
```

A pipeline that requests an effort itself overrides `reasoning_effort`. For a model without
`supports_reasoning_effort`, the request is sent without the parameter and a log line names the ignored value, so a
pipeline can request an effort without knowing the model. Configuring `reasoning_effort` or `reasoning_effort_values`
without `supports_reasoning_effort: true`, an empty `reasoning_effort_values`, or a `reasoning_effort` that is not in
`reasoning_effort_values` fails at startup. Reasoning models usually reject `temperature`, so they also set
`supports_temperature: false`.

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

For locally or remotely hosted models via [Ollama](https://ollama.ai/). Ollama models can serve as both chat models and embedding models.

| Field  | Required | Description                                        |
| ------ | -------- | -------------------------------------------------- |
| `host` | Yes      | Ollama server URL (e.g., `http://localhost:11434`) |

:::warning
The field is `host`, **not** `endpoint`. Using `endpoint` will cause a configuration error at startup.
:::

```yaml
- id: "ollama-llama3"
  name: "Llama 3"
  description: "Llama 3 via Ollama"
  type: "ollama"
  model: "llama3"
  api_key: ""
  host: "http://localhost:11434"
  tools: []
  cost_per_million_input_token: 0
  cost_per_million_output_token: 0
```

Ollama also supports embedding models. Use `mxbai-embed-large` or `nomic-embed-text` for RAG:

```yaml
- id: "mxbai-embed-large"
  name: "mxbai-embed-large"
  description: "Ollama embedding model"
  type: "ollama"
  model: "mxbai-embed-large:latest"
  host: "http://localhost:11434"
  api_key: ""
  cost_per_million_input_token: 0
  cost_per_million_output_token: 0
```

### OpenAI Embedding (`openai_embedding`)

For OpenAI text embedding models, and for any embedding model behind an OpenAI-compatible endpoint:

| Field                   | Required | Description                                                                                                     |
| ----------------------- | -------- | --------------------------------------------------------------------------------------------------------------- |
| `base_url`              | No       | OpenAI-compatible endpoint, for example a vLLM server or Logos. Without it, the official OpenAI API is used.    |
| `retrieval_instruction` | No       | Text put in front of a search query before it is embedded; see [Retrieval Instruction](#retrieval-instruction). |

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

### Passthrough Reranker (`passthrough_reranker`)

Use the passthrough reranker when no external reranking service is available.
It performs no network request and returns the first `top_n` valid vector-search
results in their existing order. Retrieval remains functional, but relevance
quality can be lower than with a dedicated reranker.

```yaml
- id: "passthrough-reranker"
  name: "Passthrough reranker"
  description: "Preserve vector-search order"
  type: "passthrough_reranker"
  model: "passthrough"
  cost_per_1k_requests: 0
```

### vLLM Reranker (`vllm_rerank`)

For a cross-encoder served by vLLM, such as Qwen3-Reranker, behind a Jina- or Cohere-compatible `/rerank` endpoint:

| Field                     | Required | Description                                                                                                                                                                          |
| ------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `base_url`                | Yes      | Base URL of the server, for example a Logos instance                                                                                                                                 |
| `rerank_path`             | No       | Path of the rerank endpoint, default `/rerank`                                                                                                                                       |
| `request_timeout`         | No       | Request timeout in seconds, default `10.0`                                                                                                                                           |
| `instruction`             | No       | Instruction folded into the query. Leave it empty when the server applies the reranker's chat template, as Logos does for Qwen3-Reranker-8B; a second instruction lowers the scores. |
| `rerank_floor_calibrated` | No       | Set to `true` only for Qwen3-Reranker-8B, against which `global_search_rerank_floor` is calibrated. Default `false`, which skips the floor.                                          |

```yaml
- id: "qwen3-reranker"
  name: "Qwen3 Reranker 8B"
  description: "Qwen3-Reranker-8B through Logos"
  type: "vllm_rerank"
  model: "Qwen/Qwen3-Reranker-8B"
  base_url: "https://your-logos-instance"
  api_key: "<your-logos-api-key>"
  rerank_floor_calibrated: true
  cost_per_1k_requests: 0
```

Global search uses the `reranker` role of `global_search_pipeline`, and falls back to that of `lecture_retrieval_pipeline`. See [Global search](../developer/global-search.md#ranking).

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

## Embedding Model Configuration

Iris uses embedding models for Retrieval-Augmented Generation (RAG): ingested lecture content, FAQs, and transcriptions are all stored as vectors in Weaviate and retrieved using the same embedding model at query time. **The embedding model used during ingestion must be the same model used during retrieval.** Changing embedding models requires a full re-index of all content.

### Supported Embedding Types

| `type`             | Provider                                                    | Notes                                                                                        |
| ------------------ | ----------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `openai_embedding` | OpenAI API, or an OpenAI-compatible gateway with `base_url` | `text-embedding-3-small`, `text-embedding-3-large`, or Qwen3-Embedding through Logos or vLLM |
| `azure_embedding`  | Azure OpenAI                                                | Same models, deployed on Azure                                                               |
| `ollama`           | Ollama                                                      | e.g., `mxbai-embed-large`, `nomic-embed-text`                                                |

### Client-Side (`self_provided`) Vectors

Iris uses client-side embedding: the application calls the embedding model, computes the vector, and supplies it directly to Weaviate during both ingestion and retrieval. Weaviate is configured with `DEFAULT_VECTORIZER_MODULE=none` — it never generates its own embeddings. This means:

- Any embedding model type supported by Iris (`openai_embedding`, `azure_embedding`, `ollama`) can be used without changes to the Weaviate setup.
- Weaviate collections are created with `Configure.Vectors.self_provided()`, so no Weaviate vectorizer module needs to be installed.

### Retrieval Instruction

Instruction-tuned embedding models such as Qwen3-Embedding expect a search query to be embedded with an instruction in front of it, while the documents are embedded as they are. Set the instruction once on the model entry, and Iris adds it to the query of the global search retrieval only, never to ingested content:

```yaml
- id: "qwen3-embedding"
  name: "Qwen3 Embedding 8B"
  description: "Qwen3-Embedding-8B through Logos"
  type: "openai_embedding"
  model: "Qwen/Qwen3-Embedding-8B"
  base_url: "https://your-logos-instance/v1"
  api_key: "<your-logos-api-key>"
  retrieval_instruction: >-
    Instruct: Given a search query from a university student, retrieve
    relevant passages from lecture materials that answer or cover the
    query
    Query:
  cost_per_million_input_token: 0
```

Do not set `retrieval_instruction` on a plain OpenAI or Azure model: it has no instruction protocol and would embed the instruction as part of the query.

:::info TUM-internal deployment
The TUM deployment embeds all Iris collections with Qwen3-Embedding-8B through Logos, the LLM gateway that Artemis also uses for its global search index. Global search reranks with Qwen3-Reranker-8B through Logos. Other deployments can use any of the embedding and reranker types above.
:::

### Embedding Dimensions

Different embedding models produce vectors of different sizes. Iris does **not** validate dimension consistency at startup — misconfigured dimensions will cause silent retrieval failures (zero similarity scores). The dimension is implicit in the model; you do not set it in `llm_config.yml`. Common values:

| Model                    | Dimensions |
| ------------------------ | ---------- |
| `Qwen3-Embedding-8B`     | 4096       |
| `text-embedding-3-small` | 1536       |
| `text-embedding-3-large` | 3072       |
| `mxbai-embed-large`      | 1024       |
| `nomic-embed-text`       | 768        |

:::warning
If you switch embedding models after ingestion, re-ingest all content from Artemis. Mixing vectors of different dimensions or from different models in the same collection will silently degrade retrieval quality.
:::

### Assigning Embedding Models to Pipelines

In `application.yml`, embedding models are assigned by referencing their `id` from `llm_config.yml` under the `llm_configuration` section. Example:

```yaml
llm_configuration:
  lecture_unit_page_ingestion_pipeline:
    default:
      embedding: qwen3-embedding # matches id in llm_config.yml
  lecture_retrieval_pipeline:
    default:
      embedding: qwen3-embedding # must be the same model used for ingestion
```

See `application.example.yml` in the repository for the full list of pipelines that require an embedding model.

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
