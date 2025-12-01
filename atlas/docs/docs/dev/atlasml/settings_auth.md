---
title: 'Settings and Authentication'
---

# Settings and Authentication

## Settings

Module: `atlasml/config.py`. Settings are strongly typed via Pydantic and loaded from environment variables. The service can operate with safe defaults in tests or when explicitly requested, while production requires explicit configuration.

Environment variables:

- `ATLAS_API_KEYS`: JSON array of API key tokens (e.g., `["key1","key2"]`)
- `WEAVIATE_HOST`: Full HTTPS URL of centralized Weaviate instance (e.g., `https://weaviate.example.com`)
- `WEAVIATE_PORT`: Weaviate HTTPS port (always `443` for centralized setup)
- `WEAVIATE_GRPC_PORT`: Weaviate gRPC port (always `50051` for centralized setup)
- `WEAVIATE_API_KEY`: API key for authenticating with centralized Weaviate
- `OPENAI_API_KEY`: Azure OpenAI API key for generating embeddings
- `OPENAI_API_URL`: Azure OpenAI endpoint URL
- `SENTRY_DSN`: Optional Sentry DSN (used when `ENV=production`)
- `ENV`: Environment name (e.g., `dev`, `production`)

:::warning Centralized Weaviate Required
AtlasML requires the centralized Weaviate setup with HTTPS and API key authentication. See the [Admin Configuration Guide](/admin/atlasml-configuration) for complete setup instructions.
:::

Defaults are used in tests or when `get_settings(use_defaults=True)` is explicitly requested. The `ENV` variable also toggles optional production-only features like Sentry error reporting.

## Authentication

Module: `atlasml/dependencies.py`. Authentication uses a simple API-key strategy implemented as FastAPI dependencies. This can be attached per-route or globally depending on deployment needs.

AtlasML uses a simple API key mechanism via the `Authorization` header. Keys are compared verbatim and should be rotated and stored securely via your deployment platform’s secret manager.

- Header: `Authorization: <API_KEY>`
- Keys are read from `ATLAS_API_KEYS` and compared verbatim.
- Use `Depends(TokenValidator)` or `validate_token` on routes to enforce auth. For example, add `dependencies=[Depends(TokenValidator)]` to a router or endpoint.
