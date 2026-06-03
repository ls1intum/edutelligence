from typing import Optional

from pydantic import Field

from iris.domain.status.status_update_dto import StatusUpdateDTO


class AutonomousTutorPipelineStatusUpdateDTO(StatusUpdateDTO):
    """
    This DTO is sent back to Artemis with the generated response and a confidence score.
    - result: The generated response to the student's post.
    - confidence: Confidence score (0.0 to 1.0) indicating how confident the model is in the response.
    """

    result: Optional[str] = None
    confidence: Optional[float] = Field(default=None)
