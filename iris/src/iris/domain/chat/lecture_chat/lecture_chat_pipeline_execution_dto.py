from typing import Optional

from pydantic import Field

from iris.domain import ChatPipelineExecutionDTO


class LectureChatPipelineExecutionDTO(ChatPipelineExecutionDTO):
    course_id: int = Field(alias="courseId")
    lecture_id: Optional[int] = Field(alias="lectureId", default=None)
    lecture_unit_id: Optional[int] = Field(alias="lectureUnitId", default=None)
