from typing import Optional, Generic, TypeVar

from pydantic import Field

from ..chat_pipeline_execution_dto import ChatPipelineExecutionDTO
from ...data.exercise_with_submissions_dto import ExerciseWithSubmissionsDTO
from ...data.extended_course_dto import ExtendedCourseDTO
from ...data.metrics.student_metrics_dto import StudentMetricsDTO
from ...event.pyris_event_dto import PyrisEventDTO

T = TypeVar("T")


class CourseChatPipelineExecutionDTO(ChatPipelineExecutionDTO, Generic[T]):
    course: ExtendedCourseDTO
    metrics: Optional[StudentMetricsDTO]
    event_payload: Optional[PyrisEventDTO[T]] = Field(None, alias="eventPayload")
