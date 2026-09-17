"""In-memory TTL cache for the per-request DB reference reads (#980 O12).

The request happy path reads rows that rarely change — the api key row, the
team row (rate-limit defaults), the key's deployments, the resolution of the
requested model name. Every read is a synchronous pool checkout + query on
the event loop (~2 ms per request in total). The cache holds them for a
short TTL and serves repeats from memory:

* ``LOGOS_REF_CACHE_TTL_S`` (default 1.0) — entry lifetime in seconds.
  0 disables the cache (legacy per-request reads).
* Staleness is bounded by the TTL: a revoked key, a changed rate limit, or a
  new model/deployment becomes visible within one TTL. These rows are written
  by the webservice, not the orchestrator, so there is no in-process
  invalidation hook — the TTL is the bound.

The cache is generic (``load(key, loader)``): the DB call stays in the module
that owns it, so test doubles patched onto that module keep working. All
access is synchronous on the single event-loop thread, so no locking is
needed.
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, Optional, Tuple

_MISSING = object()


def _ttl_from_env() -> float:
    try:
        return float(os.getenv("LOGOS_REF_CACHE_TTL_S", "1.0"))
    except (TypeError, ValueError):
        return 1.0


class RefCache:
    """Small TTL cache. ``get`` returns ``_MISSING`` for absent/expired keys,
    so a cached ``None`` (negative result) is distinguishable from a miss."""

    # Hard bound on entry count: beyond this everything is dropped at once.
    # The request path only caches a handful of keys; the bound exists to keep
    # a pathological key fan-out from growing memory without limit.
    MAX_ENTRIES = 4096

    def __init__(self, ttl_s: Optional[float] = None) -> None:
        self.ttl_s = _ttl_from_env() if ttl_s is None else ttl_s
        self._entries: Dict[Tuple[Any, ...], Tuple[float, Any]] = {}

    def get(self, key: Tuple[Any, ...]) -> Any:
        if self.ttl_s <= 0:
            return _MISSING
        entry = self._entries.get(key)
        if entry is None:
            return _MISSING
        built_at, value = entry
        if time.monotonic() - built_at >= self.ttl_s:
            del self._entries[key]
            return _MISSING
        return value

    def set(self, key: Tuple[Any, ...], value: Any) -> None:
        if self.ttl_s <= 0:
            return
        if len(self._entries) >= self.MAX_ENTRIES:
            self._entries.clear()
        self._entries[key] = (time.monotonic(), value)

    def load(self, key: Tuple[Any, ...], loader: Callable[[], Any]) -> Any:
        """Cached ``loader()`` — the loader runs only on a miss/expiry."""
        value = self.get(key)
        if value is not _MISSING:
            return value
        value = loader()
        self.set(key, value)
        return value

    def clear(self) -> None:
        self._entries.clear()


_cache: Optional[RefCache] = None


def get_ref_cache() -> RefCache:
    global _cache
    if _cache is None:
        _cache = RefCache()
    return _cache
