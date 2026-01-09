from typing import List

from iris.common.logging_config import get_logger

from ...domain.ingestion.ingestion_status_update_dto import (
    IngestionStatusUpdateDTO,
)
from ...domain.status.stage_dto import StageDTO
from ...domain.status.stage_state_dto import StageStateEnum
from .status_update import StatusCallback

logger = get_logger(__name__)


class LecturesDeletionStatusCallback(StatusCallback):
    """
    Callback class for updating the status of a Tutor Chat pipeline run.
    """

    def __init__(
        self, run_id: str, base_url: str, initial_stages: List[StageDTO] = None
    ):
        url = f"{base_url}/api/iris/internal/webhooks/ingestion/runs/{run_id}/status"

        current_stage_index = len(initial_stages) if initial_stages else 0
        stages = initial_stages or []
        stages += [
            StageDTO(
                weight=100,
                state=StageStateEnum.NOT_STARTED,
                name="Lecture unit removal",
            ),
        ]
        status = IngestionStatusUpdateDTO(stages=stages)
        stage = stages[current_stage_index]
        super().__init__(url, run_id, status, stage, current_stage_index)
