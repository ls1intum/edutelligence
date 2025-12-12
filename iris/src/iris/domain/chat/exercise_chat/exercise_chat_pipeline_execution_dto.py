from typing import Any, Optional

from pydantic import Field

from iris.domain.chat.chat_pipeline_execution_dto import (
    ChatPipelineExecutionDTO,
)
from iris.domain.data.course_dto import CourseDTO
from iris.domain.data.programming_exercise_dto import ProgrammingExerciseDTO
from iris.domain.data.programming_submission_dto import (
    ProgrammingSubmissionDTO,
)
from iris.domain.event.pyris_event_dto import PyrisEventDTO


class ExerciseChatPipelineExecutionDTO(ChatPipelineExecutionDTO):
    submission: Optional[ProgrammingSubmissionDTO] = None
    exercise: ProgrammingExerciseDTO
    course: CourseDTO
    event_payload: Optional[PyrisEventDTO[Any]] = Field(None, alias="eventPayload")
    custom_instructions: Optional[str] = Field(default="", alias="customInstructions")
