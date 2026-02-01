from typing import Optional

from pydantic import Field

from iris.domain.data.course_dto import CourseDTO
from iris.domain.data.lecture_dto import PyrisLectureDTO
from iris.domain.data.post_dto import PostDTO
from iris.domain.data.programming_exercise_dto import ProgrammingExerciseDTO
from iris.domain.data.text_exercise_dto import TextExerciseDTO
from iris.domain.data.user_dto import UserDTO
from iris.domain.pipeline_execution_dto import PipelineExecutionDTO


class AutonomousTutorPipelineExecutionDto(PipelineExecutionDTO):
    course: CourseDTO
    post: PostDTO
    user: UserDTO
    programming_exercise: Optional[ProgrammingExerciseDTO] = Field(
        default=None, alias="programmingExercise"
    )
    text_exercise: Optional[TextExerciseDTO] = Field(default=None, alias="textExercise")
    lecture: Optional[PyrisLectureDTO] = Field(default=None)
