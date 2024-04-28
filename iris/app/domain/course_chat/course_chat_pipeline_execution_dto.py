from typing import List, Optional

from pydantic import Field

from ...domain.pyris_message import PyrisMessage
from ...domain import PipelineExecutionDTO
from ...domain.data.course_dto import CourseDTO
from ...domain.data.user_dto import UserDTO


class CourseChatPipelineExecutionDTO(PipelineExecutionDTO):
    user: Optional[UserDTO] = None
    course: CourseDTO
    chat_history: List[PyrisMessage] = Field(alias="chatHistory", default=[])
