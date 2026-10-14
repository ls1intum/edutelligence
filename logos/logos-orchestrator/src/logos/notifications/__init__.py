"""Notification emission for the orchestrator.

The orchestrator does not own the notification store — the application server
does. This module is the thin client that ships an event to the application
server's internal emission endpoint, the same outbox pattern the model
discovery notifier uses for price/capability refreshes.
"""

from .client import emit_notification

__all__ = [
    "emit_notification",
]
