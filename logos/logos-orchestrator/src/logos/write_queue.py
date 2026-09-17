"""Write-behind queue for per-request DB bookkeeping (#980 O13).

The post-response DB writes (usage payload, log-entry metrics, monitoring
flush) are bookkeeping the client never waits for, yet they are synchronous
psycopg2 calls executed on the orchestrator's single event loop. Each one both
delays the client's response *and* blocks the loop — which in turn slows the
WebSocket round-trip that carries the real inference. This queue moves that
work off the request's critical path: the request enqueues a closure and
returns immediately; a dedicated worker thread drains the queue in FIFO order
and runs the (blocking) DB calls there, off the loop.

Relative ordering is preserved (FIFO); different requests interleave freely
because they touch different log rows. The pool behind ``DBManager`` is a
thread-safe SQLAlchemy QueuePool, so the worker thread checks out its own
connection.

Tests install a ``sync``-mode queue (see ``conftest.py``) so enqueued writes
run inline and existing assertions on DB side effects keep holding.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable, Tuple

logger = logging.getLogger(__name__)

_SENTINEL = object()

# A queue this deep holds ~tens of seconds of writes even if the DB stalls;
# beyond it we drop (and log loudly) rather than grow memory without bound.
_DEFAULT_MAXSIZE = 16384


class WriteQueue:
    """A FIFO write-behind queue drained by a single background thread."""

    def __init__(self, maxsize: int = _DEFAULT_MAXSIZE, sync: bool = False, name: str = "logos-write-queue"):
        self._q: "queue.Queue[Tuple]" = queue.Queue(maxsize=maxsize)
        self._sync = sync
        self._name = name
        self._thread: "threading.Thread | None" = None
        self.flushed = 0
        self.dropped = 0
        self.errors = 0

    @property
    def sync(self) -> bool:
        """True when enqueued writes run inline (test mode)."""
        return self._sync

    def _run(self) -> None:
        while True:
            item = self._q.get()
            try:
                if item is _SENTINEL:
                    return
                fn, args, kwargs = item
                fn(*args, **kwargs)
                self.flushed += 1
            except Exception:  # noqa: BLE001 — one bad write must not kill the drain thread
                self.errors += 1
                logger.exception("write-behind task failed (fn=%s)", getattr(fn, "__name__", fn))
            finally:
                self._q.task_done()

    def _ensure_thread(self) -> None:
        if self._sync or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name=self._name, daemon=True)
        self._thread.start()

    def enqueue(self, fn: Callable, *args: Any, **kwargs: Any) -> bool:
        """Queue ``fn(*args, **kwargs)`` to run later — or inline in sync mode.

        Returns True when the write was accepted, False when it was dropped
        because the bounded queue was full (only possible in async mode).
        """
        if self._sync:
            fn(*args, **kwargs)
            return True
        self._ensure_thread()
        try:
            self._q.put_nowait((fn, args, kwargs))
            return True
        except queue.Full:
            self.dropped += 1
            logger.warning("write-behind queue full; dropping %s", getattr(fn, "__name__", fn))
            return False

    def pending(self) -> int:
        """Number of writes not yet flushed (0 in sync mode)."""
        return 0 if self._sync else self._q.qsize()

    def shutdown(self, timeout: float = 5.0) -> None:
        """Drain pending writes (bounded by ``timeout``) and stop the thread."""
        if self._sync or self._thread is None:
            return
        self._q.put(_SENTINEL)
        self._thread.join(timeout)
        self._thread = None


_default: "WriteQueue | None" = None
_lock = threading.Lock()


def get_write_queue() -> WriteQueue:
    """The process-wide queue, created lazily on first use."""
    global _default
    if _default is None:
        with _lock:
            if _default is None:
                _default = WriteQueue()
    return _default


def set_write_queue(q: WriteQueue) -> None:
    """Replace the singleton (tests install a sync-mode queue per test)."""
    global _default
    with _lock:
        _default = q
