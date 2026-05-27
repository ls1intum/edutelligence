import hmac
import inspect
from functools import wraps
from typing import Callable

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader
from starlette.requests import Request as StarletteRequest

from assessment_module_manager import env
from assessment_module_manager.logger import logger

api_key_auth_header = APIKeyHeader(name='Authorization', auto_error=False)


def _extract_authorization_secret(secret: str | None) -> str | None:
    if secret is None:
        return None

    stripped_secret = secret.strip()
    if not stripped_secret:
        return None

    scheme, _, value = stripped_secret.partition(" ")
    if scheme.lower() == "bearer" and value:
        return value.strip() or None
    return stripped_secret


def resolve_lms_url_from_secret(secret: str | None) -> str:
    provided_secret = _extract_authorization_secret(secret)
    if provided_secret is None:
        logger.warning("Authentication failed: missing or empty Authorization header")
        raise HTTPException(status_code=401, detail="Invalid API secret.")

    provided_secret_str = str(provided_secret)

    matching_lms_urls = [
        lms_url
        for lms_url, configured_secret in env.DEPLOYMENT_SECRETS.items()
        if hmac.compare_digest(
            "" if configured_secret is None else str(configured_secret),
            provided_secret_str,
        )
    ]

    if len(matching_lms_urls) == 1:
        logger.debug("Resolved LMS URL from Authorization header: %s", matching_lms_urls[0])
        return matching_lms_urls[0]

    if len(matching_lms_urls) > 1:
        logger.error(
            "Authentication failed: Authorization header matches multiple LMS deployments: %s",
            matching_lms_urls,
        )
        raise HTTPException(
            status_code=401,
            detail="Ambiguous API secret. Configure unique LMS secrets for each deployment.",
        )

    if env.PRODUCTION:
        logger.warning("Authentication failed: Authorization header did not match any configured LMS deployment")
        raise HTTPException(status_code=401, detail="Invalid API secret.")

    logger.warning("DEBUG MODE: Authorization header did not match any configured LMS deployment")
    raise HTTPException(status_code=401, detail="Invalid API secret.")


def get_resolved_lms_url(request: Request) -> str:
    resolved_lms_url = getattr(request.state, "lms_url", None)
    if resolved_lms_url:
        return resolved_lms_url
    logger.error("Missing resolved LMS URL on request state for path %s", request.url.path)
    raise HTTPException(status_code=500, detail="Missing resolved LMS URL.")


def _find_request_in_call(
    args: tuple[object, ...],
    kwargs: dict[str, object],
) -> Request | StarletteRequest | None:
    for value in kwargs.values():
        if isinstance(value, (Request, StarletteRequest)):
            return value
    for value in args:
        if isinstance(value, (Request, StarletteRequest)):
            return value
    return None


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
    async def wrapper(*args, secret: str = Depends(api_key_auth_header), **kwargs):
        request = _find_request_in_call(args, kwargs)
        resolved_lms_url = resolve_lms_url_from_secret(secret)
        if request is not None:
            request.state.lms_url = resolved_lms_url
            logger.debug(
                "Authenticated request for path %s with LMS URL %s",
                request.url.path,
                resolved_lms_url,
            )
        else:
            logger.debug(
                "Authenticated call to %s without a request object available for state propagation",
                func.__name__,
            )

        if inspect.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        return func(*args, **kwargs)

    # Update the function signature with the 'secret' parameter, but otherwise keep the annotations intact
    sig = inspect.signature(func)
    params = list(sig.parameters.values())
    params.append(
        inspect.Parameter('secret', inspect.Parameter.POSITIONAL_OR_KEYWORD, default=Depends(api_key_auth_header)))
    new_sig = sig.replace(parameters=params)
    wrapper.__signature__ = new_sig  # type: ignore # https://github.com/python/mypy/issues/12472

    return wrapper
