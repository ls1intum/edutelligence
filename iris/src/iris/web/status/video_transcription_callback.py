from typing import List, Optional

from iris.common.logging_config import get_logger
from iris.domain.status.stage_dto import StageDTO
from iris.domain.status.stage_state_dto import StageStateEnum
from iris.domain.transcription.video_transcription_status_dto import (
    VideoTranscriptionStatusUpdateDTO,
)
from iris.web.status.status_update import StatusCallback

logger = get_logger(__name__)


class VideoTranscriptionCallback(StatusCallback):
    """
    Callback class for updating the status of a Video Transcription Pipeline run.

    Stages:
    1. Downloading video (weight=10)
    2. Extracting audio (weight=10)
    3. Transcribing (weight=30)
    4. Detecting slides (weight=25)
    5. Aligning (weight=20)
    6. Finalizing (weight=5)
    """

    def __init__(
        self,
        run_id: str,
        base_url: str,
        initial_stages: Optional[List[StageDTO]] = None,
        lecture_unit_id: Optional[int] = None,
    ):
        url = (
            f"{base_url}/api/iris/internal/webhooks/transcription/runs/{run_id}/status"
        )

        current_stage_index = len(initial_stages) if initial_stages else 0
        stages = initial_stages or []
        stages += [
            StageDTO(
                weight=10,
                state=StageStateEnum.NOT_STARTED,
                name="Downloading video",
            ),
            StageDTO(
                weight=10,
                state=StageStateEnum.NOT_STARTED,
                name="Extracting audio",
            ),
            StageDTO(
                weight=30,
                state=StageStateEnum.NOT_STARTED,
                name="Transcribing",
            ),
            StageDTO(
                weight=25,
                state=StageStateEnum.NOT_STARTED,
                name="Detecting slides",
            ),
            StageDTO(
                weight=20,
                state=StageStateEnum.NOT_STARTED,
                name="Aligning",
            ),
            StageDTO(
                weight=5,
                state=StageStateEnum.NOT_STARTED,
                name="Finalizing",
            ),
        ]
        status = VideoTranscriptionStatusUpdateDTO(
            stages=stages, lecture_unit_id=lecture_unit_id
        )
        stage = stages[current_stage_index]
        super().__init__(url, run_id, status, stage, current_stage_index)
