---
title: Compatibility
---

# Compatibility

## General Compatibility

Iris (also known as Pyris) ships as part of the [EduTelligence](https://github.com/ls1intum/edutelligence) suite, and every service in the suite shares one version number. Each EduTelligence version targets a specific [Artemis](https://github.com/ls1intum/Artemis) release line.

:::warning
Run matching versions from the same release cycle. Pairing an Artemis release with an EduTelligence version outside the row below is untested: features may be missing, and the Artemis-to-Pyris request contract may not match.
:::

## Version Compatibility Matrix

| Artemis Version | EduTelligence Version | Status    |
| --------------- | --------------------- | --------- |
| 8.0.x           | 1.0.x                 | ✅ Stable |
| 8.1.0 - 8.2.4   | 1.1.x                 | ✅ Stable |
| 8.3.0 - 8.3.4   | 1.3.x                 | ✅ Stable |
| 8.4.0 - 8.4.4   | 1.4.x                 | ✅ Stable |
| 8.5.x           | 1.5.x                 | ✅ Stable |
| 8.6.0 - 8.6.1   | 1.6.0                 | ✅ Stable |
| 8.6.2 - 8.6.4   | 1.6.2                 | ✅ Stable |
| 8.7.0 - 8.7.1   | 1.7.0                 | ✅ Stable |
| 8.7.2 - 8.7.4   | 1.7.2                 | ✅ Stable |
| 8.8.x           | 1.8.0                 | ✅ Stable |
| 9.0.x           | 2.0.x                 | ✅ Stable |
| 9.1.x           | 2.1.x                 | ✅ Stable |
| 9.2.x           | 2.2.x                 | ✅ Stable |
| 9.3.x           | 2.3.x                 | ✅ Stable |
| 9.4.x           | 2.4.x                 | ✅ Stable |
| 9.5.x           | 2.5.x                 | ✅ Stable |
| 9.6.x           | 2.6.x                 | ✅ Stable |
| 9.7.x - 9.9.x   | 2.7.x                 | ✅ Stable |
| 10.0.x          | 3.0.x                 | ✅ Stable |

The same table is maintained in the [EduTelligence README](https://github.com/ls1intum/edutelligence#-artemis-compatibility); update both when cutting a release.

## Choosing an Image Tag

Released versions are published to the GitHub Container Registry as `ghcr.io/ls1intum/edutelligence/iris:<version>` (for example `ghcr.io/ls1intum/edutelligence/iris:3.0`). Pin production deployments to an explicit version rather than `latest`, so that an upgrade is a deliberate change and a rollback is a single tag change. See [Deployment](../admin/deployment.md).

## Requirements

| Requirement        | Details                                         |
| ------------------ | ----------------------------------------------- |
| **Python**         | 3.13 or higher                                  |
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
