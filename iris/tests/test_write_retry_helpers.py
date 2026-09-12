"""Tests for the transient-aware Weaviate write/read retry helpers.

The property under test: a transient store condition (read-only under resource
pressure, a rate limit, a momentary overload) is recovered by retrying only the
failed work in place, never by re-running the pipeline; a non-transient failure
or one that outlasts the budget fails at once with the typed error.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from iris.common.ingestion_errors import (
    STALE_CONTENT_DELETE_FAILED,
    VECTOR_STORE_WRITE_FAILED,
    IngestionStageError,
)
from iris.vector_database.batch_verify import (
    delete_many_with_retry,
    fetch_with_retry,
    write_batch_with_retry,
)
from iris.vector_database.write_retry import (
    WeaviateWriteRetry,
    is_transient_error,
    is_transient_message,
)


def no_wait_retry() -> WeaviateWriteRetry:
    # Zero-delay sleep so retry tests do not actually block.
    return WeaviateWriteRetry(sleep=lambda _delay: None, jitter=lambda _lo, hi: hi)


def _delete_result(failed=0, matches=0):
    return SimpleNamespace(failed=failed, matches=matches, successful=matches - failed)


class FakeBatch:
    """Batch context whose add_object records objects and whose failed_objects is
    scripted per attempt, so a transient-then-clear sequence can be simulated."""

    def __init__(self, failures_per_attempt):
        # failures_per_attempt[i] = list of ErrorObjects the (i+1)-th flush reports
        self.failures_per_attempt = failures_per_attempt
        self.attempt = -1
        self.added = []
        self.failed_objects = []
        self.batch = self

    def rate_limit(self, requests_per_minute):  # pylint: disable=unused-argument
        return self

    def dynamic(self):
        return self

    def __enter__(self):
        self.attempt += 1
        self.added_this_attempt = []
        return self

    def __exit__(self, *exc):
        self.failed_objects = self.failures_per_attempt[self.attempt]
        return False

    def add_object(self, uuid=None, properties=None, vector=None):
        self.added.append((properties, vector))
        self.added_this_attempt.append((properties, vector))


def error_object(message, properties):
    return SimpleNamespace(
        message=message,
        object_=SimpleNamespace(
            uuid="00000000-0000-0000-0000-000000000000",
            properties=properties,
            vector=[0.1],
        ),
    )


class FakeCollection:
    def __init__(self, batch):
        self.batch = batch


def test_transient_marker_classification():
    assert is_transient_message("store is read-only due to: resource pressure")
    assert is_transient_message("Rate limit exceeded")
    assert not is_transient_message("Object validation failed: unknown property")
    assert not is_transient_error(RuntimeError("schema mismatch"))


def test_batch_retries_only_the_dropped_objects_on_transient_failure():
    # First flush drops 1 of 2 with a transient message; second flush is clean.
    dropped = error_object("store is read-only due to: resource pressure", {"p": 2})
    batch = FakeBatch(failures_per_attempt=[[dropped], []])
    collection = FakeCollection(batch)
    prepared = [({"p": 1}, [0.1]), ({"p": 2}, [0.2])]

    write_batch_with_retry(collection, prepared, "page chunks", retry=no_wait_retry())

    # Two flushes happened; the retry re-submitted ONLY the dropped object,
    # not the whole batch (so no vision/embedding rework).
    assert batch.attempt == 1
    assert batch.added == [({"p": 1}, [0.1]), ({"p": 2}, [0.2]), ({"p": 2}, [0.1])]


def test_batch_returns_one_client_assigned_id_per_written_object():
    # The returned ids are what the purge keeps, so there must be exactly one
    # per prepared object and each must be the id the object was written under.
    batch = FakeBatch(failures_per_attempt=[[]])
    collection = FakeCollection(batch)
    prepared = [({"p": 1}, [0.1]), ({"p": 2}, [0.2]), ({"p": 3}, [0.3])]

    written_ids = write_batch_with_retry(
        collection, prepared, "page chunks", retry=no_wait_retry()
    )

    assert len(written_ids) == len(prepared)
    assert len(set(written_ids)) == len(prepared)  # all distinct


def test_batch_fails_immediately_on_non_transient_drop():
    dropped = error_object("validation error: bad property", {"p": 1})
    batch = FakeBatch(failures_per_attempt=[[dropped]])
    collection = FakeCollection(batch)

    with pytest.raises(IngestionStageError) as exc_info:
        write_batch_with_retry(
            collection, [({"p": 1}, [0.1])], "page chunks", retry=no_wait_retry()
        )

    assert exc_info.value.error_code == VECTOR_STORE_WRITE_FAILED
    assert batch.attempt == 0  # no retry for a non-transient failure


def test_batch_raises_when_transient_failure_outlasts_the_budget():
    dropped = error_object("temporarily unavailable", {"p": 1})
    # Every flush keeps dropping the object.
    batch = FakeBatch(failures_per_attempt=[[dropped]] * 10)
    collection = FakeCollection(batch)

    with pytest.raises(IngestionStageError) as exc_info:
        write_batch_with_retry(
            collection, [({"p": 1}, [0.1])], "page chunks", retry=no_wait_retry()
        )

    assert exc_info.value.error_code == VECTOR_STORE_WRITE_FAILED
    assert batch.attempt >= 1  # it retried before giving up


def test_delete_retries_transient_exception_then_succeeds():
    collection = SimpleNamespace(
        data=SimpleNamespace(
            delete_many=MagicMock(
                side_effect=[
                    RuntimeError("store is read-only due to: resource pressure"),
                    _delete_result(matches=3),
                ]
            )
        )
    )

    result = delete_many_with_retry(
        collection, MagicMock(), "stale rows", retry=no_wait_retry()
    )

    assert result.matches == 3
    assert collection.data.delete_many.call_count == 2


def test_delete_does_not_retry_a_returned_failure_count():
    # A returned failed-count is definitive, not a transient exception: fail at once.
    collection = SimpleNamespace(
        data=SimpleNamespace(
            delete_many=MagicMock(return_value=_delete_result(failed=1, matches=3))
        )
    )

    with pytest.raises(IngestionStageError) as exc_info:
        delete_many_with_retry(
            collection, MagicMock(), "stale rows", retry=no_wait_retry()
        )

    assert exc_info.value.error_code == STALE_CONTENT_DELETE_FAILED
    collection.data.delete_many.assert_called_once()


def test_fetch_retries_transient_read_then_returns():
    result = SimpleNamespace(objects=[1, 2, 3])
    fetch = MagicMock(side_effect=[RuntimeError("connection reset by peer"), result])

    assert fetch_with_retry(fetch, retry=no_wait_retry()) is result
    assert fetch.call_count == 2


def test_fetch_does_not_retry_a_non_transient_read_error():
    fetch = MagicMock(side_effect=ValueError("bad query"))

    with pytest.raises(ValueError):
        fetch_with_retry(fetch, retry=no_wait_retry())

    fetch.assert_called_once()
