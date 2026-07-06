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
        now = time.monotonic()
        cutoff = now - config.window_seconds

        with self._lock:
            if config.rpm is not None:
                req_dq = self._request_windows.setdefault(key, deque())
                self._prune_requests(req_dq, cutoff)

                if len(req_dq) >= config.rpm:
                    return (
                        False,
                        f"RPM limit reached ({config.rpm}/{config.window_seconds}s)",
                    )

                req_dq.append(now)

            if config.tpm is not None:
                tok_dq = self._token_windows.setdefault(key, deque())
                self._prune_tokens(tok_dq, cutoff)

                total = sum(tokens for _, tokens in tok_dq)
                if total >= config.tpm:
                    return (
                        False,
                        f"TPM limit reached ({config.tpm}/{config.window_seconds}s)",
                    )

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
