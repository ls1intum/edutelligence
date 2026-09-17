"""In-memory TTL cache for non-authorization DB reference reads (#980 O12).

The request happy path reads a handful of rows that rarely change. Only the
*team* row (rate-limit defaults) is served from this cache: its contents are
configuration, not authorization. The api-key row (is_active) and the
permission lookups (deployments, resolve_proxy_model) are deliberately read
fresh on every request — caching them would let a revoked key or a removed
permission keep working until the TTL expires, which is an authorization
behavior change the optimization must not make (#980 review). Re-enabling a
full reference cache needs push invalidation from the webservice (the rows
are written there, not in the orchestrator), not a shorter TTL.

* ``LOGOS_REF_CACHE_TTL_S`` (default 1.0) — entry lifetime in seconds.
  0 disables the cache (legacy per-request reads).

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
    so a cached ``None`` (negative result) is distinguishable from a miss.

    The first key element is the *namespace* (``api_key``, ``team``,
    ``deployments``, ``resolve_model``). Capacity is bounded twice:
    overall (``MAX_ENTRIES``) and per namespace
    (``MAX_ENTRIES_PER_NAMESPACE``). Eviction is expired-first, then
    least-recently-built (insertion time is the LRU proxy — with a 1 s TTL
    the difference is immaterial). A flat "clear everything when full" would
    let one tenant's user-controlled model names (the resolve_model
    namespace) evict every other tenant's cached keys on each insert.
    """

    # Hard bound on entry count. The request path caches a handful of keys;
    # the bound exists to keep a pathological key fan-out from growing
    # memory without limit.
    MAX_ENTRIES = 4096
    # A single namespace (e.g. user-supplied model names) must not crowd out
    # the other namespaces.
    MAX_ENTRIES_PER_NAMESPACE = 1024

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
        now = time.monotonic()
        if len(self._entries) >= self.MAX_ENTRIES:
            self._evict_expired(now)
        while len(self._entries) >= self.MAX_ENTRIES:
            self._evict_oldest()
        if self._count_namespace(key[0]) >= self.MAX_ENTRIES_PER_NAMESPACE:
            self._evict_oldest_in(key[0])
        self._entries[key] = (now, value)

    def _evict_expired(self, now: float) -> None:
        for k in [k for k, (built_at, _) in self._entries.items() if now - built_at >= self.ttl_s]:
            del self._entries[k]

    def _evict_oldest(self) -> None:
        oldest = min(self._entries, key=lambda k: self._entries[k][0])
        del self._entries[oldest]

    def _count_namespace(self, namespace: Any) -> int:
        return sum(1 for k in self._entries if k[0] == namespace)

    def _evict_oldest_in(self, namespace: Any) -> None:
        while self._count_namespace(namespace) >= self.MAX_ENTRIES_PER_NAMESPACE:
            oldest = min((k for k in self._entries if k[0] == namespace), key=lambda k: self._entries[k][0])
            del self._entries[oldest]

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
