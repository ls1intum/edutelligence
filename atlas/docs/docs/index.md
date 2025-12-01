# Atlas: Competency Based Learning Management System

Welcome to the Atlas documentation!

## What is AtlasML?

AtlasML is a FastAPI-based microservice that provides AI-powered competency management features for the Artemis learning platform. It uses machine learning and vector embeddings to suggest competencies, cluster exercises, and analyze learning relationships—all backed by a centralized Weaviate vector database shared across multiple microservices.

## Main Features

- **Competency Suggestions** - AI-powered competency recommendations for exercises based on semantic similarity
- **Exercise Clustering** - Automatic grouping of exercises by semantic similarity for course organization
- **Vector Embeddings** - Azure OpenAI integration for generating multi-modal embeddings
- **Centralized Vector Database** - Shared Weaviate instance for cross-microservice semantic search
- **REST API** - FastAPI-based endpoints for integration with Artemis
- **Type Safety** - Pydantic models for robust data validation and API contracts

## Who Should Read This Documentation?

### 🛠️ Administrators (DevOps/Deployment)

If you need to deploy, configure, or maintain AtlasML in production, start here:

**Quick Start Checklist:**
- [ ] Set up the centralized [Weaviate instance](https://github.com/ls1intum/edutelligence/blob/main/weaviate/README.md) (required prerequisite)
- [ ] Follow the [Installation Guide](./admin/atlasml-installation.md) to deploy AtlasML with Docker Compose
- [ ] Configure environment variables using the [Configuration Reference](./admin/atlasml-configuration.md)
- [ ] Review [Deployment Best Practices](./admin/atlasml-deployment.md) for production setup
- [ ] Set up [Monitoring](./admin/atlasml-monitoring.md) to track service health

**Key Sections:**
- **[Admin Guide Overview](./admin/index.md)** - Introduction to AtlasML administration
- **[Installation](./admin/atlasml-installation.md)** - Docker Compose deployment steps
- **[Configuration](./admin/atlasml-configuration.md)** - Complete environment variable reference
- **[Deployment](./admin/atlasml-deployment.md)** - Production best practices and CI/CD
- **[Monitoring](./admin/atlasml-monitoring.md)** - Health checks, logs, and metrics
- **[Troubleshooting](./admin/atlasml-troubleshooting.md)** - Common issues and solutions

### 👨‍💻 Contributors (Developers)

If you want to contribute code, fix bugs, or understand AtlasML's internals, start here:

**Quick Start Checklist:**
- [ ] Read the [Development Process](./dev/development-process/index.md) to understand our workflow
- [ ] Follow the [Setup Guide](./dev/setup.md) to get your local environment running
- [ ] Review [System Design](./dev/system-design.md) to understand the architecture
- [ ] Explore [AtlasML Internals](./dev/atlasml/overview.md) for detailed API and data model documentation

**Key Sections:**
- **[Development Process](./dev/development-process/index.md)** - Git workflow, PR process, and contribution guidelines
- **[System Design](./dev/system-design.md)** - Architecture overview and design decisions
- **[Setup Guide](./dev/setup.md)** - Local development environment setup
- **[Test Guide](./dev/testing.md)** - Testing practices and running tests
- **[Code Reference](./dev/code-reference/modules.md)** - Detailed code documentation
- **[AtlasML Internals](./dev/atlasml/overview.md)** - API endpoints, models, authentication, and Weaviate integration

## Quick Links

- [GitHub Repository](https://github.com/ls1intum/edutelligence)
- [Weaviate Setup Guide](https://github.com/ls1intum/edutelligence/blob/main/weaviate/README.md)
- [REST API Reference](./dev/atlasml/api.md)
- [Troubleshooting Guide](./admin/atlasml-troubleshooting.md)
