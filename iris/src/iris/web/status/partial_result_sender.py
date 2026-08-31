"""Ephemeral partial-result status callback sender."""

from threading import Event, Lock, Thread
from typing import Callable, Optional

import requests

from iris.common.logging_config import get_logger
from iris.domain.status.chat_status_update_dto import ChatStatusUpdateDTO
from iris.domain.status.run_state_dto import RunStateEnum

logger = get_logger(__name__)

# A single partial POST is capped at this timeout so that a request already in
# flight when ``stop()`` is called almost always returns within the stop drain
# budget below. Partials are best-effort draft updates, so a short timeout is an
# acceptable trade-off for the tighter ordering it buys us. Note that a client
# timeout is not a strict wall-clock cap in every failure mode, so the drain is
# best-effort rather than an absolute guarantee.
PARTIAL_POST_TIMEOUT_SECONDS = 2.0

# ``stop()`` waits at most this long for the worker thread (and any in-flight
# partial POST) to finish. It MUST be strictly greater than
# ``PARTIAL_POST_TIMEOUT_SECONDS`` so that a partial POST which started just
# before ``stop()`` normally drains before ``stop()`` returns and the pipeline
# sends the authoritative final result, minimising the window in which a stale
# partial could land after the terminal callback.
STOP_DRAIN_TIMEOUT_SECONDS = 3.0


class PartialResultSender(Thread):
    """Send accumulated partial chat answers to Artemis on a fixed interval."""

    def __init__(
        self,
        url: str,
        run_id: str,
        interval_seconds: float = 0.35,
        transform: Optional[Callable[[str], str]] = None,
    ):
        """
        Args:
            transform: Applied to the accumulated draft before it is posted.
                Used to expand inline citation handles into the markers the
                client renders, and to hide a marker the model is still typing.
                Its output may change even when no new deltas arrived (a
                citation's enrichment finishing is exactly that case), so the
                de-duplication below compares transformed text.
        """
        super().__init__(daemon=True)
        self.url = url
        self.run_id = run_id
        self.interval_seconds = interval_seconds
        self._transform = transform
        self._lock = Lock()
        self._stop_event = Event()
        self._accumulated = ""
        self._epoch = 0
        self._last_posted_text = ""
        self._last_posted_epoch = -1
        self._partial_seq = 0
        self._consecutive_failures = 0
        self._stopped_permanently = False

    def on_delta(self, delta: Optional[str]) -> None:
        with self._lock:
            if self._stopped_permanently or self._stop_event.is_set():
                return
            if delta is None:
                self._accumulated = ""
                self._epoch += 1
                return
            self._accumulated += delta

    def stop(self) -> None:
        # Prevent any further partials from being queued while we drain, then
        # wait for the worker to finish. The join budget deliberately exceeds the
        # per-POST timeout so that, in the common case, a partial POST already in
        # flight has returned before we hand control back to the pipeline, which
        # sends the final result immediately after this returns. This is
        # best-effort: if the drain budget is exceeded the sender logs a warning
        # below, and Artemis's terminal-state handling (a FINISHED run state is
        # monotonic) is the backstop against a late stale partial.
        with self._lock:
            self._stopped_permanently = True
        self._stop_event.set()
        self.join(STOP_DRAIN_TIMEOUT_SECONDS)
        if self.is_alive():
            logger.warning(
                "Partial result sender did not drain within %.1fs; a stale "
                "partial may still be in flight",
                STOP_DRAIN_TIMEOUT_SECONDS,
            )

    def run(self) -> None:
        while not self._stop_event.wait(self.interval_seconds):
            payload_info = self._next_payload()
            if payload_info is None:
                continue

            payload, text, epoch = payload_info
            if self._post_payload(payload):
                self._record_success(text, epoch)

    def _next_payload(self) -> Optional[tuple[dict, str, int]]:
        with self._lock:
            if self._stopped_permanently:
                return None
            raw = self._accumulated
            epoch = self._epoch

        # Transform outside the lock: it may block briefly, and it never calls
        # back into this sender.
        text = self._transform(raw) if self._transform is not None else raw

        with self._lock:
            if self._stopped_permanently:
                return None

            # Already delivered exactly this text at this epoch -> nothing new.
            if text == self._last_posted_text and epoch == self._last_posted_epoch:
                return None

            # Empty text is only worth sending as a *clearing* partial when a
            # non-empty draft is currently visible on the client (e.g. a
            # tool-call preamble or a retried stream was posted, then reset via
            # on_delta(None); or the model has so far only written the opening
            # of a citation marker, which the transform hides). Emitting an
            # empty partialResult with a higher
            # partialSeq tells Artemis to wipe that stale draft. We suppress the
            # initial empty state and duplicate consecutive empty resets so we
            # do not spam Artemis with redundant clears.
            if not text and not self._last_posted_text:
                return None

            self._partial_seq += 1
            payload = ChatStatusUpdateDTO(
                run_state=RunStateEnum.RUNNING,
                partial_result=text,
                partial_seq=self._partial_seq,
            ).model_dump(by_alias=True, exclude_none=True)
            return payload, text, epoch

    def _post_payload(self, payload: dict) -> bool:
        try:
            response = requests.post(
                self.url,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.run_id}",
                },
                json=payload,
                timeout=PARTIAL_POST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            self._consecutive_failures = 0
            return True
        except requests.exceptions.RequestException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            self._handle_failure(status_code, exc)
            return False
        except Exception as exc:  # pragma: no cover - defensive thread boundary
            self._handle_failure(None, exc)
            return False

    def _record_success(self, text: str, epoch: int) -> None:
        # Record what was actually delivered to the client, regardless of the
        # current epoch. A POST that started before an on_delta(None) reset still
        # reaches Artemis and stays visible, so ``_last_posted_text`` must reflect
        # it; otherwise the subsequent clearing partial would be suppressed as
        # "no draft visible" (see _next_payload) and the stale draft would linger.
        with self._lock:
            self._last_posted_text = text
            self._last_posted_epoch = epoch

    def _handle_failure(self, status_code: Optional[int], exc: Exception) -> None:
        if status_code in (401, 403, 404):
            logger.info(
                "Stopping partial result sender after status %s from %s",
                status_code,
                self.url,
            )
            self._stop_permanently()
            return

        self._consecutive_failures += 1
        if self._consecutive_failures >= 5:
            logger.warning(
                "Stopping partial result sender after %d consecutive failures: %s",
                self._consecutive_failures,
                exc,
            )
            self._stop_permanently()
        else:
            logger.info("Partial result sender failed: %s", exc)

    def _stop_permanently(self) -> None:
        with self._lock:
            self._stopped_permanently = True
        self._stop_event.set()
