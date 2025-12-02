from pydantic import Field

from iris.domain import PipelineExecutionDTO
from iris.domain.data.metrics.transcription_dto import TranscriptionWebhookDTO


class TranscriptionIngestionPipelineExecutionDto(PipelineExecutionDTO):
    transcription: TranscriptionWebhookDTO
    lecture_unit_id: int = Field(..., alias="lectureUnitId")
