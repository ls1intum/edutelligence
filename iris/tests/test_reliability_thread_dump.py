"""The thread dump must show every thread, oldest run first, with identical stacks folded."""

import threading
from unittest.mock import MagicMock

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.reliability.pools import PoolView  # noqa: E402
from iris.reliability.run_registry import RunRecord  # noqa: E402
from iris.reliability.thread_dump import (  # noqa: E402
    format_thread_dump,
    write_thread_dump,
)

WAITERS = 150


def _record(run_id, thread_id, started_at):
    return RunRecord(
        run_id=run_id,
        pipeline="ChatPipeline",
        variant="default",
        local=False,
        callback=MagicMock(phase="running"),
        thread_id=thread_id,
        started_at=started_at,
        model_id="gpt-6-luna-medium",
    )


def _wait_on(event, started):
    started.release()
    event.wait(10)


def _hold_like_the_lock_owner(event, started):
    started.release()
    event.wait(10)


def test_dump_lists_all_threads_with_the_oldest_run_first():
    release = threading.Event()
    started = threading.Semaphore(0)
    waiters = [
        threading.Thread(target=_wait_on, args=(release, started), daemon=True)
        for _ in range(WAITERS)
    ]
    owner = threading.Thread(
        target=_hold_like_the_lock_owner, args=(release, started), daemon=True
    )
    for thread in [owner, *waiters]:
        thread.start()
    for _ in range(WAITERS + 1):
        started.acquire(timeout=5)

    runs = [_record("req-owner", owner.ident, started_at=100.0)] + [
        _record(f"req-{index}", thread.ident, started_at=200.0 + index)
        for index, thread in enumerate(waiters)
    ]
    lock = threading.Lock()
    pool = PoolView(model_id="gpt-6-luna-medium", pool=MagicMock(), lock=lock)
    try:
        text = format_thread_dump("test", runs, [pool], now=1000.0)
    finally:
        release.set()
        for thread in [owner, *waiters]:
            thread.join(5)

    assert "reason: test" in text
    assert "gc: enabled=" in text
    assert "gpt-6-luna-medium: False, 0, 0" in text
    groups = text.split("\n--- ")[1:]
    # The owner started first, so its stack comes first, before the 150 waiters.
    assert "run=req-owner age=900s" in groups[0]
    assert "_hold_like_the_lock_owner" in groups[0]
    waiter_group = next(g for g in groups if f"{WAITERS} thread(s)" in g)
    assert "run=req-0 age=800s" in waiter_group
    assert "and 135 more" in waiter_group
    assert text.index("run=req-owner pipeline") < text.index("run=req-0 pipeline")


def test_the_event_loop_thread_can_be_put_first():
    text = format_thread_dump(
        "event loop stuck", [], first_thread_id=threading.get_ident(), now=0.0
    )

    first_group = text.split("\n--- ")[1]
    assert "test_the_event_loop_thread_can_be_put_first" in first_group


def test_write_keeps_the_dump_in_the_diagnostics_dir(tmp_path):
    path = write_thread_dump(str(tmp_path), "requested", [], lambda: [])

    assert path is not None and path.parent == tmp_path
    assert "reason: requested" in path.read_text()


def test_an_unwritable_dir_still_logs_the_dump(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")

    assert write_thread_dump(str(blocker / "sub"), "requested", [], lambda: []) is None
