import pytest
from pydantic import ValidationError

from iris.config import IngestionWorkerSettings


def test_defaults_are_valid():
    settings = IngestionWorkerSettings()
    assert settings.capacity == 2
    assert settings.poll_interval_seconds == 2.0
    assert settings.heartbeat_interval_seconds == 5.0


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
