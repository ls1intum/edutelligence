"""Ending a frozen session's model requests on the orchestrator.

A paused session is frozen and cut off from the model gateway, but the
requests it had in flight keep generating: the gateway's connection to the
container sees no close, so neither it nor the orchestrator learns that
nobody will read the answer. The slots stay taken — from users, which is the
reason the session was paused — until each generation runs to its end.

The gateway marks every request with the container's address as a client
tag, and the orchestrator ends all requests carrying a tag on request. Each
then goes the way of a client that left: its upstream generation is aborted
and its slot released.
"""

from __future__ import annotations

import logging

import httpx

from .config import settings

logger = logging.getLogger(__name__)

# Must match the tag the model gateway sets (agent-gateway/nginx.conf).
_TAG_PREFIX = "agent:"


def client_tag(address: str) -> str:
    """The tag the model gateway gives requests from ``address``."""
    return f"{_TAG_PREFIX}{address}"


async def cancel_client_requests(address: str, timeout_s: float = 5.0) -> int | None:
    """End the in-flight model requests sent from ``address``.

    Returns how many the orchestrator ended, or ``None`` when it could not
    be asked. Best effort: a pause must not fail over it — the requests then
    end on their own, only later.
    """
    if not settings.internal_secret:
        return None
    url = f"{settings.orchestrator_url.rstrip('/')}/internal/client_tags/cancel"
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(
                url,
                json={"tag": client_tag(address)},
                headers={"Authorization": f"Bearer {settings.internal_secret}"},
            )
        if response.status_code != 200:
            logger.warning("cancelling requests from %s returned %s", address, response.status_code)
            return None
        return int(response.json().get("cancelled") or 0)
    except Exception as exc:  # network, JSON, anything
        logger.warning("could not cancel requests from %s: %s", address, type(exc).__name__)
        return None
