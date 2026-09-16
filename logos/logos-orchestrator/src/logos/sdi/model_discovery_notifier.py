"""Notify the webservice when discovery inserts model rows."""

import logging
import os
from typing import List

import httpx

logger = logging.getLogger(__name__)


async def notify_models_discovered(model_ids: List[int]) -> None:
    url = os.getenv("LOGOS_WEBSERVICE_URL", "").rstrip("/")
    secret = os.getenv("LOGOS_INTERNAL_SECRET", "")
    if not model_ids or not url or not secret:
        return
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
        logger.warning("Model discovery notification failed", exc_info=True)
