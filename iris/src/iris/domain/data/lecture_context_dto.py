from typing import Literal, Union

from pydantic import BaseModel, Field


class VideoContextDTO(BaseModel):
    """Context about a video lecture unit the student is currently viewing.

    Sent from Artemis as part of the optional context array.
    """

    type: Literal["video"]
    lecture_unit_id: int = Field(alias="lectureUnitId")
    timestamp: float  # in seconds

    class Config:
        populate_by_name = True  # Allow both snake_case and camelCase


class SlidesContextDTO(BaseModel):
    """Context about a slides/PDF lecture unit the student is currently viewing.

    Sent from Artemis as part of the optional context array.
    """

    type: Literal["slides"]
    lecture_unit_id: int = Field(alias="lectureUnitId")
    page: int

    class Config:
        populate_by_name = True  # Allow both snake_case and camelCase


# Union type for all structured context types
# pylint: disable=invalid-name
LectureContextDTO = Union[VideoContextDTO, SlidesContextDTO]
