from typing import Optional, List


from sentry_sdk import capture_exception, capture_message

import requests
from abc import ABC

from app.common.token_usage_dto import TokenUsageDTO
from app.domain.status.competency_extraction_status_update_dto import (
    CompetencyExtractionStatusUpdateDTO,
)
from app.domain.chat.course_chat.course_chat_status_update_dto import (
    CourseChatStatusUpdateDTO,
)
from app.domain.status.lecture_chat_status_update_dto import (
    LectureChatStatusUpdateDTO,
)
from app.domain.status.stage_state_dto import StageStateEnum
from app.domain.status.stage_dto import StageDTO
from app.domain.status.text_exercise_chat_status_update_dto import (
    TextExerciseChatStatusUpdateDTO,
)
from app.domain.chat.exercise_chat.exercise_chat_status_update_dto import (
    ExerciseChatStatusUpdateDTO,
)
from app.domain.status.status_update_dto import StatusUpdateDTO
import logging

logger = logging.getLogger(__name__)


class StatusCallback(ABC):
    """
    A callback class for sending status updates to the Artemis API.
    """

    url: str
    run_id: str
    status: StatusUpdateDTO
    stage: StageDTO
    current_stage_index: Optional[int]

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
            print(self.status.dict(by_alias=True))
            requests.post(
                self.url,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.run_id}",
                },
                json=self.status.model_dump(by_alias=True),
            ).raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error sending status update: {e}")
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
        suggestions: Optional[List[str]] = None,
        tokens: Optional[List[TokenUsageDTO]] = None,
        next_stage_message: Optional[str] = None,
        start_next_stage: bool = True,
    ):
        """
        Transition the current stage to DONE and update the status.
        If there is a next stage, set the current
        stage to the next stage.
        """
        self.stage.state = StageStateEnum.DONE
        self.stage.message = message
        self.status.result = final_result
        self.status.tokens = tokens or self.status.tokens
        if hasattr(self.status, "suggestions"):
            self.status.suggestions = suggestions
        next_stage = self.get_next_stage()
        if next_stage is not None:
            self.stage = next_stage
            if next_stage_message:
                self.stage.message = next_stage_message
            if start_next_stage:
                self.stage.state = StageStateEnum.IN_PROGRESS
        self.on_status_update()
        self.status.result = None
        if hasattr(self.status, "suggestions"):
            self.status.suggestions = None

    def error(
        self, message: str, exception=None, tokens: Optional[List[TokenUsageDTO]] = None
    ):
        """
        Transition the current stage to ERROR and update the status.
        Set all later stages to SKIPPED if an error occurs.
        """
        self.stage.state = StageStateEnum.ERROR
        self.stage.message = message
        self.status.result = None
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
            f"Error occurred in job {self.run_id} in stage {self.stage.name}: {message}"
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
        self.status.suggestions = None
        next_stage = self.get_next_stage()
        if next_stage is not None:
            self.stage = next_stage
            if start_next_stage:
                self.stage.state = StageStateEnum.IN_PROGRESS
        self.on_status_update()


class CourseChatStatusCallback(StatusCallback):
    def __init__(
        self, run_id: str, base_url: str, initial_stages: List[StageDTO] = None
    ):
        url = f"{base_url}/api/public/pyris/pipelines/course-chat/runs/{run_id}/status"
        current_stage_index = len(initial_stages) if initial_stages else 0
        stages = initial_stages or []
        stages += [
            StageDTO(
                weight=40,
                state=StageStateEnum.NOT_STARTED,
                name="Thinking",
            ),
            # StageDTO(
            #     weight=10, state=StageStateEnum.NOT_STARTED, name="Creating suggestions"
            # ),
        ]
        status = CourseChatStatusUpdateDTO(stages=stages)
        stage = stages[current_stage_index]
        super().__init__(url, run_id, status, stage, current_stage_index)


class ExerciseChatStatusCallback(StatusCallback):
    def __init__(
        self, run_id: str, base_url: str, initial_stages: List[StageDTO] = None
    ):
        url = f"{base_url}/api/public/pyris/pipelines/tutor-chat/runs/{run_id}/status"
        current_stage_index = len(initial_stages) if initial_stages else 0
        stages = initial_stages or []
        stages += [
            StageDTO(
                weight=30,
                state=StageStateEnum.NOT_STARTED,
                name="Checking available information",
            ),
            StageDTO(
                weight=10, state=StageStateEnum.NOT_STARTED, name="Creating suggestions"
            ),
        ]
        status = ExerciseChatStatusUpdateDTO(stages=stages)
        stage = stages[current_stage_index]
        super().__init__(url, run_id, status, stage, current_stage_index)


class TextExerciseChatCallback(StatusCallback):
    def __init__(
        self,
        run_id: str,
        base_url: str,
        initial_stages: List[StageDTO],
    ):
        url = f"{base_url}/api/public/pyris/pipelines/text-exercise-chat/runs/{run_id}/status"
        stages = initial_stages or []
        stage = len(stages)
        stages += [
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
        ]
        super().__init__(
            url,
            run_id,
            TextExerciseChatStatusUpdateDTO(stages=stages),
            stages[stage],
            stage,
        )


class CompetencyExtractionCallback(StatusCallback):
    def __init__(
        self,
        run_id: str,
        base_url: str,
        initial_stages: List[StageDTO],
    ):
        url = f"{base_url}/api/public/pyris/pipelines/competency-extraction/runs/{run_id}/status"
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


class LectureChatCallback(StatusCallback):
    def __init__(
        self,
        run_id: str,
        base_url: str,
        initial_stages: List[StageDTO],
    ):
        url = f"{base_url}/api/public/pyris/pipelines/lecture-chat/runs/{run_id}/status"
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
            LectureChatStatusUpdateDTO(stages=stages, result=""),
            stages[stage],
            stage,
        )
