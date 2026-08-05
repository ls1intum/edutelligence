"""Preemption of the long-blocking children in the transcription phase.

FFmpeg/yt-dlp run with timeouts of up to an hour. ``subprocess.run`` would
block the ingestion thread for that whole window, so a superseded job could not
notice its cancellation until the download finished.
"""

import subprocess
import sys
import time
from threading import Timer

import pytest

from iris.common.cancellation import CancellationSignal
from iris.common.custom_exceptions import IngestionCancelledException
from iris.pipeline.shared.transcription.subprocess_utils import run_cancellable

# A child that outlives any test timeout unless it is killed.
_SLEEP_FOREVER = [sys.executable, "-c", "import time; time.sleep(300)"]


def test_nonzero_exit_raises_called_process_error():
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        run_cancellable(
            [sys.executable, "-c", "import sys; sys.stderr.write('bad'); sys.exit(3)"],
            timeout=30,
        )
    assert excinfo.value.returncode == 3
    assert "bad" in excinfo.value.stderr


def test_timeout_raises_timeout_expired_with_caller_timeout():
    with pytest.raises(subprocess.TimeoutExpired) as excinfo:
        run_cancellable(_SLEEP_FOREVER, timeout=1)
    # The reported timeout must be the caller's budget, not the poll interval,
    # since callers put it in the error they surface to Artemis.
    assert excinfo.value.timeout == 1


def test_cancellation_kills_the_child_promptly():
    """The point of the exercise: an hour-long child dies in well under a second."""
    cancel_event = CancellationSignal()
    Timer(0.1, cancel_event.set).start()

    started = time.monotonic()
    with pytest.raises(IngestionCancelledException):
        # A one-hour budget, matching the real download timeout.
        run_cancellable(_SLEEP_FOREVER, timeout=3600, cancel_event=cancel_event)
    elapsed = time.monotonic() - started

    assert elapsed < 5, f"cancellation took {elapsed:.1f}s"
