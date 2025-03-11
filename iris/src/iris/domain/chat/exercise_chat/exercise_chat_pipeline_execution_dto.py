from typing import Any, Optional

from app import PyrisEventDTO
from pydantic import Field

from src.iris.domain.chat.chat_pipeline_execution_dto import ChatPipelineExecutionDTO
from src.iris.domain.data.course_dto import CourseDTO
from src.iris.domain.data.programming_exercise_dto import ProgrammingExerciseDTO
from src.iris.domain.data.programming_submission_dto import ProgrammingSubmissionDTO


class ExerciseChatPipelineExecutionDTO(ChatPipelineExecutionDTO):
    submission: Optional[ProgrammingSubmissionDTO] = None
    exercise: ProgrammingExerciseDTO
    course: CourseDTO
    event_payload: Optional[PyrisEventDTO[Any]] = Field(None, alias="eventPayload")
