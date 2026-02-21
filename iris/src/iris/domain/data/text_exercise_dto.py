from typing import Optional

from pydantic import Field

from iris.domain.data.course_dto import CourseDTO
from iris.domain.data.exercise_dto import ExerciseDTO


class TextExerciseDTO(ExerciseDTO):
    course: CourseDTO  # TODO: entfernen ? -> Siehe ChatPipelineExecutionDTO
    example_solution: Optional[str] = Field(alias="exampleSolution", default=None)
