from typing import Literal, Optional, Union

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


class CombinedViewContextDTO(BaseModel):
    """Context indicating the student is viewing a lecture unit in the combined
    view.

    Sent from Artemis as part of the optional context array. It nests an optional
    ``slides`` and an optional ``video`` object describing the student's current
    position; at least one of them is always present. Used for RAG filtering to
    scope retrieval to the specific lecture unit.
    """

    type: Literal["combinedView"]
    slides: Optional[SlidesContextDTO] = None
    video: Optional[VideoContextDTO] = None

    class Config:
        populate_by_name = True  # Allow both snake_case and camelCase

    @property
    def lecture_unit_id(self) -> Optional[int]:
        """Derive the lecture unit id from the nested slides/video objects.

        Prefers ``slides.lecture_unit_id`` and falls back to
        ``video.lecture_unit_id``. Returns ``None`` only in the (unexpected)
        case where neither nested object is present.
        """
        if self.slides is not None:
            return self.slides.lecture_unit_id
        if self.video is not None:
            return self.video.lecture_unit_id
        return None


# Union type for all structured context types
# pylint: disable=invalid-name
LectureContextDTO = Union[VideoContextDTO, SlidesContextDTO, CombinedViewContextDTO]
