import time
from concurrent.futures import Future
from threading import Lock
from typing import Any, Optional

import requests
from memiris import Memory
from memiris.api.memory_dto import MemoryDTO
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


class StatusCallback:
    """A callback class for sending run-state status updates to Artemis."""

    api_url: str = "api/iris/internal/pipelines"

    # Result-like payload fields that describe a single RUNNING update and must
    # NOT leak into later heartbeats or the terminal send. ``result`` carries
    # e.g. transcription checkpoint JSON; ``display_page_numbers`` is attached
    # only to the send that produced it. Persistent fields (run_state, error,
    # tokens, activities, and identity fields such as the lecture-unit id) are
    # intentionally excluded so they keep accumulating across updates.
    _TRANSIENT_RESULT_FIELDS: tuple[str, ...] = ("result", "display_page_numbers")

    def __init__(self, url: str, run_id: str, status: StatusUpdateDTO):
        self.url = url
        self.run_id = run_id
        self.status = status
        self._terminal_sent = False
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

    def _shutdown_running_update_executor(self) -> None:
        """Stop the async running-update executor after terminal delivery."""
        with self._running_update_lock:
            executor = self._running_update_executor
            self._running_update_executor = None
        if executor is not None:
            executor.shutdown(wait=False)

    def _mark_terminal_sent(self) -> None:
        with self._running_update_lock:
            self._terminal_sent = True

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
        if self._terminal_sent:
            self._reject_after_terminal("finish")
            return False
        self.status.run_state = RunStateEnum.FINISHED
        self.status.error = None
        self._apply_fields(fields)
        self._mark_terminal_sent()
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
        if self._terminal_sent:
            self._reject_after_terminal("fail")
            return False
        self.status.run_state = RunStateEnum.FAILED
        self.status.error = StatusErrorDTO(message=message, code=code)
        if tokens is not None:
            self.status.tokens = tokens
        self._apply_fields(fields)
        self._mark_terminal_sent()
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
        logger.warning(message)
        capture_message(message)


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
        # How many entries of the run's cumulative token list Artemis has received.
        self._delivered_token_count = 0

    def activity_snapshot(self, activities: list[ActivityDTO], seq: int) -> None:
        payload = self._payload(
            run_state=RunStateEnum.RUNNING,
            activities=activities,
            activity_seq=seq,
        )
        self._enqueue_running_update(payload)

    def update(self, **fields) -> bool:
        """Post a RUNNING update. Usage must not travel this way.

        ``update`` posts the reusable status DTO directly and would therefore bypass the
        delta bookkeeping every other send goes through. Chat usage belongs on
        ``send_result``, ``finish`` or ``fail``.
        """
        if "tokens" in fields:
            raise ValueError(
                "ChatRunCallback.update() must not carry tokens; "
                "use send_result(), finish() or fail() so the usage is reported once."
            )
        return super().update(**fields)

    def send_result(
        self,
        final_result,
        tokens=None,
        accessed_memories=None,
        activities=None,
        activity_seq=None,
    ) -> bool:
        fields = {
            "result": final_result,
            "final": True,
            "tokens": tokens or [],
        }
        if accessed_memories is not None:
            fields["accessed_memories"] = self._memory_dtos(accessed_memories)
        if activities is not None:
            fields["activities"] = activities
        if activity_seq is not None:
            fields["activity_seq"] = activity_seq

        success = self._send_chat_fields(fields, attempts=self._DELIVERY_RETRY_ATTEMPTS)
        if not success:
            self._undelivered_result_fields = fields
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
        created_memories=None,
        tokens=None,
        activities=None,
        activity_seq=None,
    ) -> bool:
        fields: dict[str, Any] = {}
        if session_title is not None:
            fields["session_title"] = session_title
        if created_memories is not None:
            fields["created_memories"] = self._memory_dtos(created_memories)
        if tokens is not None:
            fields["tokens"] = tokens
        if activities is not None:
            fields["activities"] = activities
        if activity_seq is not None:
            fields["activity_seq"] = activity_seq
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
    ) -> bool:
        fields: dict[str, Any] = {}
        if tokens is not None:
            fields["tokens"] = tokens
        if session_title is not None:
            fields["session_title"] = session_title
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
        if self._terminal_sent:
            self._reject_after_terminal(run_state.value.lower())
            return False

        fields, carried_result = self._merge_undelivered_result(fields)

        pending_tokens: Optional[list[TokenUsageDTO]] = None
        if "tokens" in fields:
            pending_tokens = self._tokens_not_yet_delivered(fields["tokens"])
            # A copy: the caller keeps the cumulative list it passed, which send_result
            # stores as the undelivered payload and the next send slices again.
            fields = {**fields, "tokens": pending_tokens}

        # A terminal send is the LAST chance to deliver an answer that a prior
        # send_result() failed to hand off. Give it the same retry/backoff so a
        # transient failure there does not drop the delivery-critical answer.
        # Terminal sends without a carried result stay single-shot to avoid
        # slowing the common (already-delivered) path.
        if carried_result and run_state != RunStateEnum.RUNNING:
            attempts = max(attempts, self._DELIVERY_RETRY_ATTEMPTS)

        payload = self._payload(run_state=run_state, error=error, **fields)

        terminal_send = run_state != RunStateEnum.RUNNING
        if terminal_send:
            self._mark_terminal_sent()
        self._drain_running_updates()

        try:
            for attempt in range(attempts):
                if self._send_status_payload(payload):
                    if carried_result:
                        self._undelivered_result_fields = None
                    if pending_tokens:
                        self._delivered_token_count += len(pending_tokens)
                    return True
                if attempt < attempts - 1:
                    time.sleep((1, 2, 4)[attempt])
            return False
        finally:
            if terminal_send:
                self._shutdown_running_update_executor()

    def _tokens_not_yet_delivered(
        self, tokens: list[TokenUsageDTO]
    ) -> list[TokenUsageDTO]:
        """Return the part of the run's usage Artemis has not been told about yet.

        Every send hands over the run's cumulative token list, but Artemis appends what
        arrives to the run's trace without deduplicating it, so an entry sent twice is
        billed twice. The counter only advances after a delivered POST, which is what
        carries the usage of a failed send forward to the next one.
        """
        if len(tokens) < self._delivered_token_count:
            # Someone passed a partial list instead of the run's cumulative one. Sending it
            # would re-report what Artemis already has, so report nothing and say so loudly.
            message = (
                f"Token list for run {self.run_id} shrank from "
                f"{self._delivered_token_count} to {len(tokens)} entries; "
                "expected the run's cumulative usage. Reporting nothing for this send."
            )
            logger.error(message)
            capture_message(message)
            return []
        delivered = self._delivered_token_count
        return tokens[delivered:]

    def _merge_undelivered_result(
        self, fields: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        if self._undelivered_result_fields is None:
            return fields, False
        return {**self._undelivered_result_fields, **fields}, True

    @staticmethod
    def _memory_dtos(memories: list[Memory]) -> list[MemoryDTO]:
        return [MemoryDTO.from_memory(memory) for memory in memories]

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
