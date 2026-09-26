"""Deferred log materialization for the live recent-requests feed.

Warm non-streaming requests keep their log as ``_PendingLog`` until
completion. The feed still needs a row while the request queues, so the
insert is enqueued on the write-behind worker ahead of the identity UPDATEs.
"""

from __future__ import annotations

import pytest

from logos import write_queue


@pytest.fixture(autouse=True)
def _sync_queue():
    write_queue.set_write_queue(write_queue.WriteQueue(sync=True))
    yield
    write_queue.set_write_queue(write_queue.WriteQueue(sync=True))


def test_enqueue_pending_log_is_a_noop_for_materialized_ids(monkeypatch):
    import logos as main

    calls = []
    monkeypatch.setattr(main, "_insert_pending_log_row", lambda fields: calls.append(fields))

    main._enqueue_pending_log_for_live_feed(42)
    main._enqueue_pending_log_for_live_feed(None)
    assert calls == []


def test_enqueue_pending_log_inserts_before_later_queue_work(monkeypatch):
    """FIFO: deferred INSERT must land before a subsequent live identity UPDATE."""
    import logos as main

    order = []

    def insert(fields):
        order.append(("insert", fields["request_id"]))

    def update(request_id, **fields):
        order.append(("update", request_id, sorted(fields)))

    monkeypatch.setattr(main, "_insert_pending_log_row", insert)

    pending = main._PendingLog(
        {
            "api_key_id": 1,
            "team_id": 2,
            "user_id": 3,
            "environment": None,
            "log_level": "NONE",
            "request_id": "req-deferred",
        }
    )
    main._enqueue_pending_log_for_live_feed(pending)
    write_queue.get_write_queue().enqueue(update, "req-deferred", model_id=27, provider_id=12)

    assert order == [
        ("insert", "req-deferred"),
        ("update", "req-deferred", ["model_id", "provider_id"]),
    ]


def test_materialize_log_id_is_idempotent_for_pending_logs(monkeypatch):
    """A live-feed insert that already created the row must not collide."""
    import logos as main

    class DummyDB:
        def __init__(self):
            self.ensure_calls = 0

        def ensure_log_usage(self, **fields):
            self.ensure_calls += 1
            assert fields["request_id"] == "req-once"
            return 99

    db = DummyDB()
    pending = main._PendingLog(
        {
            "api_key_id": 1,
            "team_id": 2,
            "user_id": 3,
            "environment": None,
            "log_level": "NONE",
            "request_id": "req-once",
        }
    )
    assert main._materialize_log_id(db, pending) == 99
    assert main._materialize_log_id(db, pending) == 99
    assert db.ensure_calls == 2
    assert main._materialize_log_id(db, 55) == 55
