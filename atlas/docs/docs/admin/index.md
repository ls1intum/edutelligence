# Administration Guide

Welcome to the AtlasML Administration Guide! This guide provides comprehensive documentation for deploying, configuring, and maintaining AtlasML in production environments.

## About AtlasML

AtlasML is a FastAPI-based microservice that provides AI-powered competency management features for the Artemis learning platform. It requires a centralized Weaviate vector database, Azure OpenAI for embeddings, and is deployed exclusively via Docker Compose for production workloads.

## Prerequisites

Before deploying AtlasML, ensure you have:

- Docker and Docker Compose installed on your server
- A centralized Weaviate instance (see [Weaviate Setup Guide](https://github.com/ls1intum/edutelligence/blob/main/weaviate/README.md))
- Azure OpenAI API credentials for embedding generation
- API keys for securing AtlasML endpoints
- Basic knowledge of Docker, environment variables, and reverse proxies

## Quick Start

Follow this checklist to deploy AtlasML to production:

**Deployment Checklist:**
- [ ] Set up the centralized [Weaviate instance](https://github.com/ls1intum/edutelligence/blob/main/weaviate/README.md) with Traefik and API key authentication (required prerequisite)
- [ ] Follow the [Installation Guide](./atlasml-installation.md) to deploy AtlasML with Docker Compose
- [ ] Configure all required environment variables using the [Configuration Reference](./atlasml-configuration.md)
- [ ] Review [Deployment Best Practices](./atlasml-deployment.md) for production hardening and CI/CD setup
- [ ] Set up [Monitoring](./atlasml-monitoring.md) with health checks, logging, and optional Sentry integration
- [ ] Test your deployment and refer to [Troubleshooting](./atlasml-troubleshooting.md) if issues arise

## Documentation Sections

### [Installation](./atlasml-installation.md)
Step-by-step guide to deploy AtlasML using Docker Compose, including Weaviate setup, environment configuration, and initial deployment.

### [Configuration](./atlasml-configuration.md)
Complete reference for all environment variables, including Weaviate connection settings, Azure OpenAI credentials, API keys, and optional Sentry integration.

### [Deployment](./atlasml-deployment.md)
Production best practices, CI/CD workflows with GitHub Actions, secrets management, and deployment strategies.

### [Monitoring](./atlasml-monitoring.md)
Health check endpoints, log management, container monitoring, and Sentry error tracking for production observability.

### [Troubleshooting](./atlasml-troubleshooting.md)
Common issues and solutions for startup failures, Weaviate connection problems, API errors, and performance issues.

## Architecture Overview

AtlasML follows a microservice architecture:

- **AtlasML Service**: FastAPI application serving REST endpoints
- **Centralized Weaviate**: Shared vector database with HTTPS and API key authentication
- **Azure OpenAI**: Embedding generation service
- **Artemis**: Primary client consuming AtlasML's competency management features

Communication is unidirectional—Artemis calls AtlasML, and AtlasML never initiates requests back to Artemis.

## Support

- **GitHub Repository**: [ls1intum/edutelligence](https://github.com/ls1intum/edutelligence)
- **Issues**: Report bugs and request features on [GitHub Issues](https://github.com/ls1intum/edutelligence/issues)
- **Weaviate Setup**: [Weaviate README](https://github.com/ls1intum/edutelligence/blob/main/weaviate/README.md)
