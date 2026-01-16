# pylint: disable=redefined-outer-name,unused-argument,missing-class-docstring,import-outside-toplevel
import asyncio
import os
import tempfile

import pytest

# Set required env vars BEFORE importing modules to prevent RuntimeError
os.environ.setdefault("NEBULA_TEMP_DIR", tempfile.gettempdir())
os.environ.setdefault("LLM_CONFIG_PATH", "/tmp/test_llm_config.yml")

from nebula.transcript import transcriber_config  # noqa: E402


@pytest.fixture(autouse=True)
def temp_video_storage(monkeypatch):
    """Override VIDEO_STORAGE_PATH with a fresh temp directory per test."""
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
