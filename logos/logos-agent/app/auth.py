"""Keycloak bearer-token verification.

The rest of the stack validates browser tokens in the Spring webservice and
forwards internally with a shared secret. This service is reached directly from
the UI through Traefik, so it verifies the token itself: fetch the realm's
JWKS, cache it, check signature, issuer, audience, and expiry, then require the
configured realm role.

Driving an agent means opening pull requests and touching the dev environment,
so an authenticated-but-unprivileged token is not enough — the role check is
the authorisation boundary, and it is not optional outside dev mode.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from jwt import PyJWKClient

from .config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Principal:
    subject: str
    username: str
    roles: frozenset[str]

    def has_role(self, role: str) -> bool:
        return role in self.roles


_jwk_client: PyJWKClient | None = None
_jwk_client_created_at: float = 0.0
# Keycloak rotates signing keys; refetch the key set periodically so a rotation
# does not take the service down until a restart.
_JWKS_TTL_S = 3600.0


def _client() -> PyJWKClient:
    global _jwk_client, _jwk_client_created_at
    now = time.monotonic()
    if _jwk_client is None or now - _jwk_client_created_at > _JWKS_TTL_S:
        if not settings.keycloak_jwks_uri:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="KEYCLOAK_JWKS_URI is not configured",
            )
        _jwk_client = PyJWKClient(settings.keycloak_jwks_uri, cache_keys=True)
        _jwk_client_created_at = now
    return _jwk_client


def _roles_from_claims(claims: dict[str, Any]) -> frozenset[str]:
    """Collect realm and client roles into one set.

    Keycloak splits them: realm roles live under ``realm_access.roles`` and
    per-client roles under ``resource_access.<client>.roles``. The deployment
    may grant the admin role either way, so both are read.
    """
    roles: set[str] = set()
    realm_access = claims.get("realm_access") or {}
    roles.update(realm_access.get("roles") or [])
    for client in (claims.get("resource_access") or {}).values():
        if isinstance(client, dict):
            roles.update(client.get("roles") or [])
    return frozenset(roles)


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return header[7:].strip()


async def current_principal(request: Request) -> Principal:
    if settings.auth_disabled:
        if not settings.dev_mode:
            # Refusing here rather than at startup keeps the failure visible in
            # the response instead of hidden in a crash loop.
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="LOGOS_AGENT_AUTH_DISABLED requires LOGOS_AGENT_DEV_MODE",
            )
        return Principal(subject="dev", username="dev", roles=frozenset({settings.required_role}))

    token = _bearer(request)
    try:
        signing_key = _client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "RS384", "RS512", "ES256", "ES384"],
            audience=settings.keycloak_audience or None,
            issuer=settings.keycloak_issuer_uri or None,
            options={
                "verify_aud": bool(settings.keycloak_audience),
                "verify_iss": bool(settings.keycloak_issuer_uri),
            },
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}")
    except httpx.HTTPError as exc:
        logger.warning("JWKS fetch failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Identity provider unreachable")

    return Principal(
        subject=str(claims.get("sub", "")),
        username=str(claims.get("preferred_username") or claims.get("email") or claims.get("sub", "")),
        roles=_roles_from_claims(claims),
    )


async def require_agent_operator(
    principal: Principal = Depends(current_principal),
) -> Principal:
    if not principal.has_role(settings.required_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{settings.required_role}' is required to drive agents",
        )
    return principal
