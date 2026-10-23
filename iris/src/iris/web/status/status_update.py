import time
from concurrent.futures import Future
from enum import Enum
from threading import Lock
from typing import Any, Optional

import requests
from sentry_sdk import capture_exception, capture_message

from iris.common.logging_config import get_logger
from iris.common.token_usage_dto import TokenUsageDTO
from iris.domain.autonomous_tutor.autonomous_tutor_pipeline_status_update_dto import (
    AutonomousTutorPipelineStatusUpdateDTO,
)
from iris.domain.communication.communication_tutor_suggestion_status_update_dto import (
    TutorSuggestionStatusUpdateDTO,
)
from iris.domain.status.activity_dto import ActivityDTO
from iris.domain.status.chat_status_update_dto import ChatStatusUpdateDTO
from iris.domain.status.command_dto import CommandDTO
from iris.domain.status.command_result_dto import CommandResultDTO
from iris.domain.status.competency_extraction_status_update_dto import (
    CompetencyExtractionStatusUpdateDTO,
)
from iris.domain.status.global_search_status_update_dto import (
    GlobalSearchStatusUpdateDTO,
)
from iris.domain.status.inconsistency_check_status_update_dto import (
    InconsistencyCheckStatusUpdateDTO,
)
from iris.domain.status.rewriting_status_update_dto import (
    RewritingStatusUpdateDTO,
)
from iris.domain.status.run_state_dto import RunStateEnum, StatusErrorDTO
from iris.domain.status.status_update_dto import StatusUpdateDTO
from iris.domain.status.struggle_intervention_status_update_dto import (
    StruggleInterventionStatusUpdateDTO,
)
from iris.tracing import TracedThreadPoolExecutor

logger = get_logger(__name__)

# How long to wait for Artemis to carry out a command on the client and reply. Must exceed the
# Artemis-side client-ack timeout (5s) plus the HTTP round trip, so a slow client surfaces as
# "not applied" rather than a transport error. Lower this only after Artemis' own timeout has been
# lowered and deployed — the other order makes Iris give up while an answer is still on its way.
COMMAND_TIMEOUT_SECONDS = 10

# The watchdog's own terminal sends must finish quickly: it closes runs whose pipeline thread is
# stuck, often many at once, and Artemis drops a job 300 s after its last status anyway.
WATCHDOG_POST_TIMEOUT_SECONDS = 10
WATCHDOG_POST_ATTEMPTS = 2


class RunPhase(str, Enum):
    """Where a run stands towards Artemis. Changes only forward, under the update lock."""

    RUNNING = "running"
    # The final answer is being or has been sent; only a FINISHED may follow.
    ANSWER_SENDING = "answer_sending"
    TERMINAL = "terminal"


class StatusCallback:
    """A callback class for sending run-state status updates to Artemis."""

    api_url: str = "api/iris/internal/pipelines"

    # Result-like payload fields that describe a single RUNNING update and must
    # NOT leak into later heartbeats or the terminal send. ``result`` carries
    # e.g. transcription checkpoint JSON; ``display_page_numbers`` is attached
    # only to the send that produced it. ``stage``/``stage_sources`` (global
    # search) name the pipeline phase THIS update crossed into — without
    # clearing them, the terminal finish()/fail() send (which does not pass
    # its own stage) still carries the last RUNNING update's stage name (e.g.
    # "generating"), contradicting the FINISHED/FAILED run state it is sent
    # with. Persistent fields (run_state, error, tokens, activities, and
    # identity fields such as the lecture-unit id) are intentionally excluded
    # so they keep accumulating across updates. A name absent from a given
    # status DTO subtype is a harmless no-op (see _clear_transient_result_fields).
    _TRANSIENT_RESULT_FIELDS: tuple[str, ...] = (
        "result",
        "display_page_numbers",
        "stage",
        "stage_sources",
    )

    # Backoff between retries of a delivery-critical frame, in seconds.
    _RETRY_BACKOFF_S: tuple[int, ...] = (1, 2, 4)

    def _send_payload_with_backoff(
        self, payload: dict[str, Any], attempts: int
    ) -> bool:
        """Send a payload, retrying up to ``attempts`` times with backoff.

        A frame Artemis must not lose (the chat answer, a terminal decision) is worth a second and a
        third try; everything else is sent once, because a heartbeat that fails is superseded by the
        next one anyway and retrying it only delays the pipeline.
        """
        for attempt in range(attempts):
            if self._send_status_payload(payload):
                return True
            if attempt < attempts - 1:
                time.sleep(
                    self._RETRY_BACKOFF_S[min(attempt, len(self._RETRY_BACKOFF_S) - 1)]
                )
        return False

    def __init__(self, url: str, run_id: str, status: StatusUpdateDTO):
        self.url = url
        self.run_id = run_id
        self.status = status
        self._phase = RunPhase.RUNNING
        self._closed_by_watchdog = False
        self._answer_sent_at: Optional[float] = None
        self._answer_post_in_flight = False
        self._last_frame_at = time.perf_counter()
        self._running_update_executor: Optional[TracedThreadPoolExecutor] = None
        self._running_update_futures: list[Future] = []
        self._running_update_lock = Lock()

    def _serialize_status(self) -> dict[str, Any]:
        """Serialize the current status for the Artemis wire format."""
        return self.status.model_dump(by_alias=True)

    def _post_status_payload(
        self, payload: dict[str, Any], timeout: int = 200
    ) -> requests.Response:
        """Send a pre-serialized status payload to Artemis."""
        return requests.post(
            self.url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.run_id}",
            },
            json=payload,
            timeout=timeout,
        )

    def _send_status_payload(
        self, payload: dict[str, Any], *, async_running_update: bool = False
    ) -> bool:
        """Send a status payload and log timing for every attempted POST."""
        post_start = time.perf_counter()
        try:
            resp = self._post_status_payload(payload)
            logger.info(
                "Status callback to %s returned %d | duration_ms=%.0f",
                self.url,
                resp.status_code,
                (time.perf_counter() - post_start) * 1000,
            )
            resp.raise_for_status()
            self._last_frame_at = time.perf_counter()
            return True
        except requests.exceptions.RequestException as e:
            duration_ms = (time.perf_counter() - post_start) * 1000
            if async_running_update:
                logger.warning(
                    "Async status update failed: %s | duration_ms=%.0f",
                    e,
                    duration_ms,
                )
            else:
                logger.error(
                    "Error sending status update: %s | duration_ms=%.0f",
                    e,
                    duration_ms,
                )
                capture_exception(e)
            return False

    def _get_running_update_executor(self) -> TracedThreadPoolExecutor:
        """Create the FIFO async sender lazily for running updates."""
        with self._running_update_lock:
            return self._get_running_update_executor_locked()

    def _get_running_update_executor_locked(self) -> TracedThreadPoolExecutor:
        """Create the FIFO async sender while holding the update lock."""
        if self._running_update_executor is None:
            self._running_update_executor = TracedThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="StatusCallback",
            )
        return self._running_update_executor

    def _shutdown_running_update_executor(self, cancel_queued: bool = False) -> None:
        """Stop the async running-update executor after terminal delivery."""
        with self._running_update_lock:
            executor = self._running_update_executor
            self._running_update_executor = None
        if executor is None:
            return
        if cancel_queued:
            executor.shutdown(wait=False, cancel_futures=True)
        else:
            executor.shutdown(wait=False)

    @property
    def _terminal_sent(self) -> bool:
        return self._phase is RunPhase.TERMINAL

    @property
    def phase(self) -> RunPhase:
        return self._phase

    @property
    def closed_by_watchdog(self) -> bool:
        return self._closed_by_watchdog

    @property
    def answer_sent_at(self) -> Optional[float]:
        """``time.perf_counter()`` when the final answer send started, if it did."""
        return self._answer_sent_at

    @property
    def answer_post_in_flight(self) -> bool:
        return self._answer_post_in_flight

    def seconds_since_last_frame(self, now: float) -> float:
        return now - self._last_frame_at

    def _claim_terminal(self, *, by_watchdog: bool = False) -> bool:
        """Move to TERMINAL unless another send got there first; True if this call did."""
        with self._running_update_lock:
            if self._phase is RunPhase.TERMINAL:
                return False
            self._phase = RunPhase.TERMINAL
            self._closed_by_watchdog = by_watchdog
            return True

    def _enter_answer_sending(self) -> bool:
        """Mark that the final answer is on its way; False once the run is terminal."""
        with self._running_update_lock:
            if self._phase is RunPhase.TERMINAL:
                return False
            if self._phase is RunPhase.RUNNING:
                self._phase = RunPhase.ANSWER_SENDING
                self._answer_sent_at = time.perf_counter()
            return True

    def watchdog_fail(self, message: str, code: str) -> bool:
        """FAILED from the watchdog: only while no answer has been sent, bounded in time."""
        with self._running_update_lock:
            if self._phase is not RunPhase.RUNNING:
                return False
            self._phase = RunPhase.TERMINAL
            self._closed_by_watchdog = True
        error = StatusErrorDTO(message=message, code=code)
        return self._send_watchdog_terminal(
            self._watchdog_payload(RunStateEnum.FAILED, error)
        )

    def watchdog_finish(self) -> bool:
        """FINISHED from the watchdog for a run whose answer went out but that never ended.

        Not while the answer POST is still in flight: Artemis would remove the job and then
        reject the answer.
        """
        with self._running_update_lock:
            if (
                self._phase is not RunPhase.ANSWER_SENDING
                or self._answer_post_in_flight
            ):
                return False
            self._phase = RunPhase.TERMINAL
            self._closed_by_watchdog = True
        return self._send_watchdog_terminal(
            self._watchdog_payload(RunStateEnum.FINISHED, None)
        )

    def watchdog_heartbeat(self) -> bool:
        """Queue a bare RUNNING frame, which keeps the Artemis job alive.

        Gives up instead of waiting when the update lock is busy, so the watchdog never blocks.
        """
        if not self._running_update_lock.acquire(timeout=1):
            return False
        try:
            if self._phase is not RunPhase.RUNNING:
                return False
            self._last_frame_at = time.perf_counter()
            future = self._get_running_update_executor_locked().submit(
                self._send_status_payload,
                {"runState": RunStateEnum.RUNNING.value},
                async_running_update=True,
            )
            self._running_update_futures.append(future)
            return True
        finally:
            self._running_update_lock.release()

    def _watchdog_payload(
        self, run_state: RunStateEnum, error: Optional[StatusErrorDTO]
    ) -> dict[str, Any]:
        # A copy: the stuck pipeline thread still owns self.status.
        return self.status.model_copy(
            update={"run_state": run_state, "error": error}
        ).model_dump(by_alias=True)

    def _send_watchdog_terminal(self, payload: dict[str, Any]) -> bool:
        try:
            for attempt in range(WATCHDOG_POST_ATTEMPTS):
                try:
                    resp = self._post_status_payload(
                        payload, timeout=WATCHDOG_POST_TIMEOUT_SECONDS
                    )
                    resp.raise_for_status()
                    return True
                except requests.exceptions.RequestException as e:
                    logger.warning(
                        "Watchdog status send failed (attempt %d): %s", attempt + 1, e
                    )
                    if attempt < WATCHDOG_POST_ATTEMPTS - 1:
                        time.sleep(1)
            return False
        finally:
            # Frames still queued would only arrive after the terminal one.
            self._shutdown_running_update_executor(cancel_queued=True)

    def _enqueue_running_update(self, payload: Optional[dict[str, Any]] = None) -> None:
        """Queue a running status update without blocking the pipeline."""
        queued_payload = payload if payload is not None else self._serialize_status()
        with self._running_update_lock:
            if self._terminal_sent:
                # Expected race: a tracker emit paused between snapshot and enqueue
                # can land after the terminal send; the authoritative snapshot on
                # the terminal payload already superseded it (spec guard c).
                logger.debug("Dropping async status update after terminal send")
                return
            future = self._get_running_update_executor_locked().submit(
                self._send_status_payload,
                queued_payload,
                async_running_update=True,
            )
            self._running_update_futures.append(future)

    def _drain_running_updates(self) -> None:
        """Wait for all queued running updates before sync sends."""
        while True:
            with self._running_update_lock:
                futures = self._running_update_futures
                self._running_update_futures = []
            if not futures:
                return
            for future in futures:
                try:
                    future.result()
                except Exception as e:  # pragma: no cover - worker logs expected errors
                    logger.warning("Async status update failed: %s", e)

    def on_status_update(self) -> bool:
        """Send the current status to the Artemis API."""
        return self._send_status_payload(self._serialize_status())

    def update(self, **fields) -> bool:
        """Synchronously post a RUNNING status update."""
        if self._terminal_sent:
            self._reject_after_terminal("update")
            return False
        self.status.run_state = RunStateEnum.RUNNING
        self.status.error = None
        self._apply_fields(fields)
        self._drain_running_updates()
        success = self.on_status_update()
        # Only clear transient fields once the update was actually delivered.
        # If the POST failed, keep them so the payload is retried on the next
        # update instead of being silently dropped.
        if success:
            self._clear_transient_result_fields()
        return success

    def _clear_transient_result_fields(self) -> None:
        """Reset transient result-like fields on the reusable status DTO.

        Called after a successful non-terminal update so a per-update payload
        (e.g. a transcription checkpoint) is not re-sent by every later
        heartbeat or by the terminal ``finish``.
        """
        status_fields = type(self.status).model_fields
        for name in self._TRANSIENT_RESULT_FIELDS:
            field = status_fields.get(name)
            if field is not None:
                setattr(
                    self.status,
                    name,
                    field.get_default(call_default_factory=True),
                )

    def finish(self, **fields) -> bool:
        """Synchronously post a FINISHED terminal status update."""
        if not self._claim_terminal():
            self._reject_after_terminal("finish")
            return False
        self.status.run_state = RunStateEnum.FINISHED
        self.status.error = None
        self._apply_fields(fields)
        self._drain_running_updates()
        try:
            return self.on_status_update()
        finally:
            self._shutdown_running_update_executor()

    def fail(
        self,
        message=None,
        code=None,
        tokens: Optional[list[TokenUsageDTO]] = None,
        **fields,
    ) -> bool:
        """Synchronously post a FAILED terminal status update."""
        if not self._claim_terminal():
            self._reject_after_terminal("fail")
            return False
        self.status.run_state = RunStateEnum.FAILED
        self.status.error = StatusErrorDTO(message=message, code=code)
        if tokens is not None:
            self.status.tokens = tokens
        self._apply_fields(fields)
        self._drain_running_updates()
        try:
            success = self.on_status_update()
        finally:
            self._shutdown_running_update_executor()
        exception = fields.get("exception")
        if exception:
            capture_exception(exception)
        elif message:
            capture_message(f"Error occurred in job {self.run_id}: {message}")
        return success

    def _apply_fields(self, fields: dict[str, Any]) -> None:
        for field, value in fields.items():
            if field in type(self.status).model_fields:
                setattr(self.status, field, value)

    def _reject_after_terminal(self, operation: str) -> None:
        message = (
            f"Rejected status {operation} for run {self.run_id} after terminal update"
        )
        if self._closed_by_watchdog:
            # Expected: the watchdog closed a run whose pipeline thread came back later.
            logger.info("%s (closed by the watchdog)", message)
            return
        logger.warning(message)
        capture_message(message)

    def execute_command(self, command: CommandDTO) -> CommandResultDTO:
        """Synchronously ask Artemis to carry out a command on the client (e.g. a point-out) and
        return whether it was applied.

        Blocks until Artemis has driven the client and replied, so the agent tool learns the real
        outcome before formulating its answer. Any transport failure or timeout is treated as
        "not applied" so the pipeline never hangs on a command.

        Args:
            command: The command Artemis should carry out.

        Returns:
            The result reported by Artemis (``applied``).
        """
        # The command endpoint is the sibling of the status endpoint (…/runs/{runId}/command).
        # Guard the derivation so a callback URL that unexpectedly lacks "/status" surfaces as
        # "not applied" instead of silently POSTing to a wrong URL.
        if "/status" not in self.url:
            logger.warning(
                "Cannot derive command URL from callback URL without a '/status' suffix; "
                "treating the command as not applied."
            )
            return CommandResultDTO(applied=False)
        command_url = self.url.rsplit("/status", 1)[0] + "/command"
        try:
            resp = requests.post(
                command_url,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.run_id}",
                },
                json=command.model_dump(by_alias=True, exclude_none=True),
                timeout=COMMAND_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            return CommandResultDTO.model_validate(resp.json())
        except Exception as e:
            # Refused connection, read timeout, error status, unparseable body: all mean the command
            # did not happen, and the agent is told that rather than the pipeline breaking over it.
            # All are reported, because none is an ordinary result — Artemis' client-ack timeout sits
            # below ours, so a command the client ignored arrives as a valid ``applied: false`` and
            # never reaches this handler. Anything that does means the call itself went wrong.
            logger.warning("Iris command could not be executed by Artemis: %s", e)
            capture_exception(e)
            return CommandResultDTO(applied=False)


class ChatRunCallback(StatusCallback):
    """Chat status callback with delivery-critical answer handling."""

    # Number of attempts (with backoff) used for delivery-critical sends: the
    # answer-bearing ``send_result`` and any terminal send that still carries a
    # previously undelivered answer forward.
    _DELIVERY_RETRY_ATTEMPTS = 3

    def __init__(
        self,
        run_id: str,
        base_url: str,
        initial_state_unused_removed=None,
        **_kwargs,
    ):
        del initial_state_unused_removed
        url = f"{base_url}/{self.api_url}/chat/runs/{run_id}/status"
        super().__init__(
            url, run_id, ChatStatusUpdateDTO(run_state=RunStateEnum.RUNNING)
        )
        self._undelivered_result_fields: Optional[dict[str, Any]] = None
        # Usage already handed to Artemis. Callers pass their whole running token list on
        # every send, but Artemis adds each send's tokens to the trace, so each usage
        # object must be delivered exactly once.
        self._delivered_tokens: list[TokenUsageDTO] = []

    def activity_snapshot(self, activities: list[ActivityDTO], seq: int) -> None:
        payload = self._payload(
            run_state=RunStateEnum.RUNNING,
            activities=activities,
            activity_seq=seq,
        )
        self._enqueue_running_update(payload)

    def send_result(
        self,
        final_result,
        tokens=None,
        activities=None,
        activity_seq=None,
        suggested_context=None,
    ) -> bool:
        fields = {
            "result": final_result,
            "final": True,
            "tokens": tokens or [],
        }
        if activities is not None:
            fields["activities"] = activities
        if activity_seq is not None:
            fields["activity_seq"] = activity_seq
        if suggested_context is not None:
            fields["suggested_context"] = suggested_context

        if not self._enter_answer_sending():
            self._reject_after_terminal("result")
            return False
        self._answer_post_in_flight = True
        success = False
        try:
            success = self._send_chat_fields(
                fields, attempts=self._DELIVERY_RETRY_ATTEMPTS
            )
        finally:
            # Under the lock watchdog_finish() checks: it must never see the POST as done
            # before an undelivered answer is recorded, or it would finish without it.
            with self._running_update_lock:
                if not success:
                    self._undelivered_result_fields = fields
                self._answer_post_in_flight = False
        return success

    def send_intermediate(
        self,
        text,
        activities=None,
        activity_seq=None,
    ) -> bool:
        """Synchronously post a non-critical intermediate assistant message."""
        if self._terminal_sent:
            self._reject_after_terminal("send_intermediate")
            return False

        fields: dict[str, Any] = {
            "result": text,
            "final": False,
        }
        if activities is not None:
            fields["activities"] = activities
        if activity_seq is not None:
            fields["activity_seq"] = activity_seq

        payload = self._payload(run_state=RunStateEnum.RUNNING, **fields)
        self._drain_running_updates()
        return self._send_status_payload(payload)

    def send_suggestions(self, suggestions, session_title=None) -> bool:
        fields: dict[str, Any] = {"suggestions": suggestions}
        if session_title is not None:
            fields["session_title"] = session_title
        return self._send_chat_fields(fields)

    def finish(
        self,
        session_title=None,
        tokens=None,
        activities=None,
        activity_seq=None,
        compaction=None,
    ) -> bool:
        fields: dict[str, Any] = {}
        if session_title is not None:
            fields["session_title"] = session_title
        if tokens is not None:
            fields["tokens"] = tokens
        if activities is not None:
            fields["activities"] = activities
        if activity_seq is not None:
            fields["activity_seq"] = activity_seq
        if compaction is not None:
            fields["compaction"] = compaction
        return self._send_chat_fields(fields, run_state=RunStateEnum.FINISHED)

    def fail(
        self,
        message=None,
        code=None,
        tokens=None,
        session_title=None,
        activities=None,
        activity_seq=None,
        exception=None,
        compaction=None,
    ) -> bool:
        fields: dict[str, Any] = {}
        if tokens is not None:
            fields["tokens"] = tokens
        if session_title is not None:
            fields["session_title"] = session_title
        if compaction is not None:
            fields["compaction"] = compaction
        if activities is not None:
            fields["activities"] = activities
        if activity_seq is not None:
            fields["activity_seq"] = activity_seq
        success = self._send_chat_fields(
            fields,
            run_state=RunStateEnum.FAILED,
            error=StatusErrorDTO(message=message, code=code),
        )
        if exception:
            capture_exception(exception)
        elif message:
            capture_message(f"Error occurred in job {self.run_id}: {message}")
        return success

    def _send_chat_fields(
        self,
        fields: dict[str, Any],
        run_state: RunStateEnum = RunStateEnum.RUNNING,
        error: Optional[StatusErrorDTO] = None,
        attempts: int = 1,
    ) -> bool:
        terminal_send = run_state != RunStateEnum.RUNNING
        if terminal_send:
            if not self._claim_terminal():
                self._reject_after_terminal(run_state.value.lower())
                return False
        elif self._terminal_sent:
            self._reject_after_terminal(run_state.value.lower())
            return False

        fields, carried_result = self._merge_undelivered_result(fields)
        new_tokens: list[TokenUsageDTO] = []
        if "tokens" in fields:
            new_tokens = self._undelivered_tokens(fields["tokens"])
            fields = {**fields, "tokens": new_tokens}

        # A terminal send is the LAST chance to deliver an answer that a prior
        # send_result() failed to hand off. Give it the same retry/backoff so a
        # transient failure there does not drop the delivery-critical answer.
        # Terminal sends without a carried result stay single-shot to avoid
        # slowing the common (already-delivered) path.
        if carried_result and run_state != RunStateEnum.RUNNING:
            attempts = max(attempts, self._DELIVERY_RETRY_ATTEMPTS)

        payload = self._payload(run_state=run_state, error=error, **fields)

        self._drain_running_updates()

        try:
            for attempt in range(attempts):
                if self._send_status_payload(payload):
                    if carried_result:
                        self._undelivered_result_fields = None
                    self._delivered_tokens.extend(new_tokens)
                    return True
                if attempt < attempts - 1:
                    time.sleep((1, 2, 4)[attempt])
            return False
        finally:
            if terminal_send:
                self._shutdown_running_update_executor()

    def _undelivered_tokens(
        self, tokens: Optional[list[TokenUsageDTO]]
    ) -> list[TokenUsageDTO]:
        return [
            token
            for token in tokens or []
            if not any(token is delivered for delivered in self._delivered_tokens)
        ]

    def _merge_undelivered_result(
        self, fields: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        if self._undelivered_result_fields is None:
            return fields, False
        return {**self._undelivered_result_fields, **fields}, True

    def _watchdog_payload(
        self, run_state: RunStateEnum, error: Optional[StatusErrorDTO]
    ) -> dict[str, Any]:
        fields, _ = self._merge_undelivered_result({})
        return self._payload(run_state=run_state, error=error, **fields)

    @staticmethod
    def _payload(
        run_state: RunStateEnum,
        error: Optional[StatusErrorDTO] = None,
        **fields,
    ) -> dict[str, Any]:
        return ChatStatusUpdateDTO(
            run_state=run_state,
            error=error,
            **fields,
        ).model_dump(by_alias=True)


class CompetencyExtractionCallback(StatusCallback):
    """Status callback for competency extraction pipelines."""

    def __init__(self, run_id: str, base_url: str):
        url = f"{base_url}/{self.api_url}/competency-extraction/runs/{run_id}/status"
        super().__init__(
            url,
            run_id,
            CompetencyExtractionStatusUpdateDTO(run_state=RunStateEnum.RUNNING),
        )


class RewritingCallback(StatusCallback):
    """Status callback for rewriting pipelines."""

    def __init__(self, run_id: str, base_url: str):
        url = f"{base_url}/{self.api_url}/rewriting/runs/{run_id}/status"
        super().__init__(
            url, run_id, RewritingStatusUpdateDTO(run_state=RunStateEnum.RUNNING)
        )


class InconsistencyCheckCallback(StatusCallback):
    """Status callback for inconsistency check pipelines."""

    def __init__(self, run_id: str, base_url: str):
        url = f"{base_url}/{self.api_url}/inconsistency-check/runs/{run_id}/status"
        super().__init__(
            url,
            run_id,
            InconsistencyCheckStatusUpdateDTO(run_state=RunStateEnum.RUNNING),
        )


class TutorSuggestionCallback(StatusCallback):
    """Status callback for tutor suggestion pipelines."""

    def __init__(self, run_id: str, base_url: str):
        url = f"{base_url}/{self.api_url}/tutor-suggestion/runs/{run_id}/status"
        super().__init__(
            url,
            run_id,
            TutorSuggestionStatusUpdateDTO(run_state=RunStateEnum.RUNNING),
        )


class GlobalSearchCallback(StatusCallback):
    """Status callback for the global search pipeline."""

    def __init__(self, run_id: str, base_url: str):
        url = f"{base_url}/{self.api_url}/global-search/runs/{run_id}/status"
        super().__init__(
            url,
            run_id,
            GlobalSearchStatusUpdateDTO(run_state=RunStateEnum.RUNNING),
        )


class AutonomousTutorCallback(StatusCallback):
    """Status callback for autonomous tutor pipeline."""

    def __init__(self, run_id: str, base_url: str):
        url = f"{base_url}/{self.api_url}/autonomous-tutor/runs/{run_id}/status"
        super().__init__(
            url,
            run_id,
            AutonomousTutorPipelineStatusUpdateDTO(run_state=RunStateEnum.RUNNING),
        )


class StruggleInterventionCallback(StatusCallback):
    """Status callback for the proactive struggle-intervention pipeline."""

    def __init__(self, run_id: str, base_url: str):
        url = f"{base_url}/{self.api_url}/struggle-intervention/runs/{run_id}/status"
        super().__init__(
            url,
            run_id,
            StruggleInterventionStatusUpdateDTO(run_state=RunStateEnum.RUNNING),
        )
        self._trailing_finish_seen = False

    # Attempts (with backoff) for the terminal frame, matching the chat callback's
    # delivery-critical sends.
    _TERMINAL_RETRY_ATTEMPTS = 3

    def on_status_update(self) -> bool:
        """Post the current status, retrying the terminal frame.

        The terminal frame is the only thing Artemis ever learns about this run: it carries the
        decision, and it is what completes the student's in-flight request. ``finish`` marks the
        run terminal before it posts and this callback absorbs the pipeline's trailing finish, so
        nothing behind it would try again. One 5xx or one restart landing on this POST would drop
        the hint and leave the client waiting for its own timeout.
        """
        if not self._terminal_sent:
            return super().on_status_update()
        return self._send_payload_with_backoff(
            self._serialize_status(), self._TERMINAL_RETRY_ATTEMPTS
        )

    def _reject_after_terminal(self, operation: str) -> None:
        """Absorb the one trailing finish this pipeline's shape produces.

        post_agent_hook owns the terminal frame here: it finishes the decision itself, or fails
        a help request that came back unusable. AbstractAgentPipeline then closes every run with
        a finish of its own, which arrives after that and is rejected. It is structural, not an
        anomaly, so it must not reach Sentry on every single run. Exactly one is absorbed; a
        second one, and every rejected fail or update, stays an anomaly and is reported.
        """
        if operation == "finish" and not self._trailing_finish_seen:
            self._trailing_finish_seen = True
            logger.debug(
                "Absorbed the trailing finish for run %s; the pipeline had already sent its "
                "terminal frame",
                self.run_id,
            )
            return
        super()._reject_after_terminal(operation)
