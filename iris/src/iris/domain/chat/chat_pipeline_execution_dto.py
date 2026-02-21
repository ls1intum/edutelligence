from typing import Any, List, Optional, Union

from pydantic import Field

from iris.common.pyris_message import PyrisMessage
from iris.domain.data.course_dto import CourseDTO
from iris.domain.data.lecture_dto import PyrisLectureDTO
from iris.domain.data.metrics.student_metrics_dto import StudentMetricsDTO
from iris.domain.data.programming_exercise_dto import ProgrammingExerciseDTO
from iris.domain.data.programming_submission_dto import ProgrammingSubmissionDTO
from iris.domain.data.text_exercise_dto import TextExerciseDTO
from iris.domain.data.user_dto import UserDTO
from iris.domain.event.pyris_event_dto import PyrisEventDTO
from iris.domain.pipeline_execution_dto import PipelineExecutionDTO
from iris.pipeline.chat.chat_context import ChatContext


class ChatPipelineExecutionDTO(PipelineExecutionDTO):
    """
    Data Transfer Object for chat pipeline execution
    """

    context: ChatContext
    session_title: Optional[str] = Field(alias="sessionTitle", default=None)
    chat_history: List[PyrisMessage] = Field(alias="chatHistory", default=[])
    user: Optional[UserDTO]

    # Context-specific fields
    metrics: Optional[StudentMetricsDTO] = None
    event_payload: Optional[PyrisEventDTO[Any]] = Field(None, alias="eventPayload")
    custom_instructions: Optional[str] = Field(default="", alias="customInstructions")

    course: Optional[CourseDTO] = None
    exercise: Optional[Union[ProgrammingExerciseDTO, TextExerciseDTO]] = None

    lecture: Optional[PyrisLectureDTO] = None
    lecture_unit_id: Optional[int] = Field(alias="lectureUnitId", default=None)

    programming_exercise_submission: Optional[ProgrammingSubmissionDTO] = None
    text_exercise_submission: str = Field(alias="textExerciseSubmission", default="")
