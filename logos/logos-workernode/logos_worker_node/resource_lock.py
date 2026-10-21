"""An asyncio lock whose holders may name the lanes and GPUs they touch.

``async with lock`` takes the whole lock, like ``asyncio.Lock``. ``lock.scoped``
takes only the named lanes and GPUs, so operations on other lanes and other
GPUs run at the same time. Two scopes conflict when they share a lane or a GPU;
``None`` stands for every lane or every GPU.
"""

from __future__ import annotations

import asyncio
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Iterable


@dataclass
class Scope:
    lanes: frozenset[str] | None
    gpus: frozenset[int] | None

    def conflicts(self, other: "Scope") -> bool:
        return _overlap(self.lanes, other.lanes) or _overlap(self.gpus, other.gpus)


def _overlap(a: frozenset | None, b: frozenset | None) -> bool:
    if a is None:
        return b is None or bool(b)
    if b is None:
        return bool(a)
    return bool(a & b)


EVERYTHING = Scope(lanes=None, gpus=None)


class Claim:
    """A held scope. ``widen`` adds GPUs to it while it is held."""

    def __init__(self, lock: "ResourceLock", scope: Scope) -> None:
        self._lock = lock
        self.scope = scope

    async def widen(self, gpus: frozenset[int] | None) -> None:
        """Also hold *gpus*, waiting until no other holder uses them.

        Waiters are not consulted: one that conflicts with this claim already
        waits for it, so queueing behind it would deadlock.
        """
        wider = Scope(self.scope.lanes, None if gpus is None or self.scope.gpus is None else self.scope.gpus | gpus)
        while any(holder is not self and holder.scope.conflicts(wider) for holder in self._lock._holders):
            await self._lock._released()
        self.scope = wider


class _Waiter:
    def __init__(self, scope: Scope) -> None:
        self.scope = scope
        self.future: asyncio.Future = asyncio.get_running_loop().create_future()


class ResourceLock:
    def __init__(self) -> None:
        self._holders: list[Claim] = []
        self._waiters: deque[_Waiter] = deque()
        self._release_event = asyncio.Event()
        self._whole: list[Claim] = []

    async def __aenter__(self) -> None:
        self._whole.append(await self._acquire(EVERYTHING, queue=True))

    async def __aexit__(self, *exc_info: object) -> None:
        self._release(self._whole.pop())

    @asynccontextmanager
    async def scoped(
        self,
        lanes: Iterable[str],
        gpus: Iterable[int] | None = (),
        *,
        queue: bool = True,
    ) -> AsyncIterator[Claim]:
        """Hold *lanes* and *gpus*.

        With ``queue=False`` the caller waits only for holders, not for earlier
        waiters: for a step that only frees resources and must not wait behind
        an operation that itself waits for a long one.
        """
        scope = Scope(frozenset(lanes), None if gpus is None else frozenset(gpus))
        claim = await self._acquire(scope, queue=queue)
        try:
            yield claim
        finally:
            self._release(claim)

    async def _acquire(self, scope: Scope, *, queue: bool) -> Claim:
        if not queue:
            while self._conflicts_with_holder(scope):
                await self._released()
            return self._hold(scope)
        if not self._conflicts_with_holder(scope) and not any(w.scope.conflicts(scope) for w in self._waiters):
            return self._hold(scope)
        # Waiters go first in, first out among those they conflict with. A
        # waiter keeps its place until it holds the lock.
        waiter = _Waiter(scope)
        self._waiters.append(waiter)
        try:
            while True:
                await waiter.future
                if not self._conflicts_with_holder(scope):
                    return self._hold(scope)
                waiter.future = asyncio.get_running_loop().create_future()
        finally:
            self._waiters.remove(waiter)
            # Leaving the queue, granted or cancelled, can unblock later waiters.
            self._wake_waiters()

    def _conflicts_with_holder(self, scope: Scope) -> bool:
        return any(holder.scope.conflicts(scope) for holder in self._holders)

    def _hold(self, scope: Scope) -> Claim:
        claim = Claim(self, scope)
        self._holders.append(claim)
        return claim

    def _release(self, claim: Claim) -> None:
        self._holders.remove(claim)
        self._release_event.set()
        self._release_event = asyncio.Event()
        self._wake_waiters()

    def _wake_waiters(self) -> None:
        # Wake, in order, each waiter that conflicts neither with a holder nor
        # with an earlier waiter.
        earlier: list[Scope] = []
        for waiter in self._waiters:
            blocked = self._conflicts_with_holder(waiter.scope) or any(e.conflicts(waiter.scope) for e in earlier)
            if not blocked and not waiter.future.done():
                waiter.future.set_result(None)
            earlier.append(waiter.scope)

    async def _released(self) -> None:
        await self._release_event.wait()
