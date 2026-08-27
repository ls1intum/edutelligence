"""Requests in flight when the orchestrator restarts must not stay "running".

A log row is written on arrival and finalised in-process. A deploy or crash
kills the process holding that half-finished row, and nothing else ever
revisits it — so every live-request view keeps counting requests that ended
when the process did. Startup is the one moment where "no terminal state"
unambiguously means "orphaned", so the sweep belongs there and nowhere else.
"""

from __future__ import annotations

import pytest

import logos as main


class _DB:
    def __init__(self, *, closed: int = 0, raises: Exception | None = None):
        self._closed = closed
        self._raises = raises
        self.calls: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def close_orphaned_request_logs(self, error_message: str) -> int:
        if self._raises is not None:
            raise self._raises
        self.calls.append(error_message)
        return self._closed


def test_orphaned_rows_are_closed_with_an_explanatory_message(monkeypatch, caplog):
    db = _DB(closed=3)
    monkeypatch.setattr(main, "DBManager", lambda: db)

    with caplog.at_level("INFO"):
        main._close_orphaned_request_logs()

    assert db.calls == [main.ORPHANED_REQUEST_ERROR]
    assert "Closed 3 request log(s)" in caplog.text


def test_nothing_is_logged_when_there_was_nothing_to_close(monkeypatch, caplog):
    db = _DB(closed=0)
    monkeypatch.setattr(main, "DBManager", lambda: db)

    with caplog.at_level("INFO"):
        main._close_orphaned_request_logs()

    assert db.calls == [main.ORPHANED_REQUEST_ERROR]
    assert "request log(s)" not in caplog.text


def test_a_database_failure_does_not_block_startup(monkeypatch, caplog):
    """Stale rows are a reporting defect; an orchestrator that will not boot
    is an outage. The sweep must never be the reason startup fails."""
    monkeypatch.setattr(main, "DBManager", lambda: _DB(raises=RuntimeError("db down")))

    with caplog.at_level("WARNING"):
        main._close_orphaned_request_logs()  # must not raise

    assert "Could not close orphaned request logs" in caplog.text


@pytest.mark.parametrize("rowcount", [0, 1, 42])
def test_the_closed_count_is_reported_verbatim(monkeypatch, rowcount):
    db = _DB(closed=rowcount)
    monkeypatch.setattr(main, "DBManager", lambda: db)
    main._close_orphaned_request_logs()
    assert db.calls == [main.ORPHANED_REQUEST_ERROR]
