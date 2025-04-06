from typing import Optional

from iris.domain import ChatPipelineExecutionDTO
from iris.domain.data.course_dto import CourseDTO
from iris.domain.data.post_dto import PostDTO


class CommunicationTutorSuggestionPipelineExecutionDTO(ChatPipelineExecutionDTO):
    course: Optional[CourseDTO] = None
    exercise_id: Optional[int] = None
    post: PostDTO = None
