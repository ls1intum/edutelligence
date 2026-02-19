"""Tests for the per-user rate limiter."""

import time

from logos.rate_limiter import RateLimiter, SlidingWindow, RateLimitResult


class TestSlidingWindow:
    """Test the sliding window counter."""

    def test_add_and_get_total(self):
        sw = SlidingWindow()
        now = time.time()
        sw.add(1, timestamp=now)
        sw.add(3, timestamp=now + 1)
        assert sw.get_total(timestamp=now + 2) == 4

    def test_entries_expire(self):
        sw = SlidingWindow(window_size_seconds=10.0)
        now = time.time()
        sw.add(5, timestamp=now)
        # Within window
        assert sw.get_total(timestamp=now + 5) == 5
        # After window expires
        assert sw.get_total(timestamp=now + 11) == 0

    def test_get_reset_time(self):
        sw = SlidingWindow(window_size_seconds=60.0)
        now = time.time()
        sw.add(1, timestamp=now)
        reset = sw.get_reset_time(timestamp=now + 10)
        assert 49.0 <= reset <= 51.0  # ~50 seconds remaining

    def test_get_reset_time_empty(self):
        sw = SlidingWindow()
        assert sw.get_reset_time() == 0.0


class TestRateLimiter:
    """Test the RateLimiter class."""

    def test_allows_under_limit(self):
        limiter = RateLimiter()
        result = limiter.check_rate_limit(process_id=1, rpm_limit=10, tpm_limit=1000)
        assert result.allowed is True
        assert result.rpm_remaining == 10
        assert result.tpm_remaining == 1000

    def test_blocks_rpm_exceeded(self):
        limiter = RateLimiter()
        process_id = 1
        # Record 5 requests
        for _ in range(5):
            limiter.record_request(process_id)
        # Should be blocked at limit of 5
        result = limiter.check_rate_limit(process_id, rpm_limit=5, tpm_limit=None)
        assert result.allowed is False
        assert result.rpm_remaining == 0
        assert result.retry_after is not None
        assert result.retry_after > 0

    def test_blocks_tpm_exceeded(self):
        limiter = RateLimiter()
        process_id = 1
        limiter.record_tokens(process_id, 5000)
        result = limiter.check_rate_limit(process_id, rpm_limit=None, tpm_limit=5000)
        assert result.allowed is False
        assert result.tpm_remaining == 0

    def test_allows_when_no_limits(self):
        limiter = RateLimiter()
        process_id = 1
        # Record many requests
        for _ in range(100):
            limiter.record_request(process_id)
        # No limits = always allowed
        result = limiter.check_rate_limit(process_id, rpm_limit=None, tpm_limit=None)
        assert result.allowed is True

    def test_rpm_resets_after_window(self):
        limiter = RateLimiter()
        process_id = 1
        now = time.time()

        # Add requests at 'now'
        window = limiter._rpm_windows[process_id]
        window.add(1, timestamp=now - 61)  # Outside 60s window
        window.add(1, timestamp=now - 61)

        # At current time, old entries should be expired
        result = limiter.check_rate_limit(process_id, rpm_limit=5, tpm_limit=None)
        assert result.allowed is True
        # Expired entries not counted
        assert result.rpm_remaining == 5

    def test_different_processes_independent(self):
        limiter = RateLimiter()
        # Exhaust process 1
        for _ in range(10):
            limiter.record_request(1)
        # Process 2 should still be ok
        result = limiter.check_rate_limit(2, rpm_limit=10)
        assert result.allowed is True

    def test_record_tokens_counted(self):
        limiter = RateLimiter()
        limiter.record_tokens(1, 500)
        limiter.record_tokens(1, 300)
        result = limiter.check_rate_limit(1, tpm_limit=1000)
        assert result.allowed is True
        assert result.tpm_remaining == 200

    def test_reset_single_process(self):
        limiter = RateLimiter()
        for _ in range(10):
            limiter.record_request(1)
            limiter.record_request(2)
        limiter.reset(process_id=1)
        result1 = limiter.check_rate_limit(1, rpm_limit=5)
        result2 = limiter.check_rate_limit(2, rpm_limit=5)
        assert result1.allowed is True  # Reset
        assert result2.allowed is False  # Still blocked

    def test_reset_all(self):
        limiter = RateLimiter()
        for _ in range(10):
            limiter.record_request(1)
            limiter.record_request(2)
        limiter.reset()
        assert limiter.check_rate_limit(1, rpm_limit=5).allowed is True
        assert limiter.check_rate_limit(2, rpm_limit=5).allowed is True


class TestRateLimitResult:
    """Test RateLimitResult headers."""

    def test_headers_allowed(self):
        result = RateLimitResult(
            allowed=True,
            rpm_limit=60,
            rpm_remaining=55,
            tpm_limit=100000,
            tpm_remaining=95000,
            reset_time=time.time() + 30,
        )
        headers = result.get_headers()
        assert headers["X-RateLimit-Limit-RPM"] == "60"
        assert headers["X-RateLimit-Remaining-RPM"] == "55"
        assert headers["X-RateLimit-Limit-TPM"] == "100000"
        assert headers["X-RateLimit-Remaining-TPM"] == "95000"
        assert "Retry-After" not in headers

    def test_headers_blocked(self):
        result = RateLimitResult(
            allowed=False,
            rpm_limit=60,
            rpm_remaining=-5,
            retry_after=30.0,
            reset_time=time.time() + 30,
        )
        headers = result.get_headers()
        assert "Retry-After" in headers
        assert int(headers["Retry-After"]) > 0
        assert headers["X-RateLimit-Remaining-RPM"] == "0"  # clamped to 0

    def test_headers_no_limits(self):
        result = RateLimitResult(allowed=True)
        headers = result.get_headers()
        assert headers == {}
