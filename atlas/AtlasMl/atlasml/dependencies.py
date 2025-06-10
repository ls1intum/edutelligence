from fastapi import Depends
from fastapi.requests import Request

from atlasml.common.exceptions import (
    PermissionDeniedException,
    RequiresAuthenticationException,
)
from atlasml.config import APIKeyConfig, settings

import logging

logger = logging.getLogger(__name__)


def _get_api_key(request: Request) -> str:
    authorization_header = request.headers.get("Authorization")
    logger.debug(f"Received Authorization header: {authorization_header}")

    if not authorization_header:
        logger.warning("No Authorization header provided")
        raise RequiresAuthenticationException

    return authorization_header


class TokenValidator:
    async def __call__(self, api_key: str = Depends(_get_api_key)) -> APIKeyConfig:
        logger.info(f"Validating API key: {api_key}")
        logger.info(f"Available API keys in settings: {[key for key in settings.get_api_keys()]}")
        
        for key in settings.get_api_keys():
            if key.token == api_key:
                logger.info(f"Found matching API key: {key}")
                return key
                
        logger.warning(f"No matching API key found for: {api_key}")
        raise PermissionDeniedException
