---
title: 'AtlasML Service Overview'
---

# AtlasML Service Overview

AtlasML is a FastAPI-based microservice that exposes competency-centric ML features through a REST API. It integrates tightly with a Weaviate vector database to persist and query embeddings and domain metadata. The service is designed to be modular and observable, with configurable authentication and optional Sentry integration for production use.

## Architecture

- FastAPI app: `atlasml/app.py`. Creates the application, wires startup/shutdown logic, installs logging middleware, and registers routers. Centralized validation error handling provides consistent 422 responses with debugging details.
- Routers: `atlasml/routers/`. `health.py` offers a minimal liveness check for probes. `competency.py` provides endpoints for suggesting competencies, persisting items, and proposing relations within a course context.
- Models: `atlasml/models/competency.py`. Defines request/response Pydantic models for endpoint contracts and core domain DTOs such as `Competency` and `ExerciseWithCompetencies`.
- Configuration: `atlasml/config.py`. Loads strongly typed settings from environment variables, including API keys, Weaviate endpoints, and optional Sentry DSN. Safe defaults are used in tests or when explicitly requested.
- Auth dependencies: `atlasml/dependencies.py`. Supplies `TokenValidator`/`validate_token` dependencies to enforce a simple API-key based authorization using the `Authorization` header.
- Weaviate client: `atlasml/clients/weaviate.py`. Manages a singleton Weaviate connection, bootstraps collections and properties, and exposes high-level CRUD/search helpers.

## Runtime

- Sentry (optional) is initialized automatically when `ENV=production` and `SENTRY_DSN` is set. This captures errors and traces with PII only when explicitly enabled.
- Request/response logging middleware emits concise request lines, best-effort bodies for POST, response codes, and end-to-end duration. This supports rapid debugging in dev and observability in staging.
- The Weaviate client is checked on startup for liveness and closed gracefully on shutdown, ensuring connections are released and schemas are validated before requests hit the endpoints.

```{toctree}
:maxdepth: 2
:caption: AtlasML Details

api
models
settings_auth
weaviate
```
