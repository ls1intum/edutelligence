"""Cancellable subprocess execution for the transcription pipeline."""

import subprocess  # nosec B404
from typing import List, Optional

from iris.common.cancellation import CancellationSignal
from iris.common.custom_exceptions import IngestionCancelledException
from iris.common.logging_config import get_logger

logger = get_logger(__name__)


def run_cancellable(
    command: List[str],
    timeout: Optional[int] = None,
    cancel_event: Optional[CancellationSignal] = None,
    lecture_unit_id: Optional[int] = None,
) -> subprocess.CompletedProcess:
    """Run ``command``, killing the child if ``cancel_event`` is set.

    The transcription phase spends most of its wall time inside FFmpeg and
    yt-dlp, whose timeouts run to an hour. ``subprocess.run`` would block the
    ingestion thread for that whole window, so a superseded job could not
    notice its cancellation until the download finished. This polls instead.

    Raises the same exceptions as ``subprocess.run(check=True, timeout=...)``,
    so callers keep their error handling and only gain the cancellation path.

    Raises:
        IngestionCancelledException: If cancelled before the child exited.
        subprocess.TimeoutExpired: If ``timeout`` elapsed first.
        subprocess.CalledProcessError: If the child exited non-zero.
        FileNotFoundError: If the executable is not on PATH.
    """
    with subprocess.Popen(  # nosec B603
        command,
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as process:
        # Interrupt rather than poll: cancelling kills the child directly, so
        # communicate() returns at once instead of running out its timeout.
        unregister = _kill_on_cancel(process, cancel_event)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill(process)
            raise
        finally:
            unregister()

        if cancel_event is not None and cancel_event.is_set():
            logger.info(
                "[Lecture %s] Killed %s after cancellation",
                lecture_unit_id,
                command[0],
            )
            raise IngestionCancelledException(
                lecture_unit_id, f"Cancelled during {command[0]}"
            )

        if process.returncode != 0:
            raise subprocess.CalledProcessError(
                process.returncode, command, output=stdout, stderr=stderr
            )
        return subprocess.CompletedProcess(
            command, process.returncode, stdout=stdout, stderr=stderr
        )


def _kill_on_cancel(
    process: subprocess.Popen, cancel_event: Optional[CancellationSignal]
):
    """Arrange for ``process`` to be killed the moment cancellation is signalled."""
    if cancel_event is None:
        return lambda: None
    return cancel_event.on_cancel(process.kill)


def _kill(process: subprocess.Popen) -> None:
    """Kill a child process and reap its remaining output.

    Only ever runs on a path that is already failing, so a problem here must
    not replace the error the caller is about to raise.
    """
    process.kill()
    try:
        process.communicate()
    except Exception as e:  # pragma: no cover - best effort cleanup
        logger.warning("Could not reap killed child %s: %s", process.args, e)
