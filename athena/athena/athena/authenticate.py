import inspect
import os
from functools import wraps
from typing import Callable

from fastapi import HTTPException, Depends
from fastapi.security import APIKeyHeader

from athena import env
from athena.logger import logger

SECRET = os.getenv("SECRET")

api_key_header = APIKeyHeader(name='X-API-Secret', auto_error=False)


def verify_secret(secret: str):
    if secret != SECRET:
        if env.PRODUCTION:
            raise HTTPException(status_code=401, detail="Invalid API secret.")
        logger.warning("DEBUG MODE: Ignoring invalid API secret.")


def authenticated(func: Callable) -> Callable:
    """
        Decorator for endpoints that require authentication.
        Usage:
        @app.post("/endpoint")
        @authenticated
        def endpoint():
            ...
        """

    @wraps(func)
    async def wrapper(*args, secret: str = Depends(api_key_header), **kwargs):
        verify_secret(secret)
        if inspect.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        return func(*args, **kwargs)

    # Update the function signature with the 'secret' parameter, but otherwise keep the annotations intact
    sig = inspect.signature(func)
    params = list(sig.parameters.values())
    params.append(inspect.Parameter('secret', inspect.Parameter.POSITIONAL_OR_KEYWORD, default=Depends(api_key_header)))
    new_sig = sig.replace(parameters=params)
    wrapper.__signature__ = new_sig  # type: ignore # https://github.com/python/mypy/issues/12472

    return wrapper
