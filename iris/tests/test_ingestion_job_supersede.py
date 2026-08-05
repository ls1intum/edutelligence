"""Sequencing guarantees for superseded lecture-unit ingestion jobs."""

import threading

from iris.ingestion.ingestion_job_handler import IngestionJobHandler

COURSE, LECTURE, UNIT = 1, 2, 3


def _handler() -> IngestionJobHandler:
    return IngestionJobHandler()


def _submit(handler, body, unit=UNIT):
    """Start a job and return its cancellation event and thread."""
    cancel_event = handler.create_cancellation_event()

    def run():
        body(cancel_event)

    thread = threading.Thread(target=run)
    handler.add_job(thread, COURSE, LECTURE, unit, cancel_event)
    return cancel_event, thread


def test_new_request_runs_instead_of_being_dropped():
    """The core bug: the superseding request must actually execute."""
    handler = _handler()
    first_running, release_first = threading.Event(), threading.Event()
    second_ran = threading.Event()

    def first(unused_cancel_event):
        first_running.set()
        release_first.wait(timeout=5)

    _submit(handler, first)
    assert first_running.wait(timeout=5)

    _submit(handler, lambda unused_cancel_event: second_ran.set())
    release_first.set()

    assert second_ran.wait(timeout=5), "superseding job was dropped"


def test_superseding_request_cancels_the_previous_job():
    handler = _handler()
    first_running, release_first = threading.Event(), threading.Event()

    def first(unused_cancel_event):
        first_running.set()
        release_first.wait(timeout=5)

    first_cancel, first_thread = _submit(handler, first)
    assert first_running.wait(timeout=5)
    _submit(handler, lambda unused_cancel_event: None)

    assert first_cancel.is_set(), "superseded job was not cancelled"
    release_first.set()
    first_thread.join(timeout=5)
    assert not first_thread.is_alive()


def test_superseded_request_does_not_commit_stale_write():
    handler = _handler()
    first_running = threading.Event()
    allow_first_commit = threading.Event()
    second_done = threading.Event()
    writes = []

    def first(cancel_event):
        first_running.set()
        allow_first_commit.wait(timeout=5)
        if cancel_event.is_set():
            return
        writes.append("first")

    def second(unused_cancel_event):
        writes.append("second")
        second_done.set()

    _, first_thread = _submit(handler, first)
    assert first_running.wait(timeout=5)
    _, second_thread = _submit(handler, second)
    assert second_done.wait(timeout=5)

    allow_first_commit.set()
    first_thread.join(timeout=5)
    second_thread.join(timeout=5)

    assert writes == ["second"]


def test_same_unit_jobs_can_overlap_during_preprocessing():
    """Same-unit requests should not serialize whole worker threads."""
    handler = _handler()
    first_running = threading.Event()
    second_running = threading.Event()
    release_both = threading.Event()

    def first(unused_cancel_event):
        first_running.set()
        release_both.wait(timeout=5)

    def second(unused_cancel_event):
        second_running.set()
        release_both.wait(timeout=5)

    _, first_thread = _submit(handler, first)
    assert first_running.wait(timeout=5)
    _, second_thread = _submit(handler, second)

    assert second_running.wait(timeout=5), "superseding job never reached preprocessing"
    release_both.set()
    first_thread.join(timeout=5)
    second_thread.join(timeout=5)
    assert not first_thread.is_alive()
    assert not second_thread.is_alive()


def test_unrelated_lecture_units_are_not_serialized():
    """Only same-unit jobs queue; different units stay concurrent."""
    handler = _handler()
    both_running = threading.Barrier(2, timeout=5)

    threads = [
        _submit(handler, lambda unused_cancel_event: both_running.wait(), unit=unit)[1]
        for unit in (10, 11)
    ]
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
