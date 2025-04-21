from typing import Optional

from iris.domain import ChatPipelineExecutionDTO
from iris.domain.data.course_dto import CourseDTO
from iris.domain.data.post_dto import PostDTO
from iris.domain.data.programming_exercise_dto import ProgrammingExerciseDTO
from iris.domain.data.text_exercise_dto import TextExerciseDTO


class CommunicationTutorSuggestionPipelineExecutionDTO(ChatPipelineExecutionDTO):
    course: CourseDTO
    exercise_id: Optional[int] = None
    lecture_id: Optional[int] = None
    lecture_unit_id: Optional[int] = None
    post: PostDTO
    textExerciseDTO: Optional[TextExerciseDTO] = None
    programmingExerciseDTO: Optional[ProgrammingExerciseDTO] = None
