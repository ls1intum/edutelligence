"""Lock-free look at the HTTP connection pools of the configured model clients.

Every value here is read without taking the pool lock, so it works while that lock is stuck.
Never call ``repr(pool)``: httpcore's ``__repr__`` takes the lock and would hang.
"""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class PoolView:
    """One model's connection pool and the lock that guards it."""

    model_id: str
    pool: Any
    lock: Any

    def lock_held(self) -> bool:
        return bool(self.lock.locked())

    def open_requests(self) -> int:
        return len(getattr(self.pool, "_requests", ()))

    def connections(self) -> int:
        return len(getattr(self.pool, "_connections", ()))


def _pool_of(client: Any) -> Optional[Any]:
    """httpcore pool behind an OpenAI client, or None if the layout is unknown."""
    http_client = getattr(client, "_client", None)
    transport = getattr(http_client, "_transport", None)
    return getattr(transport, "_pool", None)


def model_pools() -> list[PoolView]:
    """One view per configured model whose client exposes an httpcore pool."""
    from iris.llm.llm_manager import (  # pylint: disable=import-outside-toplevel
        LlmManager,
    )

    views = []
    for entry in LlmManager().entries:
        client = getattr(entry, "_client", None)
        pool = _pool_of(client) if client is not None else None
        thread_lock = getattr(pool, "_optional_thread_lock", None)
        lock = getattr(thread_lock, "_lock", None)
        if lock is not None and callable(getattr(lock, "locked", None)):
            views.append(PoolView(model_id=entry.id, pool=pool, lock=lock))
    return views
