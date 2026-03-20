---
title: Compatibility
---

# Compatibility

## General Compatibility

Iris is designed to work with the **latest version of Artemis**. The Iris service (also known as Pyris) is versioned independently but tested against Artemis releases. If you are running an older version of Artemis, some Iris features may not be available or may behave differently.

:::warning
There is no formal version compatibility matrix at this time. Iris follows a rolling release model aligned with Artemis development. Always use matching versions from the same release cycle.
:::

## Requirements

| Requirement        | Details                                         |
| ------------------ | ----------------------------------------------- |
| **Python**         | 3.12 or higher                                  |
| **Docker**         | Required for running Weaviate (vector database) |
| **LLM API access** | At least one supported LLM provider (see below) |

## Supported LLM Providers

| Provider         | Status       | Notes                                                                             |
| ---------------- | ------------ | --------------------------------------------------------------------------------- |
| **OpenAI**       | Recommended  | Best tested and most widely used in production                                    |
| **Azure OpenAI** | Supported    | Enterprise deployments with Azure compliance requirements                         |
| **Ollama**       | Experimental | Local model inference — useful for development and privacy-sensitive environments |

:::tip
For production deployments, OpenAI is the recommended provider. Azure OpenAI is a solid alternative for institutions that require Azure-based infrastructure. Ollama support is experimental and intended primarily for local development or research setups.
:::

## Deployment Options

Iris can be deployed in several ways:

- **Docker Compose** — simplest setup for development and small deployments
- **Kubernetes** — recommended for production environments
- **Local development** — run directly with Poetry for contributing to the project

For detailed setup instructions, see the [Administrator Guide](/docs/admin/deployment).
