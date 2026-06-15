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
    """Execution payload for the struggle-intervention pipeline: the struggle
    signal plus the optional exercise/submission/history context to gate on."""

    struggle_signal: StruggleSignal = Field(alias="struggleSignal")
    programming_exercise: Optional[ProgrammingExerciseDTO] = Field(
        alias="programmingExercise", default=None
    )
    programming_exercise_submission: Optional[ProgrammingSubmissionDTO] = Field(
        alias="programmingExerciseSubmission", default=None
    )
    # Text-only USER/LLM exercise-chat history (so the gate does not repeat help
    # already given). Same shared assumption as the other agent pipelines; non-text
    # message shapes are not produced by this flow.
    chat_history: List[PyrisMessage] = Field(alias="chatHistory", default_factory=list)
    course: Optional[CourseDTO] = Field(default=None)
    user: Optional[UserDTO] = Field(default=None)
