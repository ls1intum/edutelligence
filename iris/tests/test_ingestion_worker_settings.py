import pytest
from pydantic import ValidationError

from iris.config import IngestionWorkerSettings


def test_defaults_are_valid():
    settings = IngestionWorkerSettings()
    assert settings.capacity == 2
    assert settings.poll_interval_seconds == 2.0
    assert settings.heartbeat_interval_seconds == 5.0
    assert settings.heartbeat_timeout_seconds == 10.0


def test_capacity_rejects_zero():
    # Zero free capacity means the worker never claims work, while its poll and
    # heartbeat loops keep running and keep Artemis in pull mode indefinitely.
    with pytest.raises(ValidationError):
        IngestionWorkerSettings(capacity=0)


def test_capacity_rejects_negative():
    with pytest.raises(ValidationError):
        IngestionWorkerSettings(capacity=-1)


def test_poll_interval_seconds_rejects_zero():
    # threading.Event.wait() with a non-positive timeout returns immediately,
    # turning the poll loop into a tight request loop.
    with pytest.raises(ValidationError):
        IngestionWorkerSettings(poll_interval_seconds=0)


def test_poll_interval_seconds_rejects_negative():
    with pytest.raises(ValidationError):
        IngestionWorkerSettings(poll_interval_seconds=-1.0)


def test_heartbeat_interval_seconds_rejects_zero():
    with pytest.raises(ValidationError):
        IngestionWorkerSettings(heartbeat_interval_seconds=0)


def test_heartbeat_interval_seconds_rejects_negative():
    with pytest.raises(ValidationError):
        IngestionWorkerSettings(heartbeat_interval_seconds=-1.0)


def test_heartbeat_timeout_seconds_rejects_zero():
    with pytest.raises(ValidationError):
        IngestionWorkerSettings(heartbeat_timeout_seconds=0)


def test_heartbeat_timeout_seconds_rejects_more_than_the_claim_timeout():
    # Claims keep 30 s; a heartbeat that may hang longer than that defeats its purpose.
    with pytest.raises(ValidationError):
        IngestionWorkerSettings(heartbeat_timeout_seconds=31)


def test_heartbeat_timeout_seconds_accepts_the_upper_bound():
    assert (
        IngestionWorkerSettings(heartbeat_timeout_seconds=30).heartbeat_timeout_seconds
        == 30
    )
