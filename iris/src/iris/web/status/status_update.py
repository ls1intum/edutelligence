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
from iris.pipeline.chat.iris_chat_mode import IrisChatMode
from iris.tracing import TracedThreadPoolExecutor

logger = get_logger(__name__)


class StatusCallback:
    """A callback class for sending run-state status updates to Artemis."""

    api_url: str = "api/iris/internal/pipelines"

    def __init__(self, url: str, run_id: str, status: StatusUpdateDTO):
        self.url = url
        self.run_id = run_id
        self.status = status
        self._terminal_sent = False
        self._in_progress_executor: Optional[TracedThreadPoolExecutor] = None
        self._in_progress_futures: list[Future] = []
        self._in_progress_lock = Lock()

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
        self, payload: dict[str, Any], *, async_in_progress: bool = False
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
            if async_in_progress:
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

    def _get_in_progress_executor(self) -> TracedThreadPoolExecutor:
        """Create the FIFO async sender lazily for in-progress updates."""
        if self._in_progress_executor is None:
            self._in_progress_executor = TracedThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="StatusCallback",
            )
        return self._in_progress_executor

    def _enqueue_in_progress_update(
        self, payload: Optional[dict[str, Any]] = None
    ) -> None:
        """Queue a running status update without blocking the pipeline."""
        if self._terminal_sent:
            self._reject_after_terminal("async update")
            return
        queued_payload = payload if payload is not None else self._serialize_status()
        future = self._get_in_progress_executor().submit(
            self._send_status_payload,
            queued_payload,
            async_in_progress=True,
        )
        with self._in_progress_lock:
            self._in_progress_futures.append(future)

    def _drain_in_progress_updates(self) -> None:
        """Wait for all queued in-progress updates before sync sends."""
        while True:
            with self._in_progress_lock:
                futures = self._in_progress_futures
                self._in_progress_futures = []
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
        self._drain_in_progress_updates()
        return self.on_status_update()

    def finish(self, **fields) -> bool:
        """Synchronously post a FINISHED terminal status update."""
        if self._terminal_sent:
            self._reject_after_terminal("finish")
            return False
        self.status.run_state = RunStateEnum.FINISHED
        self.status.error = None
        self._apply_fields(fields)
        self._terminal_sent = True
        self._drain_in_progress_updates()
        return self.on_status_update()

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
        self._terminal_sent = True
        self._drain_in_progress_updates()
        success = self.on_status_update()
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

    def activity_snapshot(self, activities: list[ActivityDTO], seq: int) -> None:
        payload = self._payload(
            run_state=RunStateEnum.RUNNING,
            activities=activities,
            activity_seq=seq,
        )
        self._enqueue_in_progress_update(payload)

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
            "tokens": tokens or [],
        }
        if accessed_memories is not None:
            fields["accessed_memories"] = self._memory_dtos(accessed_memories)
        if activities is not None:
            fields["activities"] = activities
        if activity_seq is not None:
            fields["activity_seq"] = activity_seq

        success = self._send_chat_fields(fields, attempts=3)
        if not success:
            self._undelivered_result_fields = fields
        return success

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
        return self._send_chat_fields(
            fields,
            run_state=RunStateEnum.FAILED,
            error=StatusErrorDTO(message=message, code=code),
        )

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
        payload = self._payload(run_state=run_state, error=error, **fields)

        if run_state != RunStateEnum.RUNNING:
            self._terminal_sent = True
        self._drain_in_progress_updates()

        for attempt in range(attempts):
            if self._send_status_payload(payload):
                if carried_result:
                    self._undelivered_result_fields = None
                return True
            if attempt < attempts - 1:
                time.sleep((1, 2, 4)[attempt])
        return False

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


class ChatStatusCallback(ChatRunCallback):
    """Compatibility constructor for chat pipelines before Task A7 migration."""

    def __init__(
        self,
        run_id: str,
        base_url: str,
        chat_mode: IrisChatMode,
        initial_stages=None,
    ):
        del chat_mode, initial_stages
        super().__init__(run_id, base_url, None)


class ChatGPTWrapperStatusCallback(StatusCallback):
    """Status callback for ChatGPT wrapper pipelines."""

    def __init__(self, run_id: str, base_url: str, initial_stages=None):
        del initial_stages
        url = (
            f"{base_url}/{self.api_url}/programming-exercise-chat/runs/{run_id}/status"
        )
        super().__init__(
            url, run_id, ChatStatusUpdateDTO(run_state=RunStateEnum.RUNNING)
        )


class CompetencyExtractionCallback(StatusCallback):
    """Status callback for competency extraction pipelines."""

    def __init__(self, run_id: str, base_url: str, initial_stages=None):
        del initial_stages
        url = f"{base_url}/{self.api_url}/competency-extraction/runs/{run_id}/status"
        super().__init__(
            url,
            run_id,
            CompetencyExtractionStatusUpdateDTO(run_state=RunStateEnum.RUNNING),
        )


class RewritingCallback(StatusCallback):
    """Status callback for rewriting pipelines."""

    def __init__(self, run_id: str, base_url: str, initial_stages=None):
        del initial_stages
        url = f"{base_url}/{self.api_url}/rewriting/runs/{run_id}/status"
        super().__init__(
            url, run_id, RewritingStatusUpdateDTO(run_state=RunStateEnum.RUNNING)
        )


class InconsistencyCheckCallback(StatusCallback):
    """Status callback for inconsistency check pipelines."""

    def __init__(self, run_id: str, base_url: str, initial_stages=None):
        del initial_stages
        url = f"{base_url}/{self.api_url}/inconsistency-check/runs/{run_id}/status"
        super().__init__(
            url,
            run_id,
            InconsistencyCheckStatusUpdateDTO(run_state=RunStateEnum.RUNNING),
        )


class TutorSuggestionCallback(StatusCallback):
    """Status callback for tutor suggestion pipelines."""

    def __init__(self, run_id: str, base_url: str, initial_stages=None):
        del initial_stages
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

    def thinking(self):
        """Send a RUNNING global-search heartbeat."""
        logger.info("[global-search] → callback: thinking (LLM path started)")
        return self.update()

    def done(self, answer=None, sources=None, tokens=None, **_kwargs):
        """Attach the search answer and mark the run finished."""
        logger.info(
            "[global-search] → callback: done  answer=%s  sources=%d",
            "present" if answer else "null",
            len(sources) if sources else 0,
        )
        return self.finish(answer=answer, sources=sources or [], tokens=tokens or [])


class AutonomousTutorCallback(StatusCallback):
    """Status callback for autonomous tutor pipeline."""

    def __init__(self, run_id: str, base_url: str, initial_stages=None):
        del initial_stages
        url = f"{base_url}/{self.api_url}/autonomous-tutor/runs/{run_id}/status"
        super().__init__(
            url,
            run_id,
            AutonomousTutorPipelineStatusUpdateDTO(run_state=RunStateEnum.RUNNING),
        )
