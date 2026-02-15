from typing import Any, Optional

from pydantic import Field

from ...data.course_dto import CourseDTO
from ...data.metrics.student_metrics_dto import StudentMetricsDTO
from ...event.pyris_event_dto import PyrisEventDTO
from ..chat_pipeline_execution_dto import ChatPipelineExecutionDTO


class CourseChatPipelineExecutionDTO(ChatPipelineExecutionDTO):
    course: CourseDTO
    metrics: Optional[StudentMetricsDTO]
    event_payload: Optional[PyrisEventDTO[Any]] = Field(None, alias="eventPayload")
    custom_instructions: Optional[str] = Field(default="", alias="customInstructions")
