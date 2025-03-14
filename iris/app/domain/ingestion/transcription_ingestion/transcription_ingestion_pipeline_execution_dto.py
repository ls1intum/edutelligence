from typing import List, Optional

from pydantic import Field

from app.domain import PipelineExecutionDTO, PipelineExecutionSettingsDTO
from app.domain.data.metrics.transcription_dto import TranscriptionWebhookDTO
from app.domain.status.stage_dto import StageDTO


class TranscriptionIngestionPipelineExecutionDto(PipelineExecutionDTO):
    transcription: TranscriptionWebhookDTO
    lectureUnitId: int
    settings: Optional[PipelineExecutionSettingsDTO]
    initial_stages: Optional[List[StageDTO]] = Field(
        default=None, alias="initialStages"
    )
