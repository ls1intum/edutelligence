from unittest.mock import Mock

import httpx
import pytest
from weaviate.exceptions import UnexpectedStatusCodeError

from iris.vector_database.write_retry import (
    MAX_RETRY_WAIT_SECONDS,
    MAX_WRITE_ATTEMPTS,
    WeaviateRateLimitExhausted,
    WeaviateWriteRetry,
)


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.now += delay


def unexpected_status(status_code: int) -> UnexpectedStatusCodeError:
    response = httpx.Response(
        status_code,
        request=httpx.Request("PATCH", "https://weaviate.example/v1/objects/id"),
    )
    return UnexpectedStatusCodeError("Object was not updated", response)


def retry_context(
    clock: FakeClock,
    *,
    retry_wait_budget: float = MAX_RETRY_WAIT_SECONDS,
) -> WeaviateWriteRetry:
    return WeaviateWriteRetry(
        retry_wait_budget=retry_wait_budget,
        sleep=clock.sleep,
        jitter=lambda _lower, upper: upper,
    )


def test_update_retries_http_429_with_exponential_backoff():
    clock = FakeClock()
    collection = Mock()
    collection.data.update.side_effect = [
        unexpected_status(429),
        unexpected_status(429),
        None,
    ]

    retry_context(clock).update(collection, uuid="object-id", properties={"x": 1})

    assert collection.data.update.call_count == 3
    assert clock.sleeps == pytest.approx([0.25, 0.5])


def test_update_does_not_retry_non_rate_limit_errors():
    clock = FakeClock()
    collection = Mock()
    error = unexpected_status(500)
    collection.data.update.side_effect = error

    with pytest.raises(UnexpectedStatusCodeError) as exc_info:
        retry_context(clock).update(collection, uuid="object-id", properties={"x": 1})

    assert exc_info.value is error
    collection.data.update.assert_called_once()
    assert not clock.sleeps


def test_update_stops_before_exceeding_retry_wait_budget():
    clock = FakeClock()
    collection = Mock()
    error = unexpected_status(429)
    collection.data.update.side_effect = error

    with pytest.raises(WeaviateRateLimitExhausted) as exc_info:
        retry_context(clock, retry_wait_budget=0.1).update(
            collection, uuid="object-id", properties={"x": 1}
        )

    assert exc_info.value.attempts == 1
    assert exc_info.value.last_error is error
    collection.data.update.assert_called_once()
    assert not clock.sleeps


def test_update_caps_attempts_even_when_jitter_is_zero():
    clock = FakeClock()
    collection = Mock()
    error = unexpected_status(429)
    collection.data.update.side_effect = error
    writer = WeaviateWriteRetry(
        sleep=clock.sleep,
        jitter=lambda _lower, _upper: 0.0,
    )

    with pytest.raises(WeaviateRateLimitExhausted) as exc_info:
        writer.update(collection, uuid="object-id", properties={"x": 1})

    assert exc_info.value.attempts == MAX_WRITE_ATTEMPTS
    assert collection.data.update.call_count == MAX_WRITE_ATTEMPTS
    assert clock.sleeps == pytest.approx([0.125, 0.25, 0.5, 1.0, 2.0])


def test_default_budget_allows_every_backoff_step():
    clock = FakeClock()
    collection = Mock()
    collection.data.update.side_effect = unexpected_status(429)
    writer = retry_context(clock)

    with pytest.raises(WeaviateRateLimitExhausted):
        writer.update(collection, uuid="object-id", properties={"x": 1})

    assert collection.data.update.call_count == MAX_WRITE_ATTEMPTS
    assert clock.sleeps == pytest.approx([0.25, 0.5, 1.0, 2.0, 4.0])
    assert writer.remaining_retry_wait == pytest.approx(0.25)


def test_retry_wait_budget_is_shared_across_multiple_updates():
    clock = FakeClock()
    collection = Mock()
    collection.data.update.side_effect = [
        unexpected_status(429),
        None,
        unexpected_status(429),
    ]
    writer = retry_context(clock, retry_wait_budget=0.3)

    writer.update(collection, uuid="first", properties={"x": 1})

    with pytest.raises(WeaviateRateLimitExhausted):
        writer.update(collection, uuid="second", properties={"x": 2})

    assert collection.data.update.call_count == 3
    assert clock.sleeps == pytest.approx([0.25])


def test_successful_work_does_not_consume_retry_wait_budget():
    clock = FakeClock()
    collection = Mock()
    collection.data.update.side_effect = [None, unexpected_status(429), None]
    writer = retry_context(clock, retry_wait_budget=0.25)

    writer.update(collection, uuid="first", properties={"x": 1})
    clock.now = 60.0
    writer.update(collection, uuid="second", properties={"x": 2})

    assert collection.data.update.call_count == 3
    assert clock.sleeps == pytest.approx([0.25])
