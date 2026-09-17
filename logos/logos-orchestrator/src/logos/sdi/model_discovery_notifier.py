"""Notify the webservice when discovery links new models.

The discovery syncs queue every newly linked model in
``model_discovery_notifications`` (see ``DBManager._queue_discovery_notifications``),
and :func:`deliver_discovery_notifications` ships the whole queue on each
sync pass, clearing it only after the webservice acknowledged. A webservice
outage therefore delays the price/capability refresh to the next pass
instead of losing it until the unrelated daily full refresh; the endpoint
is idempotent, so re-announcing a model is harmless.
"""

import logging
import os
from typing import List

import httpx

from logos.dbutils.dbmanager import DBManager

logger = logging.getLogger(__name__)


async def notify_models_discovered(model_ids: List[int]) -> bool:
    """POST the model IDs to the webservice's discovery endpoint.

    Returns True when the notification was delivered — or when there is no
    webservice configured to deliver to, which must drain the queue instead
    of accumulating it forever. Returns False when the webservice could not
    be reached or rejected the request, so the caller keeps the IDs queued.
    """
    url = os.getenv("LOGOS_WEBSERVICE_URL", "").rstrip("/")
    secret = os.getenv("LOGOS_INTERNAL_SECRET", "")
    if not model_ids:
        return True
    if not url or not secret:
        logger.debug("Model discovery notification skipped: no LOGOS_WEBSERVICE_URL / LOGOS_INTERNAL_SECRET configured")
        return True
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{url}/internal/models_discovered",
                json={"model_ids": model_ids},
                headers={"Authorization": "Bearer " + secret},
                timeout=10,
            )
            response.raise_for_status()
    except Exception:  # noqa: BLE001
        logger.warning("Model discovery notification failed; IDs stay queued for the next pass", exc_info=True)
        return False
    return True


async def deliver_discovery_notifications(db: DBManager) -> None:
    """Deliver every queued discovery ID to the webservice.

    Reads the pending queue, announces it, and clears the acknowledged IDs.
    On failure the queue is left untouched and is retried in full on the
    next sync pass.
    """
    pending = db.get_pending_discovery_model_ids()
    if not pending:
        return
    delivered = await notify_models_discovered(pending)
    if delivered:
        db.mark_discovery_notified(pending)
