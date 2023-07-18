from fastapi import Depends
from starlette.requests import Request as StarletteRequest
from app.config import settings, APIKeyConfig

from app.core.custom_exceptions import (
    PermissionDeniedException,
    RequiresAuthenticationException,
    InvalidModelException,
)


def _get_api_key(request: StarletteRequest) -> str:
    authorization_header = request.headers.get("Authorization")

    if not authorization_header:
        raise RequiresAuthenticationException

    return authorization_header


class TokenValidator:
    async def __call__(
        self, api_key: str = Depends(_get_api_key)
    ) -> APIKeyConfig:
        for key in settings.pyris.api_keys:
            if key.token == api_key:
                return key
        raise PermissionDeniedException


class TokenPermissionsValidator:
    async def __call__(
        self, request: StarletteRequest, api_key: str = Depends(_get_api_key)
    ):
        for key in settings.pyris.api_keys:
            if key.token == api_key:
                body = await request.json()
                if body.get("preferredModel") in key.llm_access:
                    return
                else:
                    raise InvalidModelException(
                        str(body.get("preferredModel"))
                    )
        raise PermissionDeniedException
