"""Ephemeral partial-result status callback sender."""

from threading import Event, Lock, Thread
from typing import Optional

import requests

from iris.common.logging_config import get_logger
from iris.domain.status.chat_status_update_dto import ChatStatusUpdateDTO
from iris.domain.status.stage_dto import StageDTO

logger = get_logger(__name__)


class PartialResultSender(Thread):
    """Send accumulated partial chat answers to Artemis on a fixed interval."""

    def __init__(
        self,
        url: str,
        run_id: str,
        stages_snapshot: list[StageDTO],
        interval_seconds: float = 0.35,
    ):
        super().__init__(daemon=True)
        self.url = url
        self.run_id = run_id
        self.stages_snapshot = [
            stage.model_copy(deep=True) for stage in stages_snapshot
        ]
        self.interval_seconds = interval_seconds
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
        self._stop_event.set()
        self.join(2)
        if self.is_alive():
            logger.warning("Partial result sender did not stop within 2 seconds")

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
            if not self._accumulated:
                return None
            if (
                self._accumulated == self._last_posted_text
                and self._epoch == self._last_posted_epoch
            ):
                return None

            self._partial_seq += 1
            text = self._accumulated
            epoch = self._epoch
            payload = ChatStatusUpdateDTO(
                stages=self.stages_snapshot,
                partial_result=text,
                partial_seq=self._partial_seq,
            ).model_dump(by_alias=True)
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
                timeout=10,
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
        with self._lock:
            if epoch == self._epoch:
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
