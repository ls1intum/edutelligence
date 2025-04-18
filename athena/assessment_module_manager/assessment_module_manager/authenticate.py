import inspect
from functools import wraps
from typing import Callable

from fastapi import HTTPException, Depends
from fastapi.security import APIKeyHeader

from assessment_module_manager import env
from athena.logger import logger

api_key_auth_header = APIKeyHeader(name='Authorization', auto_error=False)
api_key_lms_url_header = APIKeyHeader(name='X-Server-URL', auto_error=False)


def verify_lms_athena_key(lms_url: str, secret: str):
    if lms_url is None:
        raise HTTPException(status_code=401, detail="Invalid X-Server-URL.")
        # cannot proceed even for local development
        # database entries cannot be set uniquely

    if lms_url not in env.DEPLOYMENT_SECRETS or secret != env.DEPLOYMENT_SECRETS[lms_url]:
        if env.PRODUCTION:
            raise HTTPException(status_code=401, detail="Invalid API secret.")
        logger.warning("DEBUG MODE: Ignoring invalid LMS Deployment secret.")


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
    async def wrapper(*args, secret: str = Depends(api_key_auth_header),
                      lms_url: str = Depends(api_key_lms_url_header),
                      **kwargs):
        verify_lms_athena_key(lms_url, secret)  # this happens in scope of the ASM Module
        if inspect.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        return func(*args, **kwargs)

    # Update the function signature with the 'secret' parameter, but otherwise keep the annotations intact
    sig = inspect.signature(func)
    params = list(sig.parameters.values())
    params.append(
        inspect.Parameter('secret', inspect.Parameter.POSITIONAL_OR_KEYWORD, default=Depends(api_key_auth_header)))
    params.append(inspect.Parameter('lms_url', inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                    default=Depends(api_key_lms_url_header)))
    new_sig = sig.replace(parameters=params)
    wrapper.__signature__ = new_sig  # type: ignore # https://github.com/python/mypy/issues/12472

    return wrapper
