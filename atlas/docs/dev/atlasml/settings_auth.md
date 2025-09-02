---
title: 'Settings and Authentication'
---

# Settings and Authentication

## Settings

Module: `atlasml/config.py`. Settings are strongly typed via Pydantic and loaded from environment variables. The service can operate with safe defaults in tests or when explicitly requested, while production requires explicit configuration.

Environment variables:

- `ATLAS_API_KEYS`: Comma-separated list of API key tokens
- `WEAVIATE_HOST`: Weaviate host (e.g., `localhost`)
- `WEAVIATE_PORT`: Weaviate REST port (e.g., `8080`)
- `WEAVIATE_GRPC_PORT`: Weaviate gRPC port (e.g., `50051`)
- `SENTRY_DSN`: Optional Sentry DSN (used when `ENV=production`)
- `ENV`: Environment name (e.g., `dev`, `production`)

Defaults are used in tests or when `get_settings(use_defaults=True)` is explicitly requested. The `ENV` variable also toggles optional production-only features like Sentry error reporting.

## Authentication

Module: `atlasml/dependencies.py`. Authentication uses a simple API-key strategy implemented as FastAPI dependencies. This can be attached per-route or globally depending on deployment needs.

AtlasML uses a simple API key mechanism via the `Authorization` header. Keys are compared verbatim and should be rotated and stored securely via your deployment platform’s secret manager.

- Header: `Authorization: <API_KEY>`
- Keys are read from `ATLAS_API_KEYS` and compared verbatim.
- Use `Depends(TokenValidator)` or `validate_token` on routes to enforce auth. For example, add `dependencies=[Depends(TokenValidator)]` to a router or endpoint.
