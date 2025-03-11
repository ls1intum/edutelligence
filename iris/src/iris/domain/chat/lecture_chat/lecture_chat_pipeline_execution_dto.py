from src.iris.domain import ChatPipelineExecutionDTO
from src.iris.domain.data.course_dto import CourseDTO


class LectureChatPipelineExecutionDTO(ChatPipelineExecutionDTO):
    course: CourseDTO
