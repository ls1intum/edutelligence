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


def test_unrelated_lecture_units_are_not_serialized():
    handler = IngestionJobHandler()
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
