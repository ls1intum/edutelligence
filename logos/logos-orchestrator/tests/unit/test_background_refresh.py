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


def test_a_write_during_a_load_wins_over_what_the_load_read():
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
