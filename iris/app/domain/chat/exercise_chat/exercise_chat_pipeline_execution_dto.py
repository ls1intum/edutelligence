from typing import Optional, Any

from pydantic import Field

from app.domain.chat.chat_pipeline_execution_dto import ChatPipelineExecutionDTO
from app.domain.data.course_dto import CourseDTO
from app.domain.data.programming_exercise_dto import ProgrammingExerciseDTO
from app.domain.data.programming_submission_dto import ProgrammingSubmissionDTO
from app.domain.event.pyris_event_dto import PyrisEventDTO


class ExerciseChatPipelineExecutionDTO(ChatPipelineExecutionDTO):
    submission: Optional[ProgrammingSubmissionDTO] = None
    exercise: ProgrammingExerciseDTO
    course: CourseDTO
    event_payload: Optional[PyrisEventDTO[Any]] = Field(None, alias="eventPayload")
