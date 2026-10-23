"""Operator alerts via Pushover.

Credentials come from the environment (``PYRIS_PUSHOVER_APP_TOKEN``, ``PYRIS_PUSHOVER_USER_KEY``);
without them alerts are only logged. Sent with ``requests`` and a short timeout, never through the
model clients, whose connection pools may be the broken part.
"""

import os

import requests

from iris.common.logging_config import get_logger

logger = get_logger(__name__)

PUSHOVER_URL = "https://api.pushover.net/1/messages.json"
ALERT_TIMEOUT_SECONDS = 5

# Pushover priorities: -1 arrives quietly, 1 bypasses quiet hours.
QUIET = -1
URGENT = 1


def send_alert(title: str, message: str, priority: int) -> bool:
    name = os.environ.get("PYRIS_ALERT_NAME") or "pyris"
    full_title = f"{name}: {title}"
    logger.warning(
        "Operator alert (priority %d): %s | %s", priority, full_title, message
    )
    token = os.environ.get("PYRIS_PUSHOVER_APP_TOKEN")
    user = os.environ.get("PYRIS_PUSHOVER_USER_KEY")
    if not token or not user:
        return False
    try:
        response = requests.post(
            PUSHOVER_URL,
            data={
                "token": token,
                "user": user,
                "title": full_title[:250],
                "message": message[:1024],
                "priority": priority,
            },
            timeout=ALERT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logger.error("Could not send the operator alert: %s", e)
        return False
