from typing import Optional

from pydantic import Field

from iris.domain import ChatPipelineExecutionDTO
from iris.domain.data.course_dto import CourseDTO
from iris.domain.data.post_dto import PostDTO
from iris.domain.data.programming_exercise_dto import ProgrammingExerciseDTO
from iris.domain.data.programming_submission_dto import (
    ProgrammingSubmissionDTO,
)
from iris.domain.data.text_exercise_dto import TextExerciseDTO


class CommunicationTutorSuggestionPipelineExecutionDTO(ChatPipelineExecutionDTO):
    course: CourseDTO
    lecture_id: Optional[int] = Field(default=None, alias="lectureId")
    post: PostDTO
    text_exercise: Optional[TextExerciseDTO] = Field(
        default=None, alias="textExerciseDTO"
    )
    submission: Optional[ProgrammingSubmissionDTO] = None
    programming_exercise: Optional[ProgrammingExerciseDTO] = Field(
        default=None, alias="programmingExerciseDTO"
    )
