"""
Per-user rate limiter for Logos using a sliding window algorithm.

Tracks requests per minute (RPM) and tokens per minute (TPM) per process.
Rate limits are read from process.settings JSONB field.
"""

import time
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class SlidingWindow:
    """A sliding window counter for rate limiting."""
    window_size_seconds: float = 60.0
    _entries: list = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _cleanup(self, now: float) -> None:
        """Remove entries outside the current window."""
        cutoff = now - self.window_size_seconds
        self._entries = [e for e in self._entries if e[0] > cutoff]

    def add(self, count: int = 1, timestamp: Optional[float] = None) -> None:
        """Add count to the window."""
        now = timestamp or time.time()
        with self._lock:
            self._cleanup(now)
            self._entries.append((now, count))

    def get_total(self, timestamp: Optional[float] = None) -> int:
        """Get total count in the current window."""
        now = timestamp or time.time()
        with self._lock:
            self._cleanup(now)
            return sum(e[1] for e in self._entries)

    def get_reset_time(self, timestamp: Optional[float] = None) -> float:
        """Get seconds until the oldest entry in the window expires."""
        now = timestamp or time.time()
        with self._lock:
            self._cleanup(now)
            if not self._entries:
                return 0.0
            oldest = min(e[0] for e in self._entries)
            return max(0.0, (oldest + self.window_size_seconds) - now)


class RateLimitResult:
    """Result of a rate limit check."""
    def __init__(
        self,
        allowed: bool,
        rpm_limit: Optional[int] = None,
        rpm_remaining: Optional[int] = None,
        tpm_limit: Optional[int] = None,
        tpm_remaining: Optional[int] = None,
        retry_after: Optional[float] = None,
        reset_time: Optional[float] = None,
    ):
        self.allowed = allowed
        self.rpm_limit = rpm_limit
        self.rpm_remaining = rpm_remaining
        self.tpm_limit = tpm_limit
        self.tpm_remaining = tpm_remaining
        self.retry_after = retry_after
        self.reset_time = reset_time

    def get_headers(self) -> Dict[str, str]:
        """Return rate limit response headers."""
        headers = {}
        if self.rpm_limit is not None:
            headers["X-RateLimit-Limit-RPM"] = str(self.rpm_limit)
        if self.rpm_remaining is not None:
            headers["X-RateLimit-Remaining-RPM"] = str(max(0, self.rpm_remaining))
        if self.tpm_limit is not None:
            headers["X-RateLimit-Limit-TPM"] = str(self.tpm_limit)
        if self.tpm_remaining is not None:
            headers["X-RateLimit-Remaining-TPM"] = str(max(0, self.tpm_remaining))
        if self.reset_time is not None:
            headers["X-RateLimit-Reset"] = str(int(self.reset_time))
        if not self.allowed and self.retry_after is not None:
            headers["Retry-After"] = str(int(self.retry_after) + 1)
        return headers


class RateLimiter:
    """
    In-memory per-process rate limiter using sliding window counters.

    Tracks RPM and TPM independently for each process_id.
    """

    def __init__(self):
        self._rpm_windows: Dict[int, SlidingWindow] = defaultdict(SlidingWindow)
        self._tpm_windows: Dict[int, SlidingWindow] = defaultdict(SlidingWindow)
        self._lock = threading.Lock()

    def check_rate_limit(
        self,
        process_id: int,
        rpm_limit: Optional[int] = None,
        tpm_limit: Optional[int] = None,
    ) -> RateLimitResult:
        """
        Check if a request is allowed under the rate limits.

        Args:
            process_id: The process (user) to check
            rpm_limit: Max requests per minute (None = unlimited)
            tpm_limit: Max tokens per minute (None = unlimited)

        Returns:
            RateLimitResult with allowed=True/False and rate limit metadata
        """
        if rpm_limit is None and tpm_limit is None:
            return RateLimitResult(allowed=True)

        now = time.time()

        with self._lock:
            rpm_window = self._rpm_windows[process_id]
            tpm_window = self._tpm_windows[process_id]

        current_rpm = rpm_window.get_total(now)
        current_tpm = tpm_window.get_total(now)

        rpm_remaining = (rpm_limit - current_rpm) if rpm_limit is not None else None
        tpm_remaining = (tpm_limit - current_tpm) if tpm_limit is not None else None

        rpm_exceeded = rpm_limit is not None and current_rpm >= rpm_limit
        tpm_exceeded = tpm_limit is not None and current_tpm >= tpm_limit

        if rpm_exceeded or tpm_exceeded:
            retry_after = max(
                rpm_window.get_reset_time(now) if rpm_exceeded else 0.0,
                tpm_window.get_reset_time(now) if tpm_exceeded else 0.0,
            )
            reset_time = now + retry_after
            return RateLimitResult(
                allowed=False,
                rpm_limit=rpm_limit,
                rpm_remaining=rpm_remaining,
                tpm_limit=tpm_limit,
                tpm_remaining=tpm_remaining,
                retry_after=retry_after,
                reset_time=reset_time,
            )

        reset_time_val = now + max(
            rpm_window.get_reset_time(now),
            tpm_window.get_reset_time(now),
        )

        return RateLimitResult(
            allowed=True,
            rpm_limit=rpm_limit,
            rpm_remaining=rpm_remaining,
            tpm_limit=tpm_limit,
            tpm_remaining=tpm_remaining,
            reset_time=reset_time_val,
        )

    def check_and_record(
        self,
        process_id: int,
        rpm_limit: Optional[int] = None,
        tpm_limit: Optional[int] = None,
    ) -> RateLimitResult:
        """
        Atomically check rate limits and record the request if allowed.

        Preferred over separate check_rate_limit() + record_request() calls
        to avoid TOCTOU race conditions at the rate limit boundary.
        """
        if rpm_limit is None and tpm_limit is None:
            return RateLimitResult(allowed=True)

        now = time.time()

        with self._lock:
            rpm_window = self._rpm_windows[process_id]
            tpm_window = self._tpm_windows[process_id]

            current_rpm = rpm_window.get_total(now)
            current_tpm = tpm_window.get_total(now)

            rpm_remaining = (rpm_limit - current_rpm) if rpm_limit is not None else None
            tpm_remaining = (tpm_limit - current_tpm) if tpm_limit is not None else None

            rpm_exceeded = rpm_limit is not None and current_rpm >= rpm_limit
            tpm_exceeded = tpm_limit is not None and current_tpm >= tpm_limit

            if rpm_exceeded or tpm_exceeded:
                retry_after = max(
                    rpm_window.get_reset_time(now) if rpm_exceeded else 0.0,
                    tpm_window.get_reset_time(now) if tpm_exceeded else 0.0,
                )
                reset_time = now + retry_after
                return RateLimitResult(
                    allowed=False,
                    rpm_limit=rpm_limit,
                    rpm_remaining=rpm_remaining,
                    tpm_limit=tpm_limit,
                    tpm_remaining=tpm_remaining,
                    retry_after=retry_after,
                    reset_time=reset_time,
                )

            # Allowed — record immediately under the same lock
            rpm_window.add(1, now)

            reset_time_val = now + max(
                rpm_window.get_reset_time(now),
                tpm_window.get_reset_time(now),
            )

            return RateLimitResult(
                allowed=True,
                rpm_limit=rpm_limit,
                rpm_remaining=(rpm_remaining - 1) if rpm_remaining is not None else None,
                tpm_limit=tpm_limit,
                tpm_remaining=tpm_remaining,
                reset_time=reset_time_val,
            )

    def record_request(self, process_id: int) -> None:
        """Record a new request for RPM tracking."""
        with self._lock:
            window = self._rpm_windows[process_id]
        window.add(1)

    def record_tokens(self, process_id: int, token_count: int) -> None:
        """Record token usage for TPM tracking."""
        if token_count > 0:
            with self._lock:
                window = self._tpm_windows[process_id]
            window.add(token_count)

    def reset(self, process_id: Optional[int] = None) -> None:
        """Reset rate limit state. If process_id given, reset only that process."""
        with self._lock:
            if process_id is not None:
                self._rpm_windows.pop(process_id, None)
                self._tpm_windows.pop(process_id, None)
            else:
                self._rpm_windows.clear()
                self._tpm_windows.clear()


# Global singleton rate limiter instance
_rate_limiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    """Get the global rate limiter instance."""
    return _rate_limiter
