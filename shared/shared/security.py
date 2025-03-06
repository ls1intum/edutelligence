from typing import Callable, List
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.openapi.utils import get_openapi
from starlette.middleware.base import BaseHTTPMiddleware


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware that authenticates all requests using API key."""

    def __init__(
        self,
        app,
        api_key: str,
        exclude_paths: List[str],
        header_name: str,
    ):
        super().__init__(app)
        self.exclude_paths = exclude_paths + [
            "/health",
            "/health/live",
            "/docs",
            "/redoc",
            "/openapi.json",
        ]
        self.api_key = api_key
        self.header_name = header_name

    async def dispatch(self, request: Request, call_next: Callable):
        # Skip authentication for excluded paths
        if any(request.url.path.startswith(path) for path in self.exclude_paths):
            return await call_next(request)

        # Get API key from header
        api_key = request.headers.get(self.header_name)
        if not api_key:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "detail": f"API key is missing, expected in header: '{self.header_name}'"
                },
                headers={"WWW-Authenticate": "ApiKey"},
            )

        # Validate API key
        if api_key != self.api_key:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid API key"},
                headers={"WWW-Authenticate": "ApiKey"},
            )

        return await call_next(request)


def add_security_schema_to_openapi(
    openapi_schema: dict, header_name: str, exclude_paths: List[str]
) -> dict:
    exclude_paths.append("/health")
    exclude_paths.append("/health/live")

    # Add API key security scheme
    openapi_schema["components"] = openapi_schema.get("components", {})
    openapi_schema["components"]["securitySchemes"] = {
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": header_name,
            "description": "API key authentication",
        }
    }

    # Add 401 response for authentication failure
    openapi_schema["components"]["responses"] = openapi_schema.get(
        "components", {}
    ).get("responses", {})
    openapi_schema["components"]["responses"]["UnauthorizedError"] = {
        "description": "Authentication failed - API key is missing or invalid",
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {"detail": {"type": "string"}},
                }
            }
        },
    }

    # Apply security globally except for health endpoint
    openapi_schema["security"] = [{"ApiKeyAuth": []}]

    # Process all paths in the schema
    for path, methods in openapi_schema.get("paths", {}).items():
        if any(path.startswith(ex_path) for ex_path in exclude_paths):
            # Remove security from excluded paths
            for method in methods.values():
                method["security"] = []
        else:
            # Add 401 response to secured endpoints
            for method in methods.values():
                method["responses"] = method.get("responses", {})
                method["responses"]["401"] = {
                    "$ref": "#/components/responses/UnauthorizedError"
                }

    return openapi_schema


# Use this if you do not have any other custom OpenAPI schema modifications to add
def add_security_schema_to_app(
    app: FastAPI, header_name: str, exclude_paths: List[str]
):
    # Custom OpenAPI schema
    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        openapi_schema = add_security_schema_to_openapi(
            openapi_schema, header_name, exclude_paths
        )
        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi
