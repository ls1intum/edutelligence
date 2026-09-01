"""Behavior tests for InMemoryRateLimiter (issue #672)."""

import logos.rate_limiter as rl
from logos.rate_limiter import InMemoryRateLimiter, RateLimitConfig


def test_admit_within_limits():
    limiter = InMemoryRateLimiter()
    allowed, reason = limiter.check_and_record("k", RateLimitConfig(rpm=5, tpm=1000))
    assert allowed
    assert reason == ""


def test_rpm_rejects_once_the_window_is_full():
    limiter = InMemoryRateLimiter()
    cfg = RateLimitConfig(rpm=2)
    assert limiter.check_and_record("k", cfg)[0]
    assert limiter.check_and_record("k", cfg)[0]
    allowed, reason = limiter.check_and_record("k", cfg)
    assert not allowed
    assert "RPM" in reason


def test_tpm_rejects_when_recorded_tokens_fill_the_window():
    limiter = InMemoryRateLimiter()
    cfg = RateLimitConfig(tpm=100)
    limiter.record_tokens("k", 100)
    allowed, reason = limiter.check_and_record("k", cfg)
    assert not allowed
    assert "TPM" in reason


def test_tpm_reject_does_not_consume_an_rpm_slot(monkeypatch):
    # Regression (issue #672): the /me/keys RPM figure counts admitted
    # requests only, while the limiter enforces over its request window. If
    # a TPM reject appended its RPM timestamp anyway, the enforced RPM would
    # include requests the display excludes, so the UI could show headroom
    # while the limiter keeps rejecting.
    limiter = InMemoryRateLimiter()
    cfg = RateLimitConfig(rpm=2, tpm=100)
    limiter.record_tokens("k", 100)  # fill the TPM window

    # Every check now rejects on TPM.
    for _ in range(3):
        allowed, reason = limiter.check_and_record("k", cfg)
        assert not allowed
        assert "TPM" in reason

    # Let the windows slide away. If any reject had recorded an RPM
    # timestamp, the RPM limit (2) would reject immediately; instead both
    # slots must still be available.
    class _Clock:
        @staticmethod
        def monotonic():
            return 1e9

    monkeypatch.setattr(rl, "time", _Clock())
    assert limiter.check_and_record("k", cfg)[0]
    assert limiter.check_and_record("k", cfg)[0]
    allowed, reason = limiter.check_and_record("k", cfg)
    assert not allowed
    assert "RPM" in reason


def test_tpm_is_checked_before_rpm_is_recorded():
    # Pins the check order: with both limits exhausted the reject reason is
    # TPM, i.e. the RPM timestamp is only appended after both checks pass.
    limiter = InMemoryRateLimiter()
    cfg = RateLimitConfig(rpm=1, tpm=100)
    assert limiter.check_and_record("k", cfg)[0]  # admitted; records the RPM slot
    limiter.record_tokens("k", 100)  # now the TPM window is full too

    allowed, reason = limiter.check_and_record("k", cfg)
    assert not allowed
    assert "TPM" in reason
