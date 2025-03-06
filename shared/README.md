# Shared

This library contains shared utilities for EduTelligence services.

## Authentication

The `shared.security` module provides API key authentication for FastAPI applications.

### AuthMiddleware

A middleware that authenticates all requests using an API key in the HTTP headers.

```python
from fastapi import FastAPI
from shared.security import AuthMiddleware

app = FastAPI()

# Add authentication middleware
app.add_middleware(
    AuthMiddleware,
    api_key="your-secret-api-key",
    header_name="X-API-Key",
    exclude_paths=["/public", "/playground"]
)
```

#### Parameters

- `api_key`: The secret API key that clients must provide
- `header_name`: The HTTP header name where the API key should be provided
- `exclude_paths`: List of URL paths that should not require authentication

### OpenAPI Integration

To document the authentication in the OpenAPI schema (used for `/docs`):

```python
from shared.security import add_security_schema_to_app

# Add security schema to OpenAPI documentation
add_security_schema_to_app(
    app, 
    header_name="X-API-Key", 
    exclude_paths=["/public", "/playground"]
)
```

This automatically adds:

- The API key security scheme to your OpenAPI documentation
- 401 responses for secured endpoints
- Security requirements for all endpoints except excluded paths

## Health Check

The `shared.health` module provides standardized health check endpoints for FastAPI applications.

### Creating Health Check Endpoints

Add health check endpoints to your FastAPI application:

```python
from fastapi import FastAPI
from shared.health import create_health_router

app = FastAPI(version="1.0.0")

# Add health check router
app.include_router(create_health_router(app.version))
```

#### Parameters for `create_health_router`

- `app_version`: The version of the application 
- `prefix`: URL prefix for the health endpoints (default: "/health")
- `tags`: OpenAPI tags for the health endpoints (default: ["healthcheck"])
- `system_info`: Whether to include system information in health check (default: True)

### Registering Component Health Checks

Register health checks for specific components in your application:

```python
from shared.health import register_component

@register_component("database")
def database_health_check():
    try:
        # Perform database connection check
        connection_ok = check_database_connection()
        return {
            "status": "OK" if connection_ok else "ERROR",
            "details": {
                "connection_pool": "active",
                "latency_ms": 5
            } if connection_ok else None
        }
    except Exception as e:
        return {
            "status": "ERROR",
            "details": {"error": str(e)}
        }
```

### Available Endpoints

The health check router creates two endpoints:

1. `/health` - Comprehensive health check that includes:
   - Overall system status
   - Application version
   - Uptime in seconds
   - Status of all registered components
   - System information (if enabled)

2. `/health/live` - Simple liveness check that returns immediately if the service is running

### Health Status

Health checks use the following status values:

- `OK`: Component is functioning normally
- `WARNING`: Component has issues but is still operational
- `ERROR`: Component is not functioning correctly