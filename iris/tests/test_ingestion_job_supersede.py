import threading

from iris.ingestion.ingestion_job_handler import IngestionJobHandler

BASE_URL = "https://artemis.example"
COURSE, LECTURE, UNIT = 1, 2, 3


def _submit(handler, body, unit=UNIT):
    cancel_event = handler.create_cancellation_event()

    def run():
        try:
            body(cancel_event)
        finally:
            handler.complete_job(BASE_URL, COURSE, LECTURE, unit, cancel_event)

    thread = threading.Thread(target=run)
    handler.add_job(thread, BASE_URL, COURSE, LECTURE, unit, cancel_event)
    return cancel_event, thread


def _blocking_body(started, release):
    def body(unused_cancel_event):
        started.set()
        release.wait(timeout=5)

    return body


def test_superseding_request_cancels_the_previous_job():
    handler = IngestionJobHandler()
    first_running, release_first = threading.Event(), threading.Event()
    first_cancel, first_thread = _submit(
        handler, _blocking_body(first_running, release_first)
    )
    assert first_running.wait(timeout=5)
    _submit(handler, lambda unused_cancel_event: None)

    assert first_cancel.is_set(), "superseded job was not cancelled"
    release_first.set()
    first_thread.join(timeout=5)
    assert not first_thread.is_alive()


def test_completed_job_is_not_superseded_by_a_later_request():
    handler = IngestionJobHandler()
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
    handler = IngestionJobHandler()
    first_running = threading.Event()
    second_running = threading.Event()
    release_both = threading.Event()
    _, first_thread = _submit(handler, _blocking_body(first_running, release_both))
    assert first_running.wait(timeout=5)
    _, second_thread = _submit(handler, _blocking_body(second_running, release_both))

    assert second_running.wait(timeout=5), "superseding job never reached preprocessing"
    release_both.set()
    first_thread.join(timeout=5)
    second_thread.join(timeout=5)
    assert not first_thread.is_alive()
    assert not second_thread.is_alive()


def test_revoked_job_is_not_started_and_does_not_supersede_the_current_one():
    handler = IngestionJobHandler()
    current_running, release_current = threading.Event(), threading.Event()
    current_cancel, current_thread = _submit(
        handler, _blocking_body(current_running, release_current)
    )
    assert current_running.wait(timeout=5)

    revoked_cancel = handler.create_cancellation_event()
    revoked_cancel.set()
    started = threading.Event()
    revoked_thread = threading.Thread(target=started.set)
    added = handler.add_job(
        revoked_thread, BASE_URL, COURSE, LECTURE, UNIT, revoked_cancel
    )

    assert added is False
    assert not revoked_thread.is_alive() and not started.is_set()
    assert (
        not current_cancel.is_set()
    ), "a revoked job must not supersede the current one"
    assert handler.is_current_job(BASE_URL, COURSE, LECTURE, UNIT, current_cancel)
    release_current.set()
    current_thread.join(timeout=5)


def test_add_job_reports_that_it_started_the_job():
    handler = IngestionJobHandler()
    cancel_event = handler.create_cancellation_event()
    thread = threading.Thread(target=lambda: None)
    assert (
        handler.add_job(thread, BASE_URL, COURSE, LECTURE, UNIT, cancel_event) is True
    )
    thread.join(timeout=5)
