from typing import Callable, List
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware

from app.settings import settings
from app.logger import logger


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware that authenticates all requests using API key."""

    def __init__(
        self,
        app,
        exclude_paths: List[str] = None,
        header_name: str = settings.API_KEY_HEADER,
    ):
        super().__init__(app)
        self.exclude_paths = exclude_paths or [
            "/health",
            "/health/live",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/playground",
        ]
        self.header_name = header_name

    async def dispatch(self, request: Request, call_next: Callable):
        # Skip authentication for excluded paths
        if any(request.url.path.startswith(path) for path in self.exclude_paths):
            return await call_next(request)

        # Skip authentication if disabled
        if settings.DISABLE_AUTH:
            return await call_next(request)

        # Get API key from header
        api_key = request.headers.get(self.header_name)
        if not api_key:
            logger.warning(f"API key missing for {request.url.path}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key is missing",
                headers={"WWW-Authenticate": "ApiKey"},
            )

        # Validate API key
        if api_key != settings.API_KEY:
            logger.warning(f"Invalid API key for {request.url.path}: {api_key[:5]}...")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
                headers={"WWW-Authenticate": "ApiKey"},
            )

        return await call_next(request)


def add_security_schema_to_openapi(openapi_schema: dict) -> dict:
    # Add API key security scheme
    openapi_schema["components"] = openapi_schema.get("components", {})
    openapi_schema["components"]["securitySchemes"] = {
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": settings.API_KEY_HEADER,
            "description": "API key authentication",
        }
    }

    # Apply security globally except for health endpoint
    openapi_schema["security"] = [{"ApiKeyAuth": []}]

    # Remove security from health endpoint
    for path, methods in openapi_schema.get("paths", {}).items():
        if path == "/health" or path == "/health/live":
            for method in methods.values():
                method["security"] = []

    return openapi_schema
