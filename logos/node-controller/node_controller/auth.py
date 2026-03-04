"""
Authentication via FastAPI dependency injection.

Uses ``Depends(verify_api_key)`` on protected routes instead of middleware,
avoiding the Starlette BaseHTTPMiddleware performance overhead.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from node_controller.config import get_config

logger = logging.getLogger("node_controller.auth")

_bearer_scheme = HTTPBearer(auto_error=False)


async def verify_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """
    Validate the Bearer token against the configured API key.

    Returns the validated key on success.
    Raises 401 if missing, 403 if invalid.
    """
    if credentials is None or not credentials.credentials:
        logger.warning(
            "Missing auth token from %s",
            request.client.host if request.client else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    expected = get_config().controller.api_key
    if not hmac.compare_digest(credentials.credentials, expected):
        logger.warning(
            "Invalid auth token from %s",
            request.client.host if request.client else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid authentication token",
        )

    return credentials.credentials
