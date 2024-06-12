from typing import Optional, List

import requests
from abc import ABC

from ...domain.chat.course_chat.course_chat_status_update_dto import (
    CourseChatStatusUpdateDTO,
)
from ...domain.status.stage_state_dto import StageStateEnum
from ...domain.status.stage_dto import StageDTO
from ...domain.chat.exercise_chat.exercise_chat_status_update_dto import (
    ExerciseChatStatusUpdateDTO,
)
from ...domain.status.status_update_dto import StatusUpdateDTO
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
                json=self.status.dict(by_alias=True),
            ).raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error sending status update: {e}")

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
    ):
        """
        Transition the current stage to DONE and update the status.
        If there is a next stage, set the current
        stage to the next stage.
        """
        if self.stage.state == StageStateEnum.IN_PROGRESS:
            self.stage.state = StageStateEnum.DONE
            self.stage.message = message
            next_stage = self.get_next_stage()
            if next_stage is not None:
                self.stage = next_stage
            else:
                self.status.result = final_result
                self.status.suggestions = suggestions
            self.on_status_update()
        else:
            raise ValueError(
                "Invalid state transition to done. current state is ", self.stage.state
            )

    def error(self, message: str):
        """
        Transition the current stage to ERROR and update the status.
        Set all later stages to SKIPPED if an error occurs.
        """
        self.stage.state = StageStateEnum.ERROR
        self.stage.message = message
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

    def skip(self, message: Optional[str] = None):
        """
        Transition the current stage to SKIPPED and update the status.
        If there is a next stage, set the current stage to the next stage.
        """
        self.stage.state = StageStateEnum.SKIPPED
        self.stage.message = message
        next_stage = self.get_next_stage()
        if next_stage is not None:
            self.stage = next_stage
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
            StageDTO(weight=30, state=StageStateEnum.NOT_STARTED, name="File Lookup"),
            StageDTO(
                weight=70,
                state=StageStateEnum.NOT_STARTED,
                name="Response Generation",
            ),
        ]
        status = ExerciseChatStatusUpdateDTO(stages=stages)
        stage = stages[current_stage_index]
        super().__init__(url, run_id, status, stage, current_stage_index)
