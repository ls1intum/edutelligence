from typing import List, Optional

from pydantic import Field

from iris.common.pyris_message import PyrisMessage
from iris.domain.data.course_dto import CourseDTO
from iris.domain.data.programming_exercise_dto import ProgrammingExerciseDTO
from iris.domain.data.programming_submission_dto import ProgrammingSubmissionDTO
from iris.domain.data.user_dto import UserDTO
from iris.domain.pipeline_execution_dto import PipelineExecutionDTO
from iris.domain.struggle.struggle_signal_dto import StruggleSignal


class StruggleInterventionPipelineExecutionDTO(PipelineExecutionDTO):
    struggle_signal: StruggleSignal = Field(alias="struggleSignal")
    programming_exercise: Optional[ProgrammingExerciseDTO] = Field(
        alias="programmingExercise", default=None
    )
    programming_exercise_submission: Optional[ProgrammingSubmissionDTO] = Field(
        alias="programmingExerciseSubmission", default=None
    )
    chat_history: List[PyrisMessage] = Field(alias="chatHistory", default_factory=list)
    course: Optional[CourseDTO] = Field(default=None)
    user: Optional[UserDTO] = Field(default=None)
