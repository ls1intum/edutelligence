import logging
from typing import List, Optional

from ...domain.ingestion.ingestion_status_update_dto import (
    IngestionStatusUpdateDTO,
)
from ...domain.status.stage_dto import StageDTO
from ...domain.status.stage_state_dto import StageStateEnum
from .status_update import StatusCallback

logger = logging.getLogger(__name__)


class TranscriptionIngestionStatus(StatusCallback):
    """
    Callback class for updating the status of a Transcription ingestion Pipeline run.
    """

    def __init__(
        self,
        run_id: str,
        base_url: str,
        initial_stages: Optional[List[StageDTO]] = None,
        lecture_unit_id: Optional[int] = None,
    ):
        url = f"{base_url}/api/iris/internal/webhooks/ingestion/transcriptions/runs/{run_id}/status"

        current_stage_index = len(initial_stages) if initial_stages else 0
        stages = initial_stages or []
        stages += [
            StageDTO(
                weight=10,
                state=StageStateEnum.NOT_STARTED,
                name="Remove old transcription",
            ),
            StageDTO(
                weight=10,
                state=StageStateEnum.NOT_STARTED,
                name="Chunk transcription",
            ),
            StageDTO(
                weight=40,
                state=StageStateEnum.NOT_STARTED,
                name="Summarize transcription",
            ),
            StageDTO(
                weight=20,
                state=StageStateEnum.NOT_STARTED,
                name="Ingest transcription",
            ),
            StageDTO(
                weight=20,
                state=StageStateEnum.NOT_STARTED,
                name="Ingest lecture unit summary",
            ),
        ]
        status = IngestionStatusUpdateDTO(stages=stages, id=lecture_unit_id)
        stage = stages[current_stage_index]
        super().__init__(url, run_id, status, stage, current_stage_index)
