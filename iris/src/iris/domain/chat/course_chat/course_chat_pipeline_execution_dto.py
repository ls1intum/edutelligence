from typing import Optional

from pydantic import Field

from ...data.extended_course_dto import ExtendedCourseDTO
from ...data.metrics.student_metrics_dto import StudentMetricsDTO
from ..chat_pipeline_execution_dto import ChatPipelineExecutionDTO


class CourseChatPipelineExecutionDTO(ChatPipelineExecutionDTO):
    course: ExtendedCourseDTO
    metrics: Optional[StudentMetricsDTO]
    custom_instructions: Optional[str] = Field(default="", alias="customInstructions")
