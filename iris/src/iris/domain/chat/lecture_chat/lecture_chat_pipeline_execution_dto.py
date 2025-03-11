from iris.domain import ChatPipelineExecutionDTO
from iris.domain.data.course_dto import CourseDTO


class LectureChatPipelineExecutionDTO(ChatPipelineExecutionDTO):
    course: CourseDTO
