"""Sequencing guarantees for superseded lecture-unit ingestion jobs.

The bug: a second ingestion request for a lecture unit already being processed
was dropped, stranding Artemis on a token that never reported. The replacement
must run — but never concurrently with the job it replaced, since a slow-dying
predecessor would otherwise overwrite fresh content with stale content.
"""

import threading
import time

from iris.ingestion.ingestion_job_handler import IngestionJobHandler

COURSE, LECTURE, UNIT = 1, 2, 3


def _handler(max_join_seconds=60.0) -> IngestionJobHandler:
    return IngestionJobHandler(max_join_seconds=max_join_seconds)


def _submit(handler, body, unit=UNIT):
    """Start a job whose body runs only once the handler grants it the slot.

    Returns the job's cancellation event, so tests can observe whether it was
    superseded.
    """
    cancel_event = handler.create_cancellation_event()

    def run():
        if handler.await_turn(COURSE, LECTURE, unit, cancel_event):
            body()

    thread = threading.Thread(target=run)
    handler.add_job(thread, COURSE, LECTURE, unit, cancel_event)
    return cancel_event, thread


def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_new_request_runs_instead_of_being_dropped():
    """The core bug: the superseding request must actually execute."""
    handler = _handler()
    first_running, release_first = threading.Event(), threading.Event()
    second_ran = threading.Event()

    def first():
        first_running.set()
        release_first.wait(timeout=5)

    _submit(handler, first)
    assert first_running.wait(timeout=5)

    _submit(handler, second_ran.set)
    release_first.set()

    assert second_ran.wait(timeout=5), "superseding job was dropped"


def test_successor_does_not_start_until_predecessor_has_exited():
    """What makes a late-dying job harmless.

    A predecessor ignoring its cancellation entirely must still not overlap its
    successor, or it could write stale content after the successor already
    wrote fresh content and reported success.
    """
    handler = _handler()
    first_running, second_done = threading.Event(), threading.Event()
    overlap, active, guard = [], set(), threading.Lock()

    def track(name, hold):
        with guard:
            active.add(name)
            if len(active) > 1:
                overlap.append(set(active))
        time.sleep(hold)
        with guard:
            active.discard(name)

    def first():
        first_running.set()
        track("first", 0.2)  # deliberately ignores its cancel event

    def second():
        track("second", 0.05)
        second_done.set()

    _submit(handler, first)
    assert first_running.wait(timeout=5)
    _submit(handler, second)

    assert second_done.wait(timeout=5), "successor never ran"
    assert not overlap, f"jobs overlapped: {overlap}"


def test_queued_requests_collapse_to_the_newest():
    """Intermediate requests are dead on arrival and must not run."""
    handler = _handler()
    first_running, release_first = threading.Event(), threading.Event()
    ran, guard = [], threading.Lock()

    def record(name):
        def body():
            with guard:
                ran.append(name)

        return body

    def first():
        first_running.set()
        release_first.wait(timeout=5)
        with guard:
            ran.append("first")

    _submit(handler, first)
    assert first_running.wait(timeout=5)
    _submit(handler, record("middle"))
    _submit(handler, record("last"))

    release_first.set()
    assert _wait_until(lambda: "last" in ran), "newest queued job never ran"
    assert ran == ["first", "last"], f"unexpected order: {ran}"


def test_wedged_predecessor_does_not_strand_its_successor():
    """A predecessor that never exits must not block the queued run forever.

    Waiting indefinitely would leave Artemis listening to a token that never
    reports — the bug this handler exists to fix. Past the deadline the
    successor proceeds; safety then rests on the cancel flag, which every write
    site checks.
    """
    handler = _handler(max_join_seconds=0.05)
    wedged_running, release_wedged = threading.Event(), threading.Event()
    successor_ran = threading.Event()

    def wedged():
        wedged_running.set()
        release_wedged.wait(timeout=30)  # ignores cancellation, like a hung socket

    wedged_cancel, _ = _submit(handler, wedged)
    assert wedged_running.wait(timeout=5)
    _submit(handler, successor_ran.set)

    assert successor_ran.wait(timeout=5), "successor stranded behind a wedged job"
    # Still running — that is the scenario — but flagged, so it cannot write.
    assert not release_wedged.is_set()
    assert wedged_cancel.is_set(), "wedged job was never flagged as cancelled"
    release_wedged.set()


def test_unrelated_lecture_units_are_not_serialized():
    """Only same-unit jobs queue; different units stay concurrent."""
    handler = _handler()
    both_running = threading.Barrier(2, timeout=5)

    threads = [_submit(handler, both_running.wait, unit=unit)[1] for unit in (10, 11)]
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
