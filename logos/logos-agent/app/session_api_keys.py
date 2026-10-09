"""Mint and revoke short-lived Logos API keys for agent sessions.

The webservice owns the rows. The runner calls it with the shared internal
secret, never logs key values, and revokes the key when the session ends.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from .config import settings

logger = logging.getLogger(__name__)


class SessionApiKeyError(RuntimeError):
    """Mint or revoke failed; the message is safe to surface (no key values)."""


@dataclass(frozen=True)
class MintedSessionKey:
    id: int
    key_value: str
    expires_at: str
    parent_api_key_id: int


def session_key_ttl_s() -> int:
    """Lifetime for a session key: session budget plus margin, capped.

    When ``session_timeout_s`` is 0 (no wall-clock budget), the cap is used.
    A session that outlives its key is not refreshed in this version — keep
    the cap at or above the longest session you allow, or set a session
    timeout.
    """
    budget = settings.session_timeout_s
    base = budget if budget > 0 else settings.session_api_key_ttl_cap_s
    ttl = base + settings.session_api_key_ttl_margin_s
    return max(1, min(ttl, settings.session_api_key_ttl_cap_s))


async def mint(*, session_id: int, parent_key_value: str) -> MintedSessionKey:
    """Ask the webservice for a session-scoped clone of the standing agent key."""
    if not settings.internal_secret:
        raise SessionApiKeyError("LOGOS_INTERNAL_SECRET is not configured")
    if not parent_key_value:
        raise SessionApiKeyError("LOGOS_AGENT_API_KEY is not configured")
    url = f"{settings.webservice_url.rstrip('/')}/internal/session_api_keys"
    body = {
        "parent_key_value": parent_key_value,
        "ttl_seconds": session_key_ttl_s(),
        "name": f"agent-session-{session_id}",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {settings.internal_secret}"},
                json=body,
            )
    except httpx.HTTPError as exc:
        raise SessionApiKeyError(f"could not reach the webservice to mint a session key: {exc}") from exc
    if response.status_code != 200:
        detail = _safe_error(response)
        raise SessionApiKeyError(f"session key mint failed ({response.status_code}): {detail}")
    payload = response.json() if response.content else {}
    try:
        key_id = int(payload["id"])
        key_value = str(payload["key_value"])
        expires_at = str(payload["expires_at"])
        parent_id = int(payload["parent_api_key_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SessionApiKeyError("session key mint returned an incomplete response") from exc
    if not key_value:
        raise SessionApiKeyError("session key mint returned an empty key")
    logger.info(
        "minted session API key id=%s for session %s (expires_at=%s, parent_id=%s)",
        key_id,
        session_id,
        expires_at,
        parent_id,
    )
    return MintedSessionKey(
        id=key_id,
        key_value=key_value,
        expires_at=expires_at,
        parent_api_key_id=parent_id,
    )


async def revoke(key_id: int) -> None:
    """Deactivate a previously minted session key. Best-effort; logs on failure."""
    if key_id <= 0:
        return
    if not settings.internal_secret:
        logger.warning("cannot revoke session API key id=%s: internal secret missing", key_id)
        return
    url = f"{settings.webservice_url.rstrip('/')}/internal/session_api_keys/{key_id}/revoke"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {settings.internal_secret}"},
            )
    except httpx.HTTPError as exc:
        logger.warning("could not revoke session API key id=%s: %s", key_id, exc)
        return
    if response.status_code not in (200, 404):
        logger.warning(
            "session API key revoke id=%s failed (%s): %s",
            key_id,
            response.status_code,
            _safe_error(response),
        )
        return
    logger.info("revoked session API key id=%s", key_id)


def _safe_error(response: httpx.Response) -> str:
    """Body snippet for logs: never include a key_value field if present."""
    try:
        payload: Any = response.json()
    except ValueError:
        return (response.text or "")[:200]
    if isinstance(payload, dict):
        cleaned = {k: v for k, v in payload.items() if k not in {"key_value", "api_key", "credential"}}
        return str(cleaned.get("error") or cleaned)[:200]
    return str(payload)[:200]


def expires_at_epoch(expires_at: str) -> float | None:
    """Parse an ISO expires_at string to a UNIX epoch, or None."""
    try:
        instant = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return instant.timestamp()
