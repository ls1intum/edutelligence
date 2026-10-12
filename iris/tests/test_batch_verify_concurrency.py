"""Tests for the optional parallel object-store confirmation in batch_verify.

The census confirms every row of a course against the object store, one read per row.
``concurrency`` runs those reads in parallel; the result must stay identical to the
sequential one that ingestion and the audit rely on.
"""

# pylint: disable=protected-access

import threading
import time
from types import SimpleNamespace

import pytest

from iris.vector_database import batch_verify
from iris.vector_database.batch_verify import confirmed_generations, confirmed_rows
from iris.vector_database.write_retry import (
    WeaviateRateLimitExhausted,
    WeaviateWriteRetry,
)

RUN_ID = "ingestion_run_id"


def _fast_retry() -> WeaviateWriteRetry:
    return WeaviateWriteRetry(sleep=lambda _delay: None)


class _Store:
    """A collection whose object-store reads are instrumented."""

    def __init__(self, rows, ghosts=(), delay=0.0, fail_first=0, always_fail=False):
        self.rows = rows
        self.ghosts = set(ghosts)
        self.delay = delay
        self.fail_first = fail_first
        self.always_fail = always_fail
        self._lock = threading.Lock()
        self._running = 0
        self.peak = 0
        self.calls = 0
        self._failures: dict = {}
        self.query = SimpleNamespace(
            fetch_objects=lambda **_kwargs: SimpleNamespace(objects=list(self.rows)),
            fetch_object_by_id=self._fetch_object_by_id,
        )

    def _fetch_object_by_id(self, object_uuid):
        with self._lock:
            self.calls += 1
            self._running += 1
            self.peak = max(self.peak, self._running)
            seen = self._failures.get(object_uuid, 0)
            self._failures[object_uuid] = seen + 1
        try:
            if self.delay:
                time.sleep(self.delay)
            if self.always_fail or seen < self.fail_first:
                raise RuntimeError("request timed out")
            return None if object_uuid in self.ghosts else SimpleNamespace()
        finally:
            with self._lock:
                self._running -= 1


def _row(object_uuid, run_id="run-a"):
    return SimpleNamespace(uuid=object_uuid, properties={RUN_ID: run_id})


def _rows(count, run_id="run-a", prefix="r"):
    return [_row(f"{prefix}-{index}", run_id) for index in range(count)]


class TestConfirmedRows:
    """confirmed_rows: one object-store read per row."""

    def test_parallel_result_equals_sequential_including_ghosts(self):
        rows = _rows(53)
        ghosts = {row.uuid for row in rows[::3]}
        sequential = confirmed_rows(_Store(rows, ghosts), rows, retry=_fast_retry())
        parallel = confirmed_rows(
            _Store(rows, ghosts), rows, retry=_fast_retry(), concurrency=8
        )
        assert parallel == sequential
        assert [row.uuid for row in parallel] == [
            row.uuid for row in rows if row.uuid not in ghosts
        ]

    def test_never_runs_more_than_concurrency_reads_at_once(self):
        rows = _rows(40)
        store = _Store(rows, delay=0.02)
        confirmed_rows(store, rows, concurrency=5)
        assert store.calls == 40
        assert 1 < store.peak <= 5

    def test_default_is_sequential_and_creates_no_pool(self, monkeypatch):
        def no_pool(*_args, **_kwargs):
            raise AssertionError("the sequential path must not create a pool")

        monkeypatch.setattr(batch_verify, "ThreadPoolExecutor", no_pool)
        rows = _rows(5)
        store = _Store(rows, delay=0.001)
        assert confirmed_rows(store, rows) == rows
        assert store.peak == 1

    def test_transient_failure_is_retried_by_every_parallel_task(self, monkeypatch):
        contexts = []

        def fresh_retry(cls):  # pylint: disable=unused-argument
            contexts.append(_fast_retry())
            return contexts[-1]

        monkeypatch.setattr(WeaviateWriteRetry, "for_request", classmethod(fresh_retry))
        rows = _rows(12)
        store = _Store(rows, fail_first=1)
        shared = _fast_retry()
        assert confirmed_rows(store, rows, retry=shared, concurrency=4) == rows
        assert store.calls == 24  # each read failed once, then succeeded
        # No retry state is shared: every task got its own context, not `shared`.
        assert len(contexts) == len(rows)
        assert len({id(context) for context in contexts}) == len(rows)

    @pytest.mark.parametrize("concurrency", [1, 4])
    def test_exhausted_retries_raise_as_before(self, concurrency, monkeypatch):
        monkeypatch.setattr(
            WeaviateWriteRetry, "for_request", classmethod(lambda cls: _fast_retry())
        )
        rows = _rows(6)
        store = _Store(rows, always_fail=True)
        with pytest.raises(WeaviateRateLimitExhausted):
            confirmed_rows(store, rows, retry=_fast_retry(), concurrency=concurrency)


class TestConfirmedGenerations:
    """confirmed_generations: one verdict per ingestion generation."""

    def _scene(self):
        # Generation "a": its first scanned rows are ghosts but a later one is real.
        # Generation "b": fully real. Generation "ghost": nothing is real.
        rows = _rows(4, "a", "a") + _rows(5, "b", "b") + _rows(3, "ghost", "g")
        ghosts = {"a-0", "a-1", "a-2", *{f"g-{index}" for index in range(3)}}
        return rows, ghosts

    def test_parallel_result_equals_sequential_including_ghosts(self):
        rows, ghosts = self._scene()
        kwargs = {"limit": 100}
        sequential = confirmed_generations(
            _Store(rows, ghosts), None, RUN_ID, retry=_fast_retry(), **kwargs
        )
        parallel = confirmed_generations(
            _Store(rows, ghosts),
            None,
            RUN_ID,
            retry=_fast_retry(),
            concurrency=8,
            **kwargs,
        )
        assert parallel == sequential
        assert sequential[0] == {"a", "b"}
        assert len(sequential[1]) == len(rows)

    def test_checks_a_generation_in_scan_order_and_stops_at_the_first_real_row(self):
        rows = _rows(6, "a", "a")
        store = _Store(rows, ghosts={"a-0", "a-1"})
        real, _ = confirmed_generations(
            store, None, RUN_ID, limit=100, concurrency=4, retry=_fast_retry()
        )
        assert real == {"a"}
        assert store.calls == 3  # a-0 (ghost), a-1 (ghost), a-2 (real), then stop

    def test_never_runs_more_than_concurrency_reads_at_once(self):
        rows = []
        for generation in range(12):
            rows += _rows(1, f"gen-{generation}", f"gen-{generation}")
        store = _Store(rows, delay=0.02)
        real, _ = confirmed_generations(
            store, None, RUN_ID, limit=100, concurrency=3, retry=_fast_retry()
        )
        assert len(real) == 12
        assert 1 < store.peak <= 3

    def test_transient_failure_is_retried_and_exhaustion_raises(self, monkeypatch):
        monkeypatch.setattr(
            WeaviateWriteRetry, "for_request", classmethod(lambda cls: _fast_retry())
        )
        rows = _rows(1, "a", "a") + _rows(1, "b", "b")
        store = _Store(rows, fail_first=1)
        real, _ = confirmed_generations(store, None, RUN_ID, limit=100, concurrency=2)
        assert real == {"a", "b"}
        with pytest.raises(WeaviateRateLimitExhausted):
            confirmed_generations(
                _Store(rows, always_fail=True), None, RUN_ID, limit=100, concurrency=2
            )
