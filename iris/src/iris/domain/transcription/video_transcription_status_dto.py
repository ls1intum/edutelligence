from typing import Optional

from pydantic import Field

from iris.domain.status.status_update_dto import StatusUpdateDTO


class VideoTranscriptionStatusUpdateDTO(StatusUpdateDTO):
    """Status update DTO for video transcription pipeline callbacks to Artemis."""

    result: Optional[str] = Field(
        default=None, description="Final transcription result as JSON string"
    )
    lecture_unit_id: Optional[int] = Field(
        default=None, alias="lectureUnitId", description="Lecture unit ID"
    )

    class Config:
        populate_by_name = True
