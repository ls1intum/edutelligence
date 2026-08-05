"""Cancellation signalling for the lecture ingestion pipelines."""

import threading
from typing import Callable, Optional

from iris.common.custom_exceptions import IngestionCancelledException
from iris.common.logging_config import get_logger

logger = get_logger(__name__)


class CancellationSignal(threading.Event):
    """An ``Event`` that also runs registered callbacks when it is set.

    Some work cannot be woken by checking a flag — a thread blocked in
    ``communicate()`` or ``wait()`` only notices once it returns. Rather than
    polling those places, they register what should happen on cancellation and
    are interrupted directly. Callbacks run on the thread calling ``set()``, so
    they must be cheap and non-blocking (``Popen.kill``, ``Event.set``).
    """

    def __init__(self) -> None:
        super().__init__()
        self._callbacks: list[Callable[[], None]] = []
        self._callback_lock = threading.Lock()

    def on_cancel(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register ``callback``, returning a function that unregisters it.

        Runs immediately if cancellation already happened, so nothing can be
        missed by registering a moment too late.
        """
        with self._callback_lock:
            if super().is_set():
                already_cancelled = True
            else:
                already_cancelled = False
                self._callbacks.append(callback)

        if already_cancelled:
            _run(callback)
            return noop_unregister

        def unregister() -> None:
            with self._callback_lock:
                if callback in self._callbacks:
                    self._callbacks.remove(callback)

        return unregister

    def set(self) -> None:
        super().set()
        with self._callback_lock:
            callbacks, self._callbacks = self._callbacks, []
        for callback in callbacks:
            _run(callback)


def noop_unregister() -> None:
    """Unregister handle for a callback that was never registered."""


def _run(callback: Callable[[], None]) -> None:
    """Run a cancellation callback without letting it break the caller."""
    try:
        callback()
    except Exception as e:  # pragma: no cover - best effort interruption
        logger.warning("Cancellation callback failed: %s", e)


def raise_if_cancelled(
    cancel_event: Optional[threading.Event],
    lecture_unit_id: Optional[int] = None,
    stage: Optional[str] = None,
) -> None:
    """Stop the current ingestion job if a newer request superseded it.

    Belongs at the boundary of expensive work — between slides, between
    embeddings — and immediately before every Weaviate mutation, but never
    inside a delete/insert pair that would leave the unit half-written.

    Raises:
        IngestionCancelledException: If ``cancel_event`` is set.
    """
    if cancel_event is None or not cancel_event.is_set():
        return

    logger.info("[Lecture %s] Cancellation detected at %s", lecture_unit_id, stage)
    raise IngestionCancelledException(
        lecture_unit_id,
        f"Cancelled during {stage}" if stage else "Superseded by a newer request",
    )
