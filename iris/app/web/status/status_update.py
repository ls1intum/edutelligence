from typing import Optional
from abc import ABC

import requests

from ...domain.status.stage_state_dto import StageStateEnum
from ...domain.status.stage_dto import StageDTO
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
        else:
            raise ValueError("Invalid state transition")

    def done(self, message: Optional[str] = None, final_result: Optional[str] = None):
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
            self.on_status_update()
        else:
            raise ValueError("Invalid state transition")

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
