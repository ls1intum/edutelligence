import inspect
from functools import wraps
from typing import Callable

from fastapi import HTTPException, Depends, Request
from fastapi.security import APIKeyHeader

from .logger import logger
from .settings import Settings

api_key_auth_header = APIKeyHeader(name="Authorization", auto_error=False)
api_key_lms_url_header = APIKeyHeader(name="X-Server-URL", auto_error=False)


def get_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        raise HTTPException(
            status_code=500, detail="Settings not initialized on app.state."
        )
    return settings


def verify_lms_athena_key(
    lms_url: str,
    secret: str,
    settings: Settings,
):
    if lms_url is None:
        raise HTTPException(status_code=401, detail="Invalid X-Server-URL.")
        # cannot proceed even for local development
        # database entries cannot be set uniquely

    if (
        lms_url not in settings.deployment_secrets
        or secret != settings.deployment_secrets[lms_url]
    ):
        if settings.production:
            raise HTTPException(status_code=401, detail="Invalid API secret.")
        logger.warning("DEBUG MODE: Ignoring invalid LMS Deployment secret.")


def authenticated(func: Callable) -> Callable:
    """
    Decorator for endpoints that require authentication.
    """

    @wraps(func)
    async def wrapper(
        *args,
        secret: str = Depends(api_key_auth_header),
        lms_url: str = Depends(api_key_lms_url_header),
        **kwargs
    ):
        # Get request from kwargs (FastAPI will inject it)
        request = kwargs.get("request")
        if request:
            settings = get_settings(request)
        else:
            # Fallback - create default settings
            from .settings import Settings

            settings = Settings()

        verify_lms_athena_key(lms_url, secret, settings)
        if inspect.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        return func(*args, **kwargs)

    # Update the function signature
    sig = inspect.signature(func)
    params = list(sig.parameters.values())
    params.extend(
        [
            inspect.Parameter(
                "secret",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=Depends(api_key_auth_header),
            ),
            inspect.Parameter(
                "lms_url",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=Depends(api_key_lms_url_header),
            ),
        ]
    )
    wrapper.__signature__ = sig.replace(parameters=params)  # type: ignore
    return wrapper
