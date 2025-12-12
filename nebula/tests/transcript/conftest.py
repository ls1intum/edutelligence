# pylint: disable=redefined-outer-name,unused-argument,missing-class-docstring,import-outside-toplevel
import asyncio
import tempfile

import pytest

from nebula.transcript import transcriber_config


@pytest.fixture(autouse=True)
def temp_video_storage(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr(
            transcriber_config, "VIDEO_STORAGE_PATH", tmp, raising=False
        )
        yield


@pytest.fixture
def anyio_backend():
    # Ensure pytest-asyncio/anyio play nicely
    return "asyncio"


@pytest.fixture
def event_loop():
    # A fresh loop per test file to avoid crosstalk
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
