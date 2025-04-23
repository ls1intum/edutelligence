from typing import Optional

from pydantic import Field

from iris.domain import ChatPipelineExecutionDTO
from iris.domain.data.course_dto import CourseDTO
from iris.domain.data.post_dto import PostDTO
from iris.domain.data.programming_exercise_dto import ProgrammingExerciseDTO
from iris.domain.data.text_exercise_dto import TextExerciseDTO


class CommunicationTutorSuggestionPipelineExecutionDTO(ChatPipelineExecutionDTO):
    course: CourseDTO
    lecture_id: Optional[int] = Field(default=None, alias="lectureId")
    lecture_unit_ids: Optional[list[int]] = Field(default=None, alias="lectureUnitIds")
    post: PostDTO
    textExerciseDTO: Optional[TextExerciseDTO] = None
    programmingExerciseDTO: Optional[ProgrammingExerciseDTO] = None
