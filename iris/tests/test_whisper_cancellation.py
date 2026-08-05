"""Whisper distinguishes job cancellation from chunk failure.

``abort_event`` means a sibling chunk failed and the run has genuinely failed;
``cancel_event`` means the job was superseded and nothing failed. Aliasing them
would report a cancelled job as a transcription failure, and a Whisper error as
a cancellation.
"""

import threading
import time

import pytest

from iris.common.cancellation import CancellationSignal
from iris.common.custom_exceptions import IngestionCancelledException
from iris.pipeline.shared.transcription.whisper_client import (
    WhisperClient,
    _sleep_unless_stopped,
)


def _client(tmp_path):
    """Build a client without touching llm_config.yml."""
    client = WhisperClient.__new__(WhisperClient)
    client.max_retries = 3
    client.request_timeout = 5
    client.no_speech_threshold = 0.8
    client.split_timeout = 3600
    client.provider_name = "OpenAI"
    # pylint: disable=protected-access
    client._get_request_params = lambda: (  # type: ignore[method-assign]
        "https://api.openai.example/v1/audio/transcriptions",
        {},
        {},
    )
    chunk = tmp_path / "chunk_000.mp3"
    chunk.write_bytes(b"\x00")
    return client, str(chunk)


def test_chunk_failure_does_not_set_the_job_cancellation_event(tmp_path):
    """The job-level event stays clear when only a chunk aborted."""
    client, chunk = _client(tmp_path)
    abort_event = threading.Event()
    abort_event.set()
    cancel_event = threading.Event()

    with pytest.raises(InterruptedError):
        client._transcribe_chunk(  # pylint: disable=protected-access
            chunk,
            0,
            1,
            7,
            abort_event,
            cancel_event,
        )

    assert not cancel_event.is_set()


def test_backoff_returns_early_when_the_run_stops():
    """Azure backoff reaches 180s; a stopped run must not sleep through it."""
    stop_event = threading.Event()
    threading.Timer(0.05, stop_event.set).start()

    started = time.monotonic()
    _sleep_unless_stopped(180, stop_event)
    assert time.monotonic() - started < 5


def test_cancellation_does_not_wait_for_an_uninterruptible_upload(
    tmp_path, monkeypatch
):
    """A superseded job must not be held by an in-flight Whisper request.

    A ``requests`` call already blocked on the socket cannot be interrupted —
    it runs to its timeout regardless — so the pool is abandoned rather than
    joined. Verified separately: ``Session.close()`` does not abort it.
    """
    client, chunk = _client(tmp_path)
    client.chunk_duration = 900
    client.max_workers = 2

    cancel_event = CancellationSignal()
    upload_started = threading.Event()

    def stuck_upload(*_args, **_kwargs):
        upload_started.set()
        time.sleep(30)  # stands in for the request timeout
        raise AssertionError("upload should have been abandoned")

    monkeypatch.setattr(
        "iris.pipeline.shared.transcription.whisper_client.split_audio_ffmpeg",
        lambda *a, **kw: [chunk, chunk],
    )
    monkeypatch.setattr(
        "iris.pipeline.shared.transcription.whisper_client._audio_duration",
        lambda _p: 1.0,
    )
    monkeypatch.setattr(client, "_transcribe_chunk", stuck_upload)

    threading.Timer(0.3, cancel_event.set).start()

    started = time.monotonic()
    with pytest.raises(IngestionCancelledException):
        client.transcribe(chunk, lecture_unit_id=7, cancel_event=cancel_event)
    elapsed = time.monotonic() - started

    assert upload_started.is_set(), "test did not exercise an in-flight upload"
    assert elapsed < 10, f"cancellation waited {elapsed:.1f}s for the stuck upload"
