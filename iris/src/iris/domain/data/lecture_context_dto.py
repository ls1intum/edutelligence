from typing import Literal, Union

from pydantic import BaseModel, Field


class VideoContextDTO(BaseModel):
    """Context about a video lecture unit the student is currently viewing.

    Sent from Artemis as part of the optional context array.
    """

    type: Literal["video"]
    lecture_unit_id: int = Field(alias="lectureUnitId", gt=0)
    timestamp: float = Field(ge=0)  # in seconds

    class Config:
        populate_by_name = True  # Allow both snake_case and camelCase


class SlidesContextDTO(BaseModel):
    """Context about a slides/PDF lecture unit the student is currently viewing.

    Sent from Artemis as part of the optional context array.
    """

    type: Literal["slides"]
    lecture_unit_id: int = Field(alias="lectureUnitId", gt=0)
    page: int = Field(ge=1)  # PDF pages start at 1

    class Config:
        populate_by_name = True  # Allow both snake_case and camelCase


class FullscreenContextDTO(BaseModel):
    """Context indicating the student is viewing a lecture unit in fullscreen mode.

    Sent from Artemis as part of the optional context array.
    Used for RAG filtering to scope retrieval to the specific lecture unit.
    """

    type: Literal["fullscreen"]
    lecture_unit_id: int = Field(alias="lectureUnitId", gt=0)

    class Config:
        populate_by_name = True  # Allow both snake_case and camelCase


# Union type for all structured context types
# pylint: disable=invalid-name
LectureContextDTO = Union[VideoContextDTO, SlidesContextDTO, FullscreenContextDTO]
