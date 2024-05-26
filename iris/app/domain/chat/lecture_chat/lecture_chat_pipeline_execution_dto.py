from app.domain import ChatPipelineExecutionDTO
from app.domain.data.course_dto import CourseDTO


class LectureChatPipelineExecutionDTO(ChatPipelineExecutionDTO):
    course: CourseDTO
