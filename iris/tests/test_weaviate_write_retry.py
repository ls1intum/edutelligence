from unittest.mock import Mock

import httpx
import pytest
from weaviate.exceptions import UnexpectedStatusCodeError

from iris.vector_database.write_retry import (
    MAX_WRITE_ATTEMPTS,
    WeaviateRateLimitExhausted,
    WeaviateRateLimitGate,
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
    deadline: float = 8.0,
    gate: WeaviateRateLimitGate | None = None,
) -> WeaviateWriteRetry:
    return WeaviateWriteRetry(
        deadline=deadline,
        clock=clock,
        sleep=clock.sleep,
        jitter=lambda _lower, upper: upper,
        gate=gate or WeaviateRateLimitGate(),
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
    assert clock.sleeps == pytest.approx([0.05, 0.1])


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


def test_update_stops_before_sleeping_past_request_deadline():
    clock = FakeClock()
    collection = Mock()
    error = unexpected_status(429)
    collection.data.update.side_effect = error

    with pytest.raises(WeaviateRateLimitExhausted) as exc_info:
        retry_context(clock, deadline=0.04).update(
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
        deadline=8.0,
        clock=clock,
        sleep=clock.sleep,
        jitter=lambda _lower, _upper: 0.0,
        gate=WeaviateRateLimitGate(),
    )

    with pytest.raises(WeaviateRateLimitExhausted) as exc_info:
        writer.update(collection, uuid="object-id", properties={"x": 1})

    assert exc_info.value.attempts == MAX_WRITE_ATTEMPTS
    assert collection.data.update.call_count == MAX_WRITE_ATTEMPTS
    assert not clock.sleeps


def test_request_deadline_is_shared_across_multiple_updates():
    clock = FakeClock()
    collection = Mock()
    collection.data.update.side_effect = [None, unexpected_status(429)]
    writer = retry_context(clock, deadline=8.0)

    writer.update(collection, uuid="first", properties={"x": 1})
    clock.now = 7.98

    with pytest.raises(WeaviateRateLimitExhausted):
        writer.update(collection, uuid="second", properties={"x": 2})

    assert collection.data.update.call_count == 2
    assert not clock.sleeps


def test_shared_gate_delays_another_writer_before_its_first_attempt():
    clock = FakeClock()
    gate = WeaviateRateLimitGate()
    gate.extend(0.2)
    collection = Mock()

    retry_context(clock, gate=gate).update(
        collection, uuid="object-id", properties={"x": 1}
    )

    assert clock.sleeps == pytest.approx([0.2])
    collection.data.update.assert_called_once()
