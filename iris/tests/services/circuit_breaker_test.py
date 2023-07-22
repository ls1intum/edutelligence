from datetime import datetime
import pytest
from freezegun import freeze_time
from app.services.circuit_breaker import CircuitBreaker


def test_protected_call_success(mocker):
    mock_function = mocker.MagicMock(return_value=3)

    result = CircuitBreaker.protected_call(
        func=mock_function, cache_key="test_key"
    )

    mock_function.assert_called_once()
    assert result == 3


def test_protected_call_fail_with_accepted_exceptions(
    mocker, test_cache_store
):
    mock_function = mocker.MagicMock(side_effect=KeyError("foo"))

    with pytest.raises(KeyError, match="foo"):
        CircuitBreaker.protected_call(
            func=mock_function,
            cache_key="test_key",
            accepted_exceptions=(KeyError,),
        )

    assert test_cache_store.get("test_key:num_failures") is None


@freeze_time("2023-06-16 03:21:34 +02:00")
def test_protected_call_too_many_failures_not_in_a_row(
    mocker, test_cache_store
):
    initial_datetime = datetime(
        year=1, month=1, day=1, hour=15, minute=2, second=3
    )
    other_datetime = datetime(
        year=1, month=1, day=1, hour=15, minute=2, second=34
    )

    with freeze_time(initial_datetime) as frozen_datetime:
        test_cache_store.set("test_key:num_failures", 2)
        mock_function = mocker.MagicMock(side_effect=KeyError("foo"))

        with pytest.raises(KeyError, match="foo"):
            CircuitBreaker.protected_call(
                func=mock_function,
                cache_key="test_key",
            )

        frozen_datetime.move_to(other_datetime)

        # NOTE: Hazelcast doesn't expire with freezegun
        test_cache_store.delete("test_key:status")
        test_cache_store.delete("test_key:num_failures")

        with pytest.raises(KeyError, match="foo"):
            CircuitBreaker.protected_call(
                func=mock_function,
                cache_key="test_key",
            )
        assert test_cache_store.get("test_key:num_failures") == 1


def test_protected_call_too_many_failures_in_a_row(mocker, test_cache_store):
    test_cache_store.set("test_key:num_failures", 2)
    mock_function = mocker.MagicMock(side_effect=KeyError("foo"))

    with pytest.raises(KeyError, match="foo"):
        CircuitBreaker.protected_call(
            func=mock_function,
            cache_key="test_key",
        )

    with pytest.raises(
        ValueError, match="Too many failures! Please try again later."
    ):
        CircuitBreaker.protected_call(
            func=mock_function,
            cache_key="test_key",
        )

    assert test_cache_store.get("test_key:num_failures") == 3
