"""A nudge from whoever writes an event to whoever is watching for one.

The event stream used to re-read the database every two seconds whether
anything had happened or not, which put a two-second floor under how live
"live" could be. Watching an agent work is the one thing in this service
that a person does in real time, so the write side says when there is
something to fetch and the read side stops guessing.

Bells exist only while somebody is listening. A runner that ran for weeks
would otherwise keep one per session it had ever written an event for — the
write side has no idea whether anybody is watching, and most of the time
nobody is. So a watcher registers itself for as long as it watches, and
``ring`` is a no-op for a session nobody is following.

In-process and deliberately small: one runner writes the events of the
sessions it runs, and a waiter that misses a nudge still has its timeout.
Nothing here is a queue — the database is the log, this is only the doorbell.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import AsyncIterator

_bells: dict[int, asyncio.Event] = {}
_watchers: dict[int, int] = {}


@contextlib.asynccontextmanager
async def watching(session_id: int) -> AsyncIterator[None]:
    """Follow a session for as long as this block runs.

    Counted rather than flagged, because two people may watch the same
    session: the bell goes when the last of them leaves, whether the stream
    ended on its own or the browser walked away mid-connection.
    """
    _watchers[session_id] = _watchers.get(session_id, 0) + 1
    _bells.setdefault(session_id, asyncio.Event())
    try:
        yield
    finally:
        remaining = _watchers.get(session_id, 1) - 1
        if remaining > 0:
            _watchers[session_id] = remaining
        else:
            _watchers.pop(session_id, None)
            _bells.pop(session_id, None)


def ring(session_id: int) -> None:
    """Say that this session has something new to read.

    Nothing to do when nobody is watching, which is the ordinary case: the
    events are in the database either way, and a watcher that arrives later
    reads them from there.
    """
    bell = _bells.get(session_id)
    if bell is not None:
        bell.set()


async def wait(session_id: int, timeout: float) -> None:
    """Wait for the next nudge, or for the timeout — whichever comes first.

    The timeout is what keeps a missed nudge from stalling a watcher: at
    worst the stream falls back to the polling it used to do. A waiter with
    no bell — nobody registered, or the registration is gone — waits out the
    timeout for the same reason.
    """
    bell = _bells.get(session_id)
    if bell is None:
        await asyncio.sleep(timeout)
        return
    try:
        await asyncio.wait_for(bell.wait(), timeout=timeout)
    except (TimeoutError, asyncio.TimeoutError):
        return
    finally:
        bell.clear()


def watched() -> int:
    """How many sessions are being followed right now."""
    return len(_bells)


__all__ = ["ring", "wait", "watched", "watching"]
