"""A nudge from whoever writes an event to whoever is watching for one.

The event stream used to re-read the database every two seconds whether
anything had happened or not, which put a two-second floor under how live
"live" could be. Watching an agent work is the one thing in this service
that a person does in real time, so the write side says when there is
something to fetch and the read side stops guessing.

In-process and deliberately small: one runner writes the events of the
sessions it runs, and a waiter that misses a nudge still has its timeout.
Nothing here is a queue — the database is the log, this is only the doorbell.
"""

from __future__ import annotations

import asyncio

_bells: dict[int, asyncio.Event] = {}


def _bell(session_id: int) -> asyncio.Event:
    bell = _bells.get(session_id)
    if bell is None:
        bell = _bells[session_id] = asyncio.Event()
    return bell


def ring(session_id: int) -> None:
    """Say that this session has something new to read."""
    _bell(session_id).set()


async def wait(session_id: int, timeout: float) -> None:
    """Wait for the next nudge, or for the timeout — whichever comes first.

    The timeout is what keeps a missed nudge from stalling a watcher: at
    worst the stream falls back to the polling it used to do.
    """
    bell = _bell(session_id)
    try:
        await asyncio.wait_for(bell.wait(), timeout=timeout)
    except (TimeoutError, asyncio.TimeoutError):
        return
    finally:
        bell.clear()


def forget(session_id: int) -> None:
    """Drop a finished session's bell."""
    _bells.pop(session_id, None)


__all__ = ["forget", "ring", "wait"]
