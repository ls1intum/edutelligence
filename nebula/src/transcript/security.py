from typing import Callable, List
from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware that authenticates all requests using an API key."""

    def __init__(self, app, api_key: str, exclude_paths: List[str], header_name: str = "Authorization"):
        super().__init__(app)
        self.api_key = api_key
        self.exclude_paths = exclude_paths + [
            "/health", "/health/live", "/docs", "/redoc", "/openapi.json"
        ]
        self.header_name = header_name

    async def dispatch(self, request: Request, call_next: Callable):
        if any(request.url.path.startswith(p) for p in self.exclude_paths):
            return await call_next(request)

        token = request.headers.get(self.header_name)
        if token != self.api_key:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "Unauthorized"})

        return await call_next(request)
