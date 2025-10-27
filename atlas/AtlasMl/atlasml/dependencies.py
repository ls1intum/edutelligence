from fastapi import Depends
from fastapi.requests import Request
from typing import List

from atlasml.common.exceptions import (
    PermissionDeniedException,
    RequiresAuthenticationException,
)
from atlasml.config import APIKeyConfig, Settings, get_settings

import logging

logger = logging.getLogger(__name__)


def _get_api_key(request: Request) -> str:
    authorization_header = request.headers.get("Authorization")

    if not authorization_header:
        logger.warning("No Authorization header provided")
        raise RequiresAuthenticationException

    return authorization_header


def get_api_keys() -> List[APIKeyConfig]:
    """Dependency to get API keys from settings."""
    return get_settings().api_keys


class TokenValidator:
    async def __call__(
        self,
        api_key: str = Depends(_get_api_key),
        api_keys: List[APIKeyConfig] = Depends(get_api_keys),
    ) -> APIKeyConfig:
        for key in api_keys:
            logger.debug(f"Checking API key: {key}")
            if key.token == api_key:
                return key

        raise PermissionDeniedException


# For backward compatibility, create a dependency function
def validate_token(
    api_key: str = Depends(_get_api_key),
    api_keys: List[APIKeyConfig] = Depends(get_api_keys),
) -> APIKeyConfig:
    """Dependency function to validate API tokens."""
    for key in api_keys:
        logger.debug(f"Checking API key: {key}")
        if key.token == api_key:
            return key
    raise PermissionDeniedException
