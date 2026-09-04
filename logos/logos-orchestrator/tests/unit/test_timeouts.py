"""Global request-lifecycle timeout knob and the queue-wait budget.

``remaining_queue_wait_s`` converts the whole-request client window into the
budget a scheduler may still spend waiting in queue: everything before
enqueue (auth, worker reconnect wait, classification) counts against it, so
the queue-timeout 429 cannot land after the client's idle watchdog already
fired. The window is the request's own ``timeout_s`` when it is smaller than
the default/global window — that is what the client actually waits on.
"""

import time

import pytest

from logos.timeouts import DEFAULT_QUEUE_WAIT_TIMEOUT_S, global_timeout_s, remaining_queue_wait_s


def test_no_ingress_stamp_keeps_the_plain_window():
    # Async jobs, tests and proxy mode have no client watchdog to beat.
    assert remaining_queue_wait_s(None) is None


def test_fresh_ingress_gets_the_full_window():
    assert remaining_queue_wait_s(time.monotonic()) == pytest.approx(DEFAULT_QUEUE_WAIT_TIMEOUT_S, abs=1.0)


def test_time_spent_before_enqueue_is_subtracted():
    ingress = time.monotonic() - 100.0
    assert remaining_queue_wait_s(ingress) == pytest.approx(DEFAULT_QUEUE_WAIT_TIMEOUT_S - 100.0, abs=1.0)


def test_window_already_spent_leaves_zero_budget():
    # The scheduler receives 0.0, not a negative number: wait_for(0) still
    # yields to the event loop once before timing out.
    assert remaining_queue_wait_s(time.monotonic() - DEFAULT_QUEUE_WAIT_TIMEOUT_S - 5.0) == 0.0


def test_global_timeout_overrides_the_window(monkeypatch):
    monkeypatch.setenv("LOGOS_TIMEOUT_S", "600")
    assert global_timeout_s(DEFAULT_QUEUE_WAIT_TIMEOUT_S) == 600.0
    assert remaining_queue_wait_s(time.monotonic()) == pytest.approx(600.0, abs=1.0)


def test_invalid_global_timeout_falls_back_to_the_default(monkeypatch):
    for raw in ("", "abc", "0", "-5"):
        monkeypatch.setenv("LOGOS_TIMEOUT_S", raw)
        assert global_timeout_s(DEFAULT_QUEUE_WAIT_TIMEOUT_S) == DEFAULT_QUEUE_WAIT_TIMEOUT_S


def test_request_timeout_shorter_than_the_window_binds():
    # The client waits timeout_s seconds in total, so it is the window the
    # pre-queue time is deducted from, not the default.
    assert remaining_queue_wait_s(time.monotonic() - 10.0, 50.0) == pytest.approx(40.0, abs=1.0)


def test_request_timeout_longer_than_the_window_keeps_the_window():
    assert remaining_queue_wait_s(time.monotonic() - 10.0, 400.0) == pytest.approx(
        DEFAULT_QUEUE_WAIT_TIMEOUT_S - 10.0, abs=1.0
    )


def test_invalid_request_timeout_is_treated_as_absent():
    for raw in (None, 0.0, -5.0, "abc"):
        left = remaining_queue_wait_s(time.monotonic(), raw)
        assert left == pytest.approx(DEFAULT_QUEUE_WAIT_TIMEOUT_S, abs=1.0)


def test_request_timeout_binds_under_the_global_override(monkeypatch):
    monkeypatch.setenv("LOGOS_TIMEOUT_S", "600")
    assert remaining_queue_wait_s(time.monotonic() - 10.0, 50.0) == pytest.approx(40.0, abs=1.0)
