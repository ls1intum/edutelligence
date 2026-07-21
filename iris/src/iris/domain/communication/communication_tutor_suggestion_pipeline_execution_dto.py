from typing import Optional

from pydantic import Field

from iris.common.pyris_message import PyrisMessage
from iris.domain.data.course_dto import CourseDTO
from iris.domain.data.post_dto import PostDTO
from iris.domain.data.programming_exercise_dto import ProgrammingExerciseDTO
from iris.domain.data.programming_submission_dto import ProgrammingSubmissionDTO
from iris.domain.data.text_exercise_dto import TextExerciseDTO
from iris.domain.data.user_dto import UserDTO
from iris.domain.pipeline_execution_dto import PipelineExecutionDTO


class CommunicationTutorSuggestionPipelineExecutionDTO(PipelineExecutionDTO):
    """Exact Python counterpart of Artemis' tutor-suggestion wire record."""

    course: CourseDTO
    post: PostDTO
    chat_history: list[PyrisMessage] = Field(alias="chatHistory", default_factory=list)
    user: UserDTO
    lecture_id: Optional[int] = Field(default=None, alias="lectureId")
    text_exercise: Optional[TextExerciseDTO] = Field(
        default=None, alias="textExerciseDTO"
    )
    submission: Optional[ProgrammingSubmissionDTO] = None
    programming_exercise: Optional[ProgrammingExerciseDTO] = Field(
        default=None, alias="programmingExerciseDTO"
    )
