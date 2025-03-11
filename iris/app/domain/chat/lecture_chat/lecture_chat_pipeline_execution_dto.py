from typing import Optional

from app.domain import ChatPipelineExecutionDTO
from pydantic import Field


class LectureChatPipelineExecutionDTO(ChatPipelineExecutionDTO):
    course_id: int = Field(alias="courseId")
    lecture_id: Optional[int] = Field(alias="lectureId", default=None)
    lecture_unit_id: Optional[int] = Field(alias="lectureUnitId", default=None)
