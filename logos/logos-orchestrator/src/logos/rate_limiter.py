from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional, Tuple


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


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._request_windows: dict[str, deque] = {}
        self._token_windows: dict[str, deque] = {}

    def _prune_requests(self, dq: deque, cutoff: float) -> None:
        while dq and dq[0] < cutoff:
            dq.popleft()

    def _prune_tokens(self, dq: deque, cutoff: float) -> None:
        while dq and dq[0][0] < cutoff:
            dq.popleft()

    def check_and_record(self, key: str, config: RateLimitConfig) -> Tuple[bool, str]:
        # The TPM check runs before the RPM slot is recorded. A request the
        # TPM limit rejects must not consume an RPM slot: the /me/keys usage
        # window (issue #672) displays admitted requests only, so a TPM
        # reject that still appended its RPM timestamp would leave the
        # displayed RPM below the enforced one — the UI showing headroom
        # while the limiter keeps returning 429.
        now = time.monotonic()
        cutoff = now - config.window_seconds

        with self._lock:
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
            tok_dq = self._token_windows.setdefault(key, deque())
            tok_dq.append((now, token_count))


_rate_limiter: Optional[InMemoryRateLimiter] = None
_rate_limiter_lock = threading.Lock()


def get_rate_limiter() -> InMemoryRateLimiter:
    global _rate_limiter

    if _rate_limiter is None:
        with _rate_limiter_lock:
            if _rate_limiter is None:
                _rate_limiter = InMemoryRateLimiter()

    return _rate_limiter
