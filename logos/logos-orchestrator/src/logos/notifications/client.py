"""Client for emitting notifications to the application server.

The orchestrator does not store notifications — the application server does
and owns the schema. This is a thin, best-effort client: it POSTs an event to
the application server's secret-gated internal endpoint (the same shared
secret and the same ``LOGOS_WEBSERVICE_URL`` the model discovery notifier
uses) and never raises, so a notification can never take down the caller.
"""

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


async def emit_notification(
    notification_type: str,
    title: str,
    body: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    targets: Optional[List[Dict[str, Any]]] = None,
    actor_user_id: Optional[int] = None,
) -> bool:
    """POST a notification to the application server's internal endpoint.

    Args:
        notification_type: a ``NotificationType`` value, e.g. ``budget_hit``.
        title: short human summary shown in the inbox (required server-side).
        body: optional longer text.
        payload: optional event-specific structured data, stored as JSONB.
        targets: fan-out targets, each ``{"kind": "user"|"team"|"role", ...}``;
            ``id`` for user/team, ``role`` for role.
        actor_user_id: optional user that triggered the event.

    Returns:
        True when the notification was accepted by the application server.
        False when it was not delivered — either because no application
        server is configured (nothing to deliver to) or because the call
        failed. The return value is informational; callers should treat
        emission as best-effort and not act on a False beyond logging.
    """
    url = os.getenv("LOGOS_WEBSERVICE_URL", "").rstrip("/")
    secret = os.getenv("LOGOS_INTERNAL_SECRET", "")
    if not url or not secret:
        logger.debug("Notification skipped: LOGOS_WEBSERVICE_URL / LOGOS_INTERNAL_SECRET not configured")
        return False

    data = {
        "type": notification_type,
        "title": title,
        "body": body,
        "payload": payload,
        "targets": targets or [],
        "actor_user_id": actor_user_id,
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{url}/internal/notifications",
                json=data,
                headers={"Authorization": "Bearer " + secret},
                timeout=10,
            )
            response.raise_for_status()
    except Exception:  # noqa: BLE001 - emission must never raise into the caller
        logger.warning("Notification emission failed", exc_info=True)
        return False
    return True
