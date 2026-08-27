"""`logos_requests_in_flight` must describe reality, in both directions.

The gauge used to be hand-maintained with paired inc()/dec() calls, and the
pairing did not hold:

* terminal paths that write their own log row — a client disconnect, a
  rate-limit or budget reject — never told the recorder the request had
  ended, so each one left an increment behind forever (production leaked
  ~470/day, which is what made the number climb without ever coming back);
* a request that failed classification completed without ever having been
  enqueued, decrementing a count it had never added.

The gauge is now derived from the map of tracked requests, so neither is
expressible. These tests pin that property rather than the call sequence.
"""

from __future__ import annotations

import time

import pytest
from tests.unit.monitoring.test_recorder import _make_recorder, _patch_prom

from logos.monitoring import recorder as recorder_module


@pytest.fixture(autouse=True)
def _isolated_state():
    """The tracked-request map is module state shared across tests."""
    recorder_module._request_states.clear()
    _force_sweep_due()
    yield
    recorder_module._request_states.clear()


def _force_sweep_due() -> None:
    """Make the next arrival run the sweep.

    Not `= 0.0`: the sweep is rate-limited against `time.monotonic()`, whose
    origin is arbitrary — on a freshly booted CI runner it read 58s, so zero
    was still "less than a minute ago" and the sweep never ran.
    """
    recorder_module._last_stale_sweep = time.monotonic() - recorder_module._STALE_SWEEP_INTERVAL_S - 1


def _enqueue(recorder, request_id):
    recorder.record_enqueue(
        request_id=request_id,
        model_id=27,
        provider_id=12,
        initial_priority="normal",
        queue_depth=0,
    )


def test_a_completed_request_is_no_longer_in_flight(monkeypatch):
    recorder, _ = _make_recorder(monkeypatch, {27: "m"}, {12: "p"})
    fake = _patch_prom(monkeypatch)

    _enqueue(recorder, "req-1")
    assert fake.REQUESTS_IN_FLIGHT.value == 1

    recorder.record_complete(request_id="req-1", result_status="success")
    assert fake.REQUESTS_IN_FLIGHT.value == 0


def test_the_gauge_tracks_concurrent_requests(monkeypatch):
    recorder, _ = _make_recorder(monkeypatch, {27: "m"}, {12: "p"})
    fake = _patch_prom(monkeypatch)

    for index in range(3):
        _enqueue(recorder, f"req-{index}")
    assert fake.REQUESTS_IN_FLIGHT.value == 3

    recorder.record_complete(request_id="req-1", result_status="success")
    assert fake.REQUESTS_IN_FLIGHT.value == 2


def test_discarding_a_request_releases_it(monkeypatch):
    """The disconnect / rate-limit / budget path: the log row is written by
    the caller, but the request must still stop counting as in flight."""
    recorder, calls = _make_recorder(monkeypatch, {27: "m"}, {12: "p"})
    fake = _patch_prom(monkeypatch)

    _enqueue(recorder, "req-gone")
    calls.clear()

    recorder.discard("req-gone", "error")

    assert fake.REQUESTS_IN_FLIGHT.value == 0
    assert calls == [], "discard must not write the log row a second time"


def test_discard_still_observes_the_duration(monkeypatch):
    """An abandoned request took real time; dropping it from the histogram
    would bias every latency percentile downwards."""
    recorder, _ = _make_recorder(monkeypatch, {27: "m"}, {12: "p"})
    fake = _patch_prom(monkeypatch)

    _enqueue(recorder, "req-gone")
    recorder.discard("req-gone", "error")

    assert fake.REQUEST_DURATION_SECONDS.label_calls == [{"model": "m", "provider": "p", "status": "error"}]
    assert len(fake.REQUEST_DURATION_SECONDS.observations) == 1


def test_completing_twice_does_not_double_release(monkeypatch):
    recorder, _ = _make_recorder(monkeypatch, {27: "m"}, {12: "p"})
    fake = _patch_prom(monkeypatch)

    _enqueue(recorder, "req-1")
    recorder.record_complete(request_id="req-1", result_status="success")
    recorder.record_complete(request_id="req-1", result_status="success")

    assert fake.REQUESTS_IN_FLIGHT.value == 0
    assert len(fake.REQUEST_DURATION_SECONDS.observations) == 1


def test_a_failure_before_enqueue_cannot_push_the_gauge_negative(monkeypatch):
    """A request rejected at classification completes without ever having
    been enqueued — it used to decrement a count it never added."""
    recorder, _ = _make_recorder(monkeypatch, {}, {})
    fake = _patch_prom(monkeypatch)

    recorder.record_complete(request_id="never-enqueued", result_status="error")

    assert fake.REQUESTS_IN_FLIGHT.value == 0


def test_discarding_an_unknown_request_is_harmless(monkeypatch):
    recorder, _ = _make_recorder(monkeypatch, {}, {})
    fake = _patch_prom(monkeypatch)

    recorder.discard("never-seen", "error")

    assert fake.REQUESTS_IN_FLIGHT.value == 0
    assert fake.REQUEST_DURATION_SECONDS.observations == []


def test_a_discard_then_complete_settles_only_once(monkeypatch):
    """Some paths write the log row and then unwind through a handler that
    records completion as well. That must not double-count."""
    recorder, _ = _make_recorder(monkeypatch, {27: "m"}, {12: "p"})
    fake = _patch_prom(monkeypatch)

    _enqueue(recorder, "req-1")
    recorder.discard("req-1", "error")
    recorder.record_complete(request_id="req-1", result_status="error")

    assert fake.REQUESTS_IN_FLIGHT.value == 0
    assert len(fake.REQUEST_DURATION_SECONDS.observations) == 1


# ---------------------------------------------------------------------------
# Safety net
# ---------------------------------------------------------------------------


def test_requests_older_than_any_plausible_lifetime_are_swept(monkeypatch):
    """A future missed terminal path must degrade into a bounded inaccuracy,
    not an unbounded map and a gauge that never comes down."""
    recorder, _ = _make_recorder(monkeypatch, {27: "m"}, {12: "p"})
    fake = _patch_prom(monkeypatch)

    _enqueue(recorder, "req-leaked")
    # Age it past the cutoff, then let the next arrival trigger the sweep.
    start, model, provider = recorder_module._request_states["req-leaked"]
    recorder_module._request_states["req-leaked"] = (
        start - recorder_module._STALE_REQUEST_AGE_S - 1,
        model,
        provider,
    )
    _force_sweep_due()

    _enqueue(recorder, "req-fresh")

    assert "req-leaked" not in recorder_module._request_states
    assert fake.REQUESTS_IN_FLIGHT.value == 1


def test_the_sweep_leaves_long_running_requests_alone(monkeypatch):
    """A request can legitimately wait 20 minutes in the queue."""
    recorder, _ = _make_recorder(monkeypatch, {27: "m"}, {12: "p"})
    fake = _patch_prom(monkeypatch)

    _enqueue(recorder, "req-slow")
    start, model, provider = recorder_module._request_states["req-slow"]
    recorder_module._request_states["req-slow"] = (start - 1200, model, provider)
    _force_sweep_due()

    _enqueue(recorder, "req-fresh")

    assert "req-slow" in recorder_module._request_states
    assert fake.REQUESTS_IN_FLIGHT.value == 2


def test_the_sweep_is_rate_limited(monkeypatch):
    """It runs off request arrivals, so it must not walk the map every time."""
    recorder, _ = _make_recorder(monkeypatch, {27: "m"}, {12: "p"})
    _patch_prom(monkeypatch)

    due_since = recorder_module._last_stale_sweep
    _enqueue(recorder, "req-1")
    first_sweep = recorder_module._last_stale_sweep
    assert first_sweep > due_since, "the first arrival should have run the sweep"

    _enqueue(recorder, "req-2")
    assert recorder_module._last_stale_sweep == first_sweep
