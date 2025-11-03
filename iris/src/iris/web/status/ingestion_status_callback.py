import logging
from typing import List

from ...domain.ingestion.ingestion_status_update_dto import (
    IngestionStatusUpdateDTO,
)
from ...domain.status.stage_dto import StageDTO
from ...domain.status.stage_state_dto import StageStateEnum
from .status_update import StatusCallback

logger = logging.getLogger(__name__)


class IngestionStatusCallback(StatusCallback):
    """
    Callback class for updating the status of a Lecture ingestion Pipeline run.
    """

    def __init__(
        self,
        run_id: str,
        base_url: str,
        initial_stages: List[StageDTO] = None,
        lecture_unit_id: int = None,
    ):
        url = f"{base_url}/api/iris/internal/webhooks/ingestion/runs/{run_id}/status"

        current_stage_index = len(initial_stages) if initial_stages else 0
        stages = initial_stages or []
        stages += [
            StageDTO(
                weight=10,
                state=StageStateEnum.NOT_STARTED,
                name="Old slides removal",
            ),
            StageDTO(
                weight=20,
                state=StageStateEnum.NOT_STARTED,
                name="Slides Interpretation",
            ),
            StageDTO(
                weight=10,
                state=StageStateEnum.NOT_STARTED,
                name="Slides ingestion",
            ),
            StageDTO(
                weight=5,
                state=StageStateEnum.NOT_STARTED,
                name="Old transcriptions removal",
            ),
            StageDTO(
                weight=5,
                state=StageStateEnum.NOT_STARTED,
                name="Transcription chunking",
            ),
            StageDTO(
                weight=10,
                state=StageStateEnum.NOT_STARTED,
                name="Transcription summarization",
            ),
            StageDTO(
                weight=10,
                state=StageStateEnum.NOT_STARTED,
                name="Transcription ingestion",
            ),
            StageDTO(
                weight=30,
                state=StageStateEnum.NOT_STARTED,
                name="Lecture unit summary ingestion",
            ),
        ]
        status = IngestionStatusUpdateDTO(stages=stages, id=lecture_unit_id)
        stage = stages[current_stage_index]
        super().__init__(url, run_id, status, stage, current_stage_index)
