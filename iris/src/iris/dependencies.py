import hashlib
import hmac
from typing import Annotated

from fastapi import Depends
from fastapi.requests import Request

from iris.common.custom_exceptions import (
    PermissionDeniedException,
    RequiresAuthenticationException,
)
from iris.common.logging_config import get_logger
from iris.config import APIKeyConfig, settings
from iris.domain.pipeline_execution_settings_dto import PipelineExecutionSettingsDTO

logger = get_logger(__name__)


def _get_api_key(request: Request) -> str:
    authorization_header = request.headers.get("Authorization")

    if not authorization_header:
        raise RequiresAuthenticationException

    return authorization_header


def _digest(value: str) -> bytes:
    """A fixed-length digest, so that comparing two values takes the same time whatever they hold."""
    return hashlib.sha256(value.encode("utf-8")).digest()


class TokenValidator:
    """Finds the configured key that a request presents, or rejects the request."""

    async def __call__(
        self, request: Request, api_key: str = Depends(_get_api_key)
    ) -> APIKeyConfig:
        presented = _digest(api_key)
        matched: APIKeyConfig | None = None
        for key in settings.api_keys:
            # every key is compared, so the time does not tell which one matched
            if hmac.compare_digest(_digest(key.token), presented) and matched is None:
                matched = key
        if matched is not None:
            return matched
        logger.warning(
            "Rejected a request with an unknown API key from %s",
            request.client.host if request.client else "an unknown address",
        )
        raise PermissionDeniedException


AuthorizedKey = Annotated[APIKeyConfig, Depends(TokenValidator())]
"""The key a request presented. Declare it as a parameter of every route that takes a base URL."""


def require_base_url(api_key: APIKeyConfig, base_url: str | None) -> None:
    """Reject a request for an Artemis installation that the key it presented is not allowed to act for.

    A key without ``allowed_base_urls`` is not limited and accepts every base URL.

    :param api_key: the key of the request, as the token validator found it
    :param base_url: the base URL the request names, None if it names none
    """
    if not api_key.permits_base_url(base_url):
        logger.warning(
            "Rejected a request for the base URL %r: it is not among the allowed_base_urls of the API key",
            base_url,
        )
        raise PermissionDeniedException


def require_settings_base_url(
    api_key: APIKeyConfig, execution_settings: PipelineExecutionSettingsDTO | None
) -> None:
    """Like require_base_url, for the settings that Artemis sends with a pipeline run.

    :param api_key: the key of the request, as the token validator found it
    :param execution_settings: the settings of the run, None if the request has none
    """
    require_base_url(
        api_key, execution_settings.artemis_base_url if execution_settings else None
    )
