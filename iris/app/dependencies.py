from fastapi import Depends
from starlette.requests import Request as StarletteRequest
from app.config import settings

from app.core.custom_exceptions import (
    PermissionDeniedException,
    RequiresAuthenticationException,
)


def _get_api_key(request: StarletteRequest) -> str:
    authorization_header = request.headers.get("Authorization")

    if not authorization_header:
        raise RequiresAuthenticationException

    return authorization_header


class PermissionsValidator:
    def __call__(self, api_key: str = Depends(_get_api_key)):
        if api_key != settings.pyris.api_key:
            raise PermissionDeniedException
