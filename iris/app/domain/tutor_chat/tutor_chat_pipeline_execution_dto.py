from typing import List, Optional

from pydantic import Field

from ...domain.pyris_message import PyrisMessage
from ...domain import PipelineExecutionDTO
from ...domain.data.course_dto import CourseDTO
from ...domain.data.programming_exercise_dto import ProgrammingExerciseDTO
from ...domain.data.user_dto import UserDTO
from ...domain.data.submission_dto import SubmissionDTO


class TutorChatPipelineExecutionDTO(PipelineExecutionDTO):
    submission: Optional[SubmissionDTO] = None
    exercise: ProgrammingExerciseDTO
    course: CourseDTO
    chat_history: List[PyrisMessage] = Field(alias="chatHistory", default=[])
    user: Optional[UserDTO] = None
