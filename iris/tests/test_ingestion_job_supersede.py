"""Sequencing guarantees for superseded lecture-unit ingestion jobs."""

import threading
import time

from iris.ingestion.ingestion_job_handler import IngestionJobHandler
from iris.ingestion.ingestion_job_registry import ingestion_job_owner_guard

BASE_URL = "https://artemis.example"
COURSE, LECTURE, UNIT = 1, 2, 3


def _handler() -> IngestionJobHandler:
    return IngestionJobHandler()


def _submit(handler, body, unit=UNIT):
    """Start a job and return its cancellation event and thread."""
    cancel_event = handler.create_cancellation_event()

    def run():
        try:
            body(cancel_event)
        finally:
            handler.complete_job(BASE_URL, COURSE, LECTURE, unit, cancel_event)

    thread = threading.Thread(target=run)
    handler.add_job(thread, BASE_URL, COURSE, LECTURE, unit, cancel_event)
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


def test_completed_job_is_not_superseded_by_a_later_request():
    """A finished job must leave no entry behind that a later request cancels."""
    handler = _handler()
    finished = threading.Event()

    first_cancel, first_thread = _submit(
        handler, lambda unused_cancel_event: finished.set()
    )

    assert finished.wait(timeout=5)
    first_thread.join(timeout=5)
    assert not first_thread.is_alive()

    _, second_thread = _submit(handler, lambda unused_cancel_event: None)
    second_thread.join(timeout=5)

    assert not first_cancel.is_set(), "completed job was still tracked as running"


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
    barrier_results = {}

    def worker(unit):
        try:
            both_running.wait()
            barrier_results[unit] = "ok"
        except Exception as exc:  # pragma: no cover - asserted via captured result
            barrier_results[unit] = type(exc).__name__

    threads = [
        _submit(
            handler, lambda unused_cancel_event, unit=unit: worker(unit), unit=unit
        )[1]
        for unit in (10, 11)
    ]
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert barrier_results == {10: "ok", 11: "ok"}


def test_superseding_request_waits_for_current_job_commit_boundary():
    handler = _handler()
    inside_commit = threading.Event()
    release_commit = threading.Event()
    second_done = threading.Event()

    def first(cancel_event):
        with ingestion_job_owner_guard(
            base_url=BASE_URL,
            course_id=COURSE,
            lecture_id=LECTURE,
            lecture_unit_id=UNIT,
            cancel_event=cancel_event,
            stage="test commit",
        ):
            inside_commit.set()
            release_commit.wait(timeout=5)

    first_cancel, first_thread = _submit(handler, first)
    assert inside_commit.wait(timeout=5)

    launcher = threading.Thread(
        target=lambda: _submit(handler, lambda unused_cancel_event: second_done.set())
    )
    launcher.start()

    time.sleep(0.2)
    assert first_cancel.is_set() is False
    assert second_done.is_set() is False

    release_commit.set()
    first_thread.join(timeout=5)
    launcher.join(timeout=5)
    assert not launcher.is_alive()
    assert second_done.wait(timeout=5)
