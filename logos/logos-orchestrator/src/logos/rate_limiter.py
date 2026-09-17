from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional, Tuple

from fastapi import HTTPException


@dataclass
class RateLimitConfig:
    rpm: Optional[int] = None
    tpm: Optional[int] = None
    # Sliding window the rpm/tpm limits are enforced over. This default is
    # the source of truth: the webservice keeps a copy of it in
    # logos/logos-webservice/.../identity/service/MeKeysService.java
    # (RATE_LIMIT_WINDOW_SECONDS) so its usage figures come from the same
    # window. Change both together — the webservice test
    # RateLimitWindowConsistencyTest fails if the two drift.
    window_seconds: int = 60


#: How often a locked call sweeps stale keys out of both stores. Deliberately much
#: longer than any window_seconds used in this module (always 60, see
#: RateLimitConfig) so a sweep is cheap relative to how rarely it needs to run.
_SWEEP_INTERVAL_S = 300

#: A key is swept once its most recent entry is older than this. Larger than every
#: window_seconds in this module so a key already past this age is guaranteed to
#: have nothing left to prune under any of them — this is what lets "stale by this
#: much" stand in for "idle" without tracking last-access time separately.
_STALE_AFTER_S = 120


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._request_windows: dict[str, deque] = {}
        self._token_windows: dict[str, deque] = {}
        self._pending_auth: dict[str, int] = {}
        self._last_sweep = time.monotonic()

    def _prune_requests(self, dq: deque, cutoff: float) -> None:
        while dq and dq[0] < cutoff:
            dq.popleft()

    def _prune_tokens(self, dq: deque, cutoff: float) -> None:
        while dq and dq[0][0] < cutoff:
            dq.popleft()

    def _sweep_locked(self, now: float) -> None:
        """Evict keys pruning alone never reaches. Call with `self._lock` held.

        `_prune_requests`/`_prune_tokens` only touch a key's own deque, and only
        when that same key is looked up again — so a client that stops sending
        requests (the common case for the per-IP buckets in `enforce_ip_rate_limit`
        / `enforce_auth_failure_budget`: /health and /info take no credential, so
        distinct source addresses show up once and often never again) would
        otherwise sit in both dicts for the life of the process. Runs at most
        once per `_SWEEP_INTERVAL_S`, so the O(n) scan below is cheap relative to
        how rarely it happens.
        """
        if now - self._last_sweep < _SWEEP_INTERVAL_S:
            return
        self._last_sweep = now
        cutoff = now - _STALE_AFTER_S
        # Deques are appended in increasing time order, so the last entry is the
        # most recent — if that one is already stale, everything before it is too.
        for key in [k for k, dq in self._request_windows.items() if not dq or dq[-1] < cutoff]:
            del self._request_windows[key]
        for key in [k for k, dq in self._token_windows.items() if not dq or dq[-1][0] < cutoff]:
            del self._token_windows[key]

    def reserve_auth_failure(self, key: str) -> None:
        """Track an authentication lookup that has not produced a result yet."""
        with self._lock:
            self._sweep_locked(time.monotonic())
            self._pending_auth[key] = self._pending_auth.get(key, 0) + 1

    def release_auth_reservation(self, key: str) -> None:
        """Release a pending authentication lookup after successful auth or an error."""
        with self._lock:
            pending = self._pending_auth.get(key, 0)
            if pending <= 1:
                self._pending_auth.pop(key, None)
            else:
                self._pending_auth[key] = pending - 1

    def record_auth_failure(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        """Record a completed authentication failure if its window has capacity."""
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            self._sweep_locked(now)
            dq = self._request_windows.setdefault(key, deque())
            self._prune_requests(dq, cutoff)
            admitted = len(dq) < limit
            if admitted:
                dq.append(now)
            pending = self._pending_auth.get(key, 0)
            if pending <= 1:
                self._pending_auth.pop(key, None)
            else:
                self._pending_auth[key] = pending - 1
            return admitted

    def tracked_key_count(self) -> int:
        """Total keys tracked across both stores. Exposed for tests observing memory bounds."""
        with self._lock:
            return len(self._request_windows) + len(self._token_windows)

    def check_and_record(self, key: str, config: RateLimitConfig) -> Tuple[bool, str]:
        # The TPM check runs before the RPM slot is recorded. A request the
        # TPM limit rejects must not consume an RPM slot: the /me/keys usage
        # window displays admitted requests only, so a TPM reject that still
        # appended its RPM timestamp would leave the displayed RPM below the
        # enforced one — the UI showing headroom while the limiter keeps
        # returning 429.
        now = time.monotonic()
        cutoff = now - config.window_seconds

        with self._lock:
            self._sweep_locked(now)
            if config.tpm is not None:
                tok_dq = self._token_windows.setdefault(key, deque())
                self._prune_tokens(tok_dq, cutoff)

                total = sum(tokens for _, tokens in tok_dq)
                if total >= config.tpm:
                    return (
                        False,
                        f"TPM limit reached ({config.tpm}/{config.window_seconds}s)",
                    )

            if config.rpm is not None:
                req_dq = self._request_windows.setdefault(key, deque())
                self._prune_requests(req_dq, cutoff)

                if len(req_dq) >= config.rpm:
                    return (
                        False,
                        f"RPM limit reached ({config.rpm}/{config.window_seconds}s)",
                    )

                req_dq.append(now)

        return True, ""

    def record_tokens(self, key: str, token_count: int) -> None:
        now = time.monotonic()

        with self._lock:
            self._sweep_locked(now)
            tok_dq = self._token_windows.setdefault(key, deque())
            tok_dq.append((now, token_count))

    def has_budget(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        """Whether `key` has an unspent request slot, without spending one.

        Pairs with `consume` for a check whose cost falls on failure rather
        than on use: a caller that keeps succeeding never approaches the
        limit no matter how many requests it makes, because only `consume`
        (called from the failure path) appends a timestamp.
        """
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            self._sweep_locked(now)
            dq = self._request_windows.setdefault(key, deque())
            self._prune_requests(dq, cutoff)
            return len(dq) < limit

    def consume(self, key: str) -> None:
        """Spend one request slot for `key`, unconditionally."""
        now = time.monotonic()
        with self._lock:
            self._sweep_locked(now)
            dq = self._request_windows.setdefault(key, deque())
            dq.append(now)


_rate_limiter: Optional[InMemoryRateLimiter] = None
_rate_limiter_lock = threading.Lock()


def get_rate_limiter() -> InMemoryRateLimiter:
    global _rate_limiter

    if _rate_limiter is None:
        with _rate_limiter_lock:
            if _rate_limiter is None:
                _rate_limiter = InMemoryRateLimiter()

    return _rate_limiter


# Per-IP RPM for endpoints that are open by design (no credential) — e.g.
# /health, /info — so a caller cannot use them to generate unbounded backend
# load. Generous enough for monitoring probes; set to 0 to disable.
PUBLIC_ENDPOINT_RPM = int(os.getenv("LOGOS_PUBLIC_ENDPOINT_RPM", "60"))

# Per-IP RPM for *failed* API-key authentication attempts across the API-key
# paths (/v1/models, /v1/chat/completions, ...). Successful auth is governed
# by the existing per-key limits instead, so this budget is spent only by
# record_auth_failure, never merely by attempting a request. Set to 0 to
# disable.
AUTH_FAILURE_RPM = int(os.getenv("LOGOS_AUTH_FAILURE_RPM", "20"))


def _ip_bucket_key(client_ip: str, bucket: str) -> str:
    return f"ip:{client_ip}:{bucket}"


def enforce_ip_rate_limit(client_ip: Optional[str], bucket: str, rpm: int, window_seconds: int = 60) -> None:
    """Raise HTTPException(429) once `client_ip` exceeds `rpm` requests for `bucket`.

    Used for endpoints that admit every caller unconditionally (no
    credential), so the request itself — not some failure within it — is
    what has to be bounded.
    """
    if rpm <= 0 or not client_ip:
        return
    allowed, reason = get_rate_limiter().check_and_record(
        _ip_bucket_key(client_ip, bucket), RateLimitConfig(rpm=rpm, window_seconds=window_seconds)
    )
    if not allowed:
        raise HTTPException(status_code=429, detail=reason, headers={"Retry-After": str(window_seconds)})


def enforce_auth_failure_budget(client_ip: Optional[str]) -> None:
    """Reserve an authentication lookup for `client_ip`.

    The failure budget is checked only after authentication has completed. This
    keeps valid concurrent requests outside the failure budget while still
    counting only completed failures.
    """
    if AUTH_FAILURE_RPM <= 0 or not client_ip:
        return
    get_rate_limiter().reserve_auth_failure(_ip_bucket_key(client_ip, "auth_fail"))


def release_auth_failure_reservation(client_ip: Optional[str]) -> None:
    """Release a reservation after successful authentication or an error."""
    if AUTH_FAILURE_RPM <= 0 or not client_ip:
        return
    get_rate_limiter().release_auth_reservation(_ip_bucket_key(client_ip, "auth_fail"))


def record_auth_failure(client_ip: Optional[str]) -> bool:
    """Record a completed authentication failure and return whether it is allowed."""
    if AUTH_FAILURE_RPM <= 0 or not client_ip:
        return True
    return get_rate_limiter().record_auth_failure(_ip_bucket_key(client_ip, "auth_fail"), AUTH_FAILURE_RPM)
