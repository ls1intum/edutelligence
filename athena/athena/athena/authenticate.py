import inspect
from functools import wraps
from typing import Callable

from fastapi import HTTPException, Depends, Request
from fastapi.security import APIKeyHeader

from athena.settings import Settings
from .logger import logger
from .contextvars import set_lms_url_context_var

api_key_auth_header = APIKeyHeader(name="Authorization", auto_error=False)
api_key_lms_url_header = APIKeyHeader(name="X-Server-URL", auto_error=False)


def get_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        # Fallback to non-prod to avoid hard-crashing in dev
        raise HTTPException(
            status_code=500, detail="Settings not initialized on app.state."
        )
    return settings


def verify_inter_module_secret_key(
    secret: str | None,
    settings: Settings,
):
    if secret != settings.SECRET.get_secret_value():
        if settings.PRODUCTION:
            raise HTTPException(status_code=401, detail="Invalid API secret.")
        logger.warning("DEBUG MODE: Ignoring invalid API secret.")


def authenticated(func: Callable) -> Callable:
    """
    Decorator for endpoints that require authentication.
    """

    @wraps(func)
    async def wrapper(
        *args,
        secret: str | None = Depends(api_key_auth_header),
        lms_url: str | None = Depends(api_key_lms_url_header),
        settings: Settings = Depends(get_settings),
        **kwargs
    ):
        verify_inter_module_secret_key(secret, settings)
        set_lms_url_context_var(lms_url or "")
        if inspect.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        return func(*args, **kwargs)

    # Update the function signature to include all dependencies
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
            inspect.Parameter(
                "settings",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=Depends(get_settings),
            ),
        ]
    )
    wrapper.__signature__ = sig.replace(parameters=params)  # type: ignore
    return wrapper
