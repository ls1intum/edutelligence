"""Write-behind queue : off-critical-path DB bookkeeping.

These exercise the queue itself (local instances, so the conftest's global
sync-mode queue is irrelevant). The production behaviour — a dedicated worker
thread draining a bounded FIFO — is what is under test.
"""

from __future__ import annotations

import threading

from logos import write_queue


def test_sync_mode_runs_inline():
    q = write_queue.WriteQueue(sync=True)
    order = []
    q.enqueue(order.append, 1)
    q.enqueue(order.append, 2)
    assert order == [1, 2]  # ran inline, before any shutdown
    assert q.pending() == 0


def test_async_fifo_ordering_is_preserved():
    q = write_queue.WriteQueue(sync=False)
    order = []
    for i in range(50):
        q.enqueue(order.append, i)
    q.shutdown(timeout=2.0)  # drains everything, then joins the thread
    assert order == list(range(50))
    assert q.flushed == 50


def test_drop_when_the_bounded_queue_is_full():
    q = write_queue.WriteQueue(sync=False, maxsize=2)
    started = threading.Event()
    gate = threading.Event()

    def blocker():
        started.set()
        gate.wait(5.0)

    q.enqueue(blocker)
    assert started.wait(1.0)  # worker is inside blocker, parked on the gate
    assert q.enqueue(lambda: None) is True  # buffered (1/2)
    assert q.enqueue(lambda: None) is True  # buffered (2/2)
    assert q.enqueue(lambda: None) is False  # full -> dropped
    gate.set()
    q.shutdown(timeout=5.0)
    assert q.dropped == 1


def test_a_failed_write_does_not_kill_the_drain_thread():
    q = write_queue.WriteQueue(sync=False)
    ran_after = []

    def bad():
        raise RuntimeError("boom")

    q.enqueue(bad)
    q.enqueue(ran_after.append, "after")
    q.shutdown(timeout=2.0)
    assert ran_after == ["after"]
    assert q.errors == 1
    assert q.flushed == 1  # only the non-throwing write counted as flushed


def test_shutdown_is_a_no_op_when_never_used():
    q = write_queue.WriteQueue(sync=False)
    q.shutdown(timeout=0.1)  # no thread was started; must not hang or raise


def test_shutdown_timeout_keeps_a_stalled_worker_registered():
    """A worker that outlives the shutdown deadline must stay registered so a
    later enqueue cannot start a second drain thread (which would break the
    per-request FIFO ordering). Once the stall clears, a follow-up shutdown
    delivers the sentinel and the worker exits cleanly."""
    q = write_queue.WriteQueue(sync=False, maxsize=2)
    started = threading.Event()
    gate = threading.Event()

    def blocker():
        started.set()
        gate.wait(5.0)

    q.enqueue(blocker)
    assert started.wait(1.0)  # worker parked on the gate
    q.enqueue(lambda: None)  # buffered (1/2)
    q.enqueue(lambda: None)  # buffered (2/2) — queue now full

    thread = q._thread  # noqa: SLF001
    q.shutdown(timeout=0.2)  # sentinel cannot fit; deadline must bound this

    assert thread is q._thread  # noqa: SLF001 — still registered, not replaced
    assert thread.is_alive()
    gate.set()
    q.shutdown(timeout=2.0)  # sentinel fits now; worker drains + exits
    assert q._thread is None  # noqa: SLF001 — cleared once the worker is gone
    assert not thread.is_alive()


def test_global_singleton_round_trip():
    original = write_queue.get_write_queue()
    try:
        replacement = write_queue.WriteQueue(sync=True)
        write_queue.set_write_queue(replacement)
        assert write_queue.get_write_queue() is replacement
    finally:
        write_queue.set_write_queue(original)
