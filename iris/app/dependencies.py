from fastapi import Depends
from fastapi.requests import Request

from app.common.custom_exceptions import (
    RequiresAuthenticationException,
    PermissionDeniedException,
)
from app.config import APIKeyConfig, settings


def _get_api_key(request: Request) -> str:
    authorization_header = request.headers.get("Authorization")

    if not authorization_header:
        raise RequiresAuthenticationException

    return authorization_header


class TokenValidator:
    async def __call__(self, api_key: str = Depends(_get_api_key)) -> APIKeyConfig:
        for key in settings.api_keys:
            if key.token == api_key:
                return key
        raise PermissionDeniedException
