from typing import Optional

from pydantic import Field

from iris.domain import ChatPipelineExecutionDTO
from iris.domain.data.course_dto import CourseDTO
from iris.domain.data.lecture_dto import PyrisLectureDTO


class LectureChatPipelineExecutionDTO(ChatPipelineExecutionDTO):
    course: CourseDTO
    lecture: PyrisLectureDTO
    # in the current workflow this is not sent by Artemis
    lecture_unit_id: Optional[int] = Field(alias="lectureUnitId", default=None)
    custom_instructions: Optional[str] = Field(default="", alias="customInstructions")
    current_pdf_page: Optional[int] = Field(default=None, alias="currentPdfPage", ge=1)
    current_video_timestamp: Optional[float] = Field(
        default=None, alias="currentVideoTimestamp", ge=0
    )
