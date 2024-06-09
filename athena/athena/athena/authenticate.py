import inspect
from functools import wraps
from typing import Callable

from fastapi import HTTPException, Depends
from fastapi.security import APIKeyHeader

from athena import env
from athena.contextvars import set_lms_url_context_var
from athena.logger import logger

api_key_auth_header = APIKeyHeader(name='Authorization', auto_error=False)
api_key_lms_url_header = APIKeyHeader(name='X-Server-URL', auto_error=False)



def verify_inter_module_secret_key(secret: str):
    if secret != env.ASSESSMENT_MODULE_MANAGER_TO_ATHENA_MODULE_SECRET:
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
    async def wrapper(*args, secret: str = Depends(api_key_auth_header),
                      lms_url: str = Depends(api_key_lms_url_header),
                      **kwargs):
        verify_inter_module_secret_key(secret)  # this happens after the ASM Module reissued the request
        set_lms_url_context_var(lms_url)
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
