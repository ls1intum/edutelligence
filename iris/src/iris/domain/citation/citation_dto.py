from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class CitationDTO(BaseModel):
    """Structured citation metadata for chat responses."""

    model_config = ConfigDict(populate_by_name=True)

    index: int
    type: Literal["video", "slides", "faq"]
    link: Optional[str] = None
    lecture_name: Optional[str] = Field(alias="lectureName", default=None)
    unit_name: Optional[str] = Field(alias="unitName", default=None)
    faq_question_title: Optional[str] = Field(alias="faqQuestionTitle", default=None)
    summary: Optional[str] = None
    keyword: Optional[str] = None
    page: Optional[int] = None
    start_time: Optional[str] = Field(alias="startTime", default=None)
    end_time: Optional[str] = Field(alias="endTime", default=None)
    start_time_seconds: Optional[int] = Field(alias="startTimeSeconds", default=None)
    end_time_seconds: Optional[int] = Field(alias="endTimeSeconds", default=None)
