"""BackgroundRefreshedValue: reads from memory, refreshes in the background, keeps pushed writes."""

import threading
import time

from logos.background_refresh import BackgroundRefreshedValue


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _wait_for(predicate, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_a_read_never_waits_for_a_slow_load():
    release = threading.Event()
    clock = _Clock()

    def loader():
        release.wait(5)
        return {"fresh"}

    value = BackgroundRefreshedValue(loader, initial={"old"}, refresh_after_s=60, clock=clock)

    started = time.monotonic()
    assert value.get() == {"old"}
    assert time.monotonic() - started < 1.0

    release.set()
    assert _wait_for(lambda: value.peek() == {"fresh"})
    assert value.loaded


def test_a_fresh_value_is_not_reloaded_until_it_is_due():
    loads = []
    clock = _Clock()
    value = BackgroundRefreshedValue(lambda: loads.append(1) or len(loads), initial=0, refresh_after_s=60, clock=clock)
    assert value.refresh()

    for _ in range(5):
        assert value.get() == 1
    assert len(loads) == 1

    clock.now += 61
    value.get()
    assert _wait_for(lambda: value.peek() == 2)


def test_a_failed_load_keeps_the_value_and_is_retried_sooner():
    clock = _Clock()
    results = [None]

    def loader():
        result = results[0]
        if isinstance(result, Exception):
            raise result
        return result

    value = BackgroundRefreshedValue(loader, initial="known", refresh_after_s=300, retry_after_s=10, clock=clock)

    assert value.refresh() is False
    results[0] = RuntimeError("database unavailable")
    clock.now += 10
    assert value.refresh() is False
    assert value.get() == "known"
    assert not value.loaded

    results[0] = "reloaded"
    clock.now += 10
    value.get()
    assert _wait_for(lambda: value.peek() == "reloaded")


def test_a_change_during_a_load_is_replayed_onto_the_loaded_value():
    reading = threading.Event()
    release = threading.Event()

    def loader():
        reading.set()
        release.wait(5)
        return frozenset()

    value = BackgroundRefreshedValue(loader, initial=frozenset(), refresh_after_s=60)
    worker = threading.Thread(target=value.refresh)
    worker.start()
    assert reading.wait(5)

    value.update(lambda locks: locks | {("worker", "lane")})
    release.set()
    worker.join(5)

    assert value.peek() == frozenset({("worker", "lane")})


def test_an_update_applies_at_once():
    value = BackgroundRefreshedValue(lambda: None, initial=frozenset(), refresh_after_s=60)

    assert value.update(lambda s: s | {1}) == frozenset({1})
    assert value.peek() == frozenset({1})


def test_an_older_overlapping_load_does_not_overwrite_a_newer_one():
    """A background load is still reading when a change lands and a forced
    refresh starts, reads the change and finishes first. The older load must
    not install its read, which predates the change, over the newer one."""
    old_read_started = threading.Event()
    release_old_read = threading.Event()
    reads = iter(["old-read"])

    def loader():
        value = next(reads, None)
        if value == "old-read":
            old_read_started.set()
            release_old_read.wait(5)
            return frozenset()
        return frozenset({"lock"})

    value = BackgroundRefreshedValue(loader, initial=frozenset(), refresh_after_s=60)
    old_load = threading.Thread(target=value.refresh)
    old_load.start()
    assert old_read_started.wait(5)

    value.update(lambda locks: locks | {"lock"})
    assert value.refresh() is True
    assert value.peek() == frozenset({"lock"})

    release_old_read.set()
    old_load.join(5)

    assert value.peek() == frozenset({"lock"})


def test_each_overlapping_load_replays_only_the_changes_after_its_start():
    first_reading = threading.Event()
    release_first = threading.Event()
    calls = []

    def loader():
        calls.append(1)
        if len(calls) == 1:
            first_reading.set()
            release_first.wait(5)
            return ("first",)
        return ("second",)

    value = BackgroundRefreshedValue(loader, initial=(), refresh_after_s=60)
    first = threading.Thread(target=value.refresh)
    first.start()
    assert first_reading.wait(5)

    value.update(lambda v: v + ("change-1",))
    release_first.set()
    first.join(5)
    # The first load started before change-1, so it replays it.
    assert value.peek() == ("first", "change-1")

    value.update(lambda v: v + ("change-2",))
    assert value.refresh() is True
    # The second load started after both changes and replays neither.
    assert value.peek() == ("second",)


def test_an_older_load_finishing_last_is_dropped_without_an_update_between():
    """Two loads start with no change between them; the newer one finishes
    first. The older one, finishing last, must not install its read."""
    older_reading = threading.Event()
    release_older = threading.Event()
    reads = iter(["older", "newer"])

    def loader():
        which = next(reads)
        if which == "older":
            older_reading.set()
            release_older.wait(5)
            return "older read"
        return "newer read"

    value = BackgroundRefreshedValue(loader, initial="initial", refresh_after_s=60)
    older = threading.Thread(target=value.refresh)
    older.start()
    assert older_reading.wait(5)

    assert value.refresh() is True
    assert value.peek() == "newer read"

    release_older.set()
    older.join(5)

    assert value.peek() == "newer read"
