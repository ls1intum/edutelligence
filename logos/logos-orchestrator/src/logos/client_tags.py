"""Cancel in-flight requests by the client that sent them.

A proxy in front of the orchestrator can mark each request with an opaque
client tag (``X-Logos-Client-Tag``). An internal caller can then end every
request carrying that tag at once — the agent runner does this when it
pauses a session, because a frozen container neither reads its answer nor
closes its socket, and nothing upstream would otherwise notice that the
reader is gone.

Ending a request is reported to the application as an ordinary client
disconnect: ``receive()`` answers ``http.disconnect``. That reuses every
path that already handles a client leaving — the pipeline's disconnect
watcher cancels the work and closes the upstream connection so vLLM aborts
the sequence, a streaming body is torn down by Starlette's disconnect
listener, the scheduler slot is released and the log entry says why.

The tag is not a credential. A client that forges another's tag can only get
its own requests cancelled when the other is paused; cancelling is gated on
the internal secret.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

CLIENT_TAG_HEADER = b"x-logos-client-tag"

_DISCONNECT = {"type": "http.disconnect"}

_events: dict[str, set[asyncio.Event]] = defaultdict(set)


def cancel(tag: str) -> int:
    """End every in-flight request carrying ``tag``. Returns how many."""
    events = _events.get(tag) or set()
    for event in events:
        event.set()
    return len(events)


def in_flight(tag: str) -> int:
    return len(_events.get(tag) or ())


def _tag_of(scope) -> str | None:
    for name, value in scope.get("headers") or ():
        if name.lower() == CLIENT_TAG_HEADER:
            tag = value.decode("latin-1").strip()
            return tag or None
    return None


class ClientTagCancellationMiddleware:
    """Register tagged HTTP requests so :func:`cancel` can end them."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        tag = _tag_of(scope) if scope["type"] == "http" else None
        if tag is None:
            await self.app(scope, receive, send)
            return

        cancelled = asyncio.Event()
        _events[tag].add(cancelled)

        async def guarded_receive():
            # Checked before any await: `Request.is_disconnected()` calls this
            # inside an already-cancelled scope, so the answer must be ready
            # without yielding.
            if cancelled.is_set():
                return _DISCONNECT
            message = asyncio.ensure_future(receive())
            stop = asyncio.ensure_future(cancelled.wait())
            try:
                done, _ = await asyncio.wait({message, stop}, return_when=asyncio.FIRST_COMPLETED)
            finally:
                stop.cancel()
                if not message.done():
                    message.cancel()
            if message in done:
                return message.result()
            return _DISCONNECT

        try:
            await self.app(scope, guarded_receive, send)
        finally:
            events = _events.get(tag)
            if events is not None:
                events.discard(cancelled)
                if not events:
                    _events.pop(tag, None)
