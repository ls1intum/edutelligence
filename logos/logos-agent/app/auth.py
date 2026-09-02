"""Keycloak bearer-token verification.

The rest of the stack validates browser tokens in the Spring webservice and
forwards internally with a shared secret. This service is reached directly from
the UI through Traefik, so it verifies the token itself: fetch the realm's
JWKS, cache it, check signature, issuer, audience, and expiry, then require the
internal operator role — granted by whichever external Keycloak role the
deployment configured for its administrators, the same mapping the webservice
applies.

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
    """The external role names a token carries for this deployment.

    Same sources as the webservice's claim extraction: realm roles, the roles
    of the configured Logos client, and the (normalized) groups. Keycloak
    splits client roles per client under ``resource_access.<client>.roles``;
    only the configured Logos client is read — a role granted by an unrelated
    client in the same realm must not open the agent endpoints.
    """
    roles: set[str] = set()
    realm_access = claims.get("realm_access") or {}
    roles.update(realm_access.get("roles") or [])
    client_access = (claims.get("resource_access") or {}).get(settings.keycloak_client_id)
    if isinstance(client_access, dict):
        roles.update(client_access.get("roles") or [])
    for group in claims.get("groups") or []:
        if isinstance(group, str):
            # Groups arrive with a leading "/", role names never have one.
            roles.add(group[1:] if group.startswith("/") else group)
    return frozenset(roles)


def _internal_roles(external_roles: frozenset[str]) -> frozenset[str]:
    """Map external Keycloak role names onto the internal role this service
    authorizes on.

    The browser JWT carries the deployment's role name (itg-admin by
    default), not the internal value — comparing it against
    ``settings.required_role`` would 403 every administrator. This is the
    webservice's mapping (KeycloakRoleMapper / logos.auth.roles.logos-admin):
    any configured external name grants the required role, nothing else does.
    """
    if external_roles & frozenset(settings.keycloak_roles_logos_admin):
        return frozenset({settings.required_role})
    return frozenset()


def _audience_ok(claims: dict[str, Any]) -> bool:
    """Whether the token was issued for the configured Logos client.

    Mirrors the webservice's resource-server check (SecurityConfig's
    AudienceValidator): Keycloak carries the authorized party in ``aud`` for
    some flows and in ``azp`` for the standard browser flow, so the client ID
    is accepted in either place. A token that presents neither is not one for
    this client, and no role claim can make it one.
    """
    expected = settings.keycloak_audience
    if not expected:
        return True
    audience = claims.get("aud")
    if isinstance(audience, str):
        audience = [audience]
    in_aud = isinstance(audience, list) and any(entry == expected for entry in audience if isinstance(entry, str))
    return in_aud or claims.get("azp") == expected


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
            issuer=settings.keycloak_issuer_uri or None,
            options={"verify_iss": bool(settings.keycloak_issuer_uri), "verify_aud": False},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}")
    except httpx.HTTPError as exc:
        logger.warning("JWKS fetch failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Identity provider unreachable")

    # The audience is checked by hand, after signature and issuer: the
    # webservice accepts the client ID in `aud` or in `azp`, and PyJWT only
    # knows the former — with its built-in check, the standard browser tokens
    # (azp, no aud) would all 401 here.
    if not _audience_ok(claims):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: required audience '{settings.keycloak_audience}' is missing",
        )

    return Principal(
        subject=str(claims.get("sub", "")),
        username=str(claims.get("preferred_username") or claims.get("email") or claims.get("sub", "")),
        roles=_internal_roles(_roles_from_claims(claims)),
    )


async def require_agent_operator(
    principal: Principal = Depends(current_principal),
) -> Principal:
    if not principal.has_role(settings.required_role):
        # Name the external role(s) that grant it: that is what an operator
        # can actually set in Keycloak.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Role '{settings.required_role}' is required to drive agents "
                f"(grant one of: {', '.join(settings.keycloak_roles_logos_admin)})"
            ),
        )
    return principal
