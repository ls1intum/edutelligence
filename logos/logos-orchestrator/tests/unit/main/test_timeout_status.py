"""Execution failures that are timeouts must settle as result_status=timeout."""

import logos as main


def test_explicit_timed_out_flag():
    assert main._is_timeout_failure(timed_out=True)


def test_error_text_containing_timeout():
    assert main._is_timeout_failure(error="Command timeout waiting for worker response")
    assert main._is_timeout_failure(error="Queue wait timeout after 30s")


def test_http_504_is_a_timeout():
    assert main._is_timeout_failure(status_code=504)


def test_ordinary_errors_stay_errors():
    assert not main._is_timeout_failure(error="upstream exploded")
    assert not main._is_timeout_failure(status_code=502)
    assert not main._is_timeout_failure()
