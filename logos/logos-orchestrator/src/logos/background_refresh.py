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
    (it may have read the database before the change). Loads can overlap (a
    forced :meth:`refresh` during a background one): each replays only the
    changes made after it started, and a load that started before the one
    whose value is installed is dropped, so an older read never overwrites a
    newer one.
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
        # Every update gets the next sequence number; a load remembers the
        # number current when it started.
        self._seq = 0
        self._changes: list[tuple[int, Callable[[T], T]]] = []
        self._next_load_id = 0
        self._active_loads: dict[int, int] = {}
        # The load whose value is installed. Load ids grow with start time, so
        # a load that started earlier never replaces one that started later,
        # even when no update happened between their starts.
        self._installed_load = -1

    @property
    def loaded(self) -> bool:
        """Whether a load has succeeded at least once."""
        return self._loaded

    def get(self) -> T:
        """The current value; starts a background refresh when one is due."""
        with self._lock:
            value = self._value
            load = None
            if not self._active_loads and self._clock() >= self._due_at:
                load = self._begin_load()
        if load is not None:
            self._start_background_refresh(*load)
        return value

    def peek(self) -> T:
        """The current value, without starting a refresh."""
        with self._lock:
            return self._value

    def refresh(self) -> bool:
        """Load now on the calling thread. Returns whether a new value was installed."""
        with self._lock:
            load = self._begin_load()
        return self._load_and_install(*load)

    async def refresh_async(self) -> bool:
        """:meth:`refresh` off the event loop."""
        return await asyncio.to_thread(self.refresh)

    def update(self, change: Callable[[T], T]) -> T:
        """Apply a known write to the memory copy at once and return the new value."""
        with self._lock:
            self._value = change(self._value)
            self._seq += 1
            if self._active_loads:
                self._changes.append((self._seq, change))
            return self._value

    def _begin_load(self) -> tuple[int, int]:
        # Caller holds the lock.
        load_id = self._next_load_id
        self._next_load_id += 1
        self._active_loads[load_id] = self._seq
        return load_id, self._seq

    def _start_background_refresh(self, load_id: int, started_at_seq: int) -> None:
        def run() -> None:
            self._load_and_install(load_id, started_at_seq)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        try:
            if loop is not None:
                loop.run_in_executor(None, run)
            else:
                threading.Thread(target=run, name=f"refresh-{self._name}", daemon=True).start()
        except Exception:  # noqa: BLE001 — a refresh that cannot start is retried on a later read
            logger.warning("Could not start a background refresh of %s", self._name, exc_info=True)
            self._finish_load(load_id, started_at_seq, None)

    def _load_and_install(self, load_id: int, started_at_seq: int) -> bool:
        try:
            value = self._loader()
        except Exception:  # noqa: BLE001 — the previous value stays in use
            logger.warning("Could not refresh %s; keeping the previous value", self._name, exc_info=True)
            value = None
        return self._finish_load(load_id, started_at_seq, value)

    def _finish_load(self, load_id: int, started_at_seq: int, value: Optional[T]) -> bool:
        with self._lock:
            self._active_loads.pop(load_id, None)
            now = self._clock()
            installed = False
            if value is None:
                # The changes are already in the value that stays in use.
                self._due_at = now + self._retry_after_s
            elif load_id > self._installed_load:
                for seq, change in self._changes:
                    if seq > started_at_seq:
                        value = change(value)
                self._value = value
                self._installed_load = load_id
                self._loaded = True
                self._due_at = now + self._refresh_after_s
                installed = True
            # Keep only the changes a load still running has to replay.
            oldest = min(self._active_loads.values(), default=None)
            self._changes = [] if oldest is None else [(seq, c) for seq, c in self._changes if seq > oldest]
            return installed
