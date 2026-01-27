from typing import Optional

from pydantic import Field

from iris.domain.status.status_update_dto import StatusUpdateDTO


class AutonomousTutorPipelineStatusUpdateDTO(StatusUpdateDTO):
    """
    This DTO is sent back to Artemis with the generated response and metadata
    about whether the response should be posted directly or queued for review.
    - result: The generated response to the student's post.
    - should_post_directly: Whether the response should be posted directly to the student.
    - confidence: Confidence score (0.0 to 1.0) indicating how confident the model is in the response.
    """

    result: Optional[str] = None
    should_post_directly: bool = Field(default=False, alias="shouldPostDirectly")
    confidence: Optional[float] = Field(default=None)
