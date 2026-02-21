from abc import ABC
from typing import List, Optional

import requests
from memiris import Memory
from memiris.api.memory_dto import MemoryDTO
from sentry_sdk import capture_exception, capture_message

from iris.common.logging_config import get_logger
from iris.common.token_usage_dto import TokenUsageDTO
from iris.domain.communication.communication_tutor_suggestion_status_update_dto import (
    TutorSuggestionStatusUpdateDTO,
)
from iris.domain.status.chat_status_update_dto import ChatStatusUpdateDTO
from iris.domain.status.competency_extraction_status_update_dto import (
    CompetencyExtractionStatusUpdateDTO,
)
from iris.domain.status.inconsistency_check_status_update_dto import (
    InconsistencyCheckStatusUpdateDTO,
)
from iris.domain.status.rewriting_status_update_dto import (
    RewritingStatusUpdateDTO,
)
from iris.domain.status.stage_dto import StageDTO
from iris.domain.status.stage_state_dto import StageStateEnum
from iris.domain.status.status_update_dto import StatusUpdateDTO
from iris.pipeline.chat.chat_context import ChatContext

logger = get_logger(__name__)


class StatusCallback(ABC):
    """
    A callback class for sending status updates to the Artemis API.
    """

    url: str
    run_id: str
    status: StatusUpdateDTO
    stage: StageDTO
    current_stage_index: Optional[int]

    api_url: str = "api/iris/internal/pipelines"

    def __init__(
        self,
        url: str,
        run_id: str,
        status: StatusUpdateDTO = None,
        stage: StageDTO = None,
        current_stage_index: Optional[int] = None,
    ):
        self.url = url
        self.run_id = run_id
        self.status = status
        self.stage = stage
        self.current_stage_index = current_stage_index

    def on_status_update(self):
        """Send a status update to the Artemis API."""
        try:
            requests.post(
                self.url,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.run_id}",
                },
                json=self.status.model_dump(by_alias=True),
                timeout=200,
            ).raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error("Error sending status update: %s", e)
            capture_exception(e)

    def get_next_stage(self):
        """Return the next stage in the status, or None if there are no more stages."""
        # Increment the current stage index
        self.current_stage_index += 1

        # Check if the current stage index is out of bounds
        if self.current_stage_index >= len(self.status.stages):
            return None

        # Return the next stage
        return self.status.stages[self.current_stage_index]

    def in_progress(self, message: Optional[str] = None):
        """Transition the current stage to IN_PROGRESS and update the status."""
        if self.stage.state == StageStateEnum.NOT_STARTED:
            self.stage.state = StageStateEnum.IN_PROGRESS
            self.stage.message = message
            self.on_status_update()
        elif self.stage.state == StageStateEnum.IN_PROGRESS:
            self.stage.message = message
            self.on_status_update()
        else:
            raise ValueError(
                "Invalid state transition to in_progress. current state is ",
                self.stage.state,
            )

    def done(
        self,
        message: Optional[str] = None,
        final_result: Optional[str] = None,
        session_title: Optional[str] = None,
        suggestions: Optional[List[str]] = None,
        tokens: Optional[List[TokenUsageDTO]] = None,
        next_stage_message: Optional[str] = None,
        start_next_stage: bool = True,
        inconsistencies: Optional[List[str]] = None,
        improvement: Optional[str] = None,
        accessed_memories: Optional[List[Memory]] = None,
        created_memories: Optional[List[Memory]] = None,
        artifact: Optional[str] = None,
    ):
        """
        Transition the current stage to DONE and update the status.
        If there is a next stage, set the current
        stage to the next stage.
        """
        self.stage.state = StageStateEnum.DONE
        self.stage.message = message
        self.status.tokens = tokens or self.status.tokens
        self.status.result = final_result
        if hasattr(self.status, "session_title"):
            self.status.session_title = session_title
        if hasattr(self.status, "suggestions"):
            self.status.suggestions = suggestions
        if hasattr(self.status, "inconsistencies"):
            self.status.inconsistencies = inconsistencies
        if hasattr(self.status, "improvement"):
            self.status.improvement = improvement
        if hasattr(self.status, "accessed_memories"):
            self.status.accessed_memories = (
                [MemoryDTO.from_memory(memory) for memory in accessed_memories]
                if accessed_memories
                else []
            )
        if hasattr(self.status, "created_memories"):
            self.status.created_memories = (
                [MemoryDTO.from_memory(memory) for memory in created_memories]
                if created_memories
                else []
            )
        if hasattr(self.status, "artifact"):
            self.status.artifact = artifact
        next_stage = self.get_next_stage()

        if next_stage is not None:
            self.stage = next_stage
            if next_stage_message:
                self.stage.message = next_stage_message
            if start_next_stage:
                self.stage.state = StageStateEnum.IN_PROGRESS

        self.on_status_update()

        self.status.result = None
        if hasattr(self.status, "session_title"):
            self.status.session_title = None
        if hasattr(self.status, "suggestions"):
            self.status.suggestions = None
        if hasattr(self.status, "inconsistencies"):
            self.status.inconsistencies = None
        if hasattr(self.status, "accessed_memories"):
            self.status.accessed_memories = None
        if hasattr(self.status, "created_memories"):
            self.status.created_memories = None

    def error(
        self,
        message: str,
        exception=None,
        tokens: Optional[List[TokenUsageDTO]] = None,
    ):
        """
        Transition the current stage to ERROR and update the status.
        Set all later stages to SKIPPED if an error occurs.
        """
        self.stage.state = StageStateEnum.ERROR
        self.stage.message = message
        self.status.result = None
        if hasattr(self.status, "suggestions"):
            self.status.suggestions = None
        self.status.tokens = tokens or self.status.tokens
        # Set all subsequent stages to SKIPPED if an error occurs
        rest_of_index = (
            self.current_stage_index + 1
        )  # Black and flake8 are conflicting with each other if this expression gets used in list comprehension
        for stage in self.status.stages[rest_of_index:]:
            stage.state = StageStateEnum.SKIPPED
            stage.message = "Skipped due to previous error"

        # Update the status after setting the stages to SKIPPED
        self.stage = self.status.stages[-1]
        self.on_status_update()
        logger.error(
            "Error occurred in job %s in stage %s: %s",
            self.run_id,
            self.stage.name,
            message,
        )
        if exception:
            capture_exception(exception)
        else:
            capture_message(
                f"Error occurred in job {self.run_id} in stage {self.stage.name}: {message}"
            )

    def skip(self, message: Optional[str] = None, start_next_stage: bool = True):
        """
        Transition the current stage to SKIPPED and update the status.
        If there is a next stage, set the current stage to the next stage.
        """
        self.stage.state = StageStateEnum.SKIPPED
        self.stage.message = message
        self.status.result = None
        if hasattr(self.status, "suggestions"):
            self.status.suggestions = None
        next_stage = self.get_next_stage()
        if next_stage is not None:
            self.stage = next_stage
            if start_next_stage:
                self.stage.state = StageStateEnum.IN_PROGRESS
        self.on_status_update()


_CHAT_CONTEXT_STAGES: dict[ChatContext, list[StageDTO]] = {
    ChatContext.COURSE: [
        StageDTO(
            weight=40,
            state=StageStateEnum.NOT_STARTED,
            name="Thinking",
        ),
        StageDTO(
            weight=10,
            state=StageStateEnum.NOT_STARTED,
            name="Extracting memories",
            internal=True,
        ),
    ],
    ChatContext.EXERCISE: [
        StageDTO(
            weight=30,
            state=StageStateEnum.NOT_STARTED,
            name="Checking available information",
        ),
        StageDTO(
            weight=10,
            state=StageStateEnum.NOT_STARTED,
            name="Creating suggestions",
        ),
    ],
    ChatContext.TEXT_EXERCISE: [
        StageDTO(
            weight=30,
            state=StageStateEnum.NOT_STARTED,
            name="Thinking",
        ),
        StageDTO(
            weight=20,
            state=StageStateEnum.NOT_STARTED,
            name="Responding",
        ),
    ],
    ChatContext.LECTURE: [
        StageDTO(
            weight=30,
            state=StageStateEnum.NOT_STARTED,
            name="Thinking",
        ),
        StageDTO(
            weight=10,
            state=StageStateEnum.NOT_STARTED,
            name="Extracting memories",
            internal=True,
        ),
    ],
}


class ChatStatusCallback(StatusCallback):
    """Unified status callback for all chat pipelines."""

    def __init__(
        self,
        run_id: str,
        base_url: str,
        context: ChatContext,
        initial_stages: List[StageDTO] = None,
    ):
        url = f"{base_url}/{self.api_url}/chat/runs/{run_id}/status"
        stages = initial_stages or []
        current_stage_index = len(stages)
        stages += [stage.model_copy() for stage in _CHAT_CONTEXT_STAGES[context]]
        status = ChatStatusUpdateDTO(stages=stages)
        super().__init__(
            url, run_id, status, stages[current_stage_index], current_stage_index
        )


class ChatGPTWrapperStatusCallback(StatusCallback):
    """Status callback for ChatGPT wrapper pipelines."""

    def __init__(
        self, run_id: str, base_url: str, initial_stages: List[StageDTO] = None
    ):
        url = (
            f"{base_url}/{self.api_url}/programming-exercise-chat/runs/{run_id}/status"
        )
        current_stage_index = len(initial_stages) if initial_stages else 0
        stages = initial_stages or []
        stages += [
            StageDTO(
                weight=30,
                state=StageStateEnum.NOT_STARTED,
                name="Generating response",
            ),
        ]
        status = ChatStatusUpdateDTO(stages=stages)
        stage = stages[current_stage_index]
        super().__init__(url, run_id, status, stage, current_stage_index)


class CompetencyExtractionCallback(StatusCallback):
    """Status callback for competency extraction pipelines."""

    def __init__(
        self,
        run_id: str,
        base_url: str,
        initial_stages: List[StageDTO],
    ):
        url = f"{base_url}/{self.api_url}/competency-extraction/runs/{run_id}/status"
        stages = initial_stages or []
        stages.append(
            StageDTO(
                weight=10,
                state=StageStateEnum.NOT_STARTED,
                name="Generating Competencies",
            )
        )
        status = CompetencyExtractionStatusUpdateDTO(stages=stages)
        stage = stages[-1]
        super().__init__(url, run_id, status, stage, len(stages) - 1)


class RewritingCallback(StatusCallback):
    """Status callback for rewriting pipelines."""

    def __init__(
        self,
        run_id: str,
        base_url: str,
        initial_stages: List[StageDTO],
    ):
        url = f"{base_url}/{self.api_url}/rewriting/runs/{run_id}/status"
        stages = initial_stages or []
        stages.append(
            StageDTO(
                weight=10,
                state=StageStateEnum.NOT_STARTED,
                name="Generating Rewritting",
            )
        )
        status = RewritingStatusUpdateDTO(stages=stages)
        stage = stages[-1]
        super().__init__(url, run_id, status, stage, len(stages) - 1)


class InconsistencyCheckCallback(StatusCallback):
    """Status callback for inconsistency check pipelines."""

    def __init__(
        self,
        run_id: str,
        base_url: str,
        initial_stages: List[StageDTO],
    ):
        url = f"{base_url}/{self.api_url}/inconsistency-check/runs/{run_id}/status"
        stages = initial_stages or []
        stages.append(
            StageDTO(
                weight=10,
                state=StageStateEnum.NOT_STARTED,
                name="Checking for inconsistencies",
            )
        )
        status = InconsistencyCheckStatusUpdateDTO(stages=stages)
        stage = stages[-1]
        super().__init__(url, run_id, status, stage, len(stages) - 1)


class TutorSuggestionCallback(StatusCallback):
    """Status callback for tutor suggestion pipelines."""

    def __init__(
        self,
        run_id: str,
        base_url: str,
        initial_stages: List[StageDTO],
    ):
        url = f"{base_url}/{self.api_url}/tutor-suggestion/runs/{run_id}/status"
        stages = initial_stages or []
        stage = len(stages)
        stages += [
            StageDTO(
                weight=30,
                state=StageStateEnum.NOT_STARTED,
                name="Thinking",
            ),
        ]
        super().__init__(
            url,
            run_id,
            TutorSuggestionStatusUpdateDTO(stages=stages),
            stages[stage],
            stage,
        )
