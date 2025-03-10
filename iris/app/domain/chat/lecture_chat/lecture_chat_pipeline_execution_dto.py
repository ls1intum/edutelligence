from app.domain import ChatPipelineExecutionDTO
from app.domain.data.course_dto import CourseDTO


class LectureChatPipelineExecutionDTO(ChatPipelineExecutionDTO):
    course_id: int
    lecture_id: Optional[int] = None
    lecture_unit_id: Optional[int] = None
