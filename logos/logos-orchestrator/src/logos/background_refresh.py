"""A value kept in memory and refreshed in the background.

For state that this process reads often and that is written rarely, by
another service, into the database: reads are served from memory and never
wait for the database, and a refresh runs in the background once the value
is older than ``refresh_after_s``. A write the owner learns about (pushed by
the service that made it) is applied to the memory copy at once with
:meth:`BackgroundRefreshedValue.update`, so it takes effect without waiting
for the next refresh; the refresh only catches what a lost push missed.

The webservice has the same pattern in Java (``BackgroundRefreshedCache``,
used by its budget snapshots).

Thread-safe: reads happen on the event loop, the background load runs on a
worker thread.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Callable, Generic, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class BackgroundRefreshedValue(Generic[T]):
    """A value served from memory and reloaded in the background.

    ``loader`` returns the fresh value, or ``None`` when it could not read
    it; a ``None`` or an exception keeps the previous value, so a database
    blip never replaces known state with nothing. A failed load is retried
    after ``retry_after_s`` instead of the full ``refresh_after_s``.

    A change applied with :meth:`update` while a load is running is replayed
    onto the loaded value when it is installed, so the load cannot discard it
    (it may have read the database before the change).
    """

    def __init__(
        self,
        loader: Callable[[], Optional[T]],
        *,
        initial: T,
        refresh_after_s: float,
        retry_after_s: Optional[float] = None,
        name: str = "value",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._loader = loader
        self._value = initial
        self._refresh_after_s = refresh_after_s
        self._retry_after_s = refresh_after_s if retry_after_s is None else retry_after_s
        self._name = name
        self._clock = clock
        self._lock = threading.Lock()
        self._loaded = False
        self._due_at = 0.0
        self._refreshing = False
        self._pending: list[Callable[[T], T]] = []

    @property
    def loaded(self) -> bool:
        """Whether a load has succeeded at least once."""
        return self._loaded

    def get(self) -> T:
        """The current value; starts a background refresh when one is due."""
        with self._lock:
            value = self._value
            due = not self._refreshing and self._clock() >= self._due_at
            if due:
                self._refreshing = True
        if due:
            self._start_background_refresh()
        return value

    def peek(self) -> T:
        """The current value, without starting a refresh."""
        with self._lock:
            return self._value

    def refresh(self) -> bool:
        """Load now on the calling thread. Returns whether a new value was installed."""
        with self._lock:
            self._refreshing = True
        return self._load_and_install()

    async def refresh_async(self) -> bool:
        """:meth:`refresh` off the event loop."""
        return await asyncio.to_thread(self.refresh)

    def update(self, change: Callable[[T], T]) -> T:
        """Apply a known write to the memory copy at once and return the new value."""
        with self._lock:
            self._value = change(self._value)
            if self._refreshing:
                self._pending.append(change)
            return self._value

    def _start_background_refresh(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        try:
            if loop is not None:
                loop.run_in_executor(None, self._load_and_install)
            else:
                threading.Thread(target=self._load_and_install, name=f"refresh-{self._name}", daemon=True).start()
        except Exception:  # noqa: BLE001 — a refresh that cannot start is retried on a later read
            logger.warning("Could not start a background refresh of %s", self._name, exc_info=True)
            with self._lock:
                self._refreshing = False
                self._due_at = self._clock() + self._retry_after_s

    def _load_and_install(self) -> bool:
        try:
            value = self._loader()
        except Exception:  # noqa: BLE001 — the previous value stays in use
            logger.warning("Could not refresh %s; keeping the previous value", self._name, exc_info=True)
            value = None
        with self._lock:
            self._refreshing = False
            pending, self._pending = self._pending, []
            now = self._clock()
            if value is None:
                # The changes are already in the value that stays in use.
                self._due_at = now + self._retry_after_s
                return False
            for change in pending:
                value = change(value)
            self._value = value
            self._loaded = True
            self._due_at = now + self._refresh_after_s
            return True
