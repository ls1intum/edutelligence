from typing import List

from .status_update import StatusCallback
from ...domain.status.stage_state_dto import StageStateEnum
from ...domain.status.stage_dto import StageDTO
from ...domain.exercise_chat.exercise_chat_status_update_dto import TutorChatStatusUpdateDTO
import logging

logger = logging.getLogger(__name__)


class LectureChatStatusCallback(StatusCallback):
    """
    Callback class for updating the status of a Lecture Chat pipeline run.
    """

    def __init__(
        self, run_id: str, base_url: str, initial_stages: List[StageDTO] = None
    ):
        url = f"{base_url}/api/public/pyris/pipelines/lecture-chat/runs/{run_id}/status"
        current_stage_index = len(initial_stages) if initial_stages else 0
        stages = initial_stages or []
        stages += [
            StageDTO(
                weight=50,
                state=StageStateEnum.NOT_STARTED,
                name="Lecture content retrieval",
            ),
            StageDTO(
                weight=50,
                state=StageStateEnum.NOT_STARTED,
                name="Response Generation",
            ),
        ]
        status = TutorChatStatusUpdateDTO(stages=stages)
        stage = stages[current_stage_index]
        super().__init__(url, run_id, status, stage, current_stage_index)
