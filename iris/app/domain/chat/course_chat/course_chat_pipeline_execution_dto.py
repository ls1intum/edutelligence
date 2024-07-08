from typing import Optional, Any, Union

from pydantic import Field

from ..chat_pipeline_execution_dto import ChatPipelineExecutionDTO
from ...data.exercise_with_submissions_dto import ExerciseWithSubmissionsDTO
from ...data.extended_course_dto import ExtendedCourseDTO
from ...data.metrics.competency_jol_dto import CompetencyJolDTO
from ...data.metrics.student_metrics_dto import StudentMetricsDTO
from ...event.pyris_event_dto import PyrisEventDTO


class CourseChatPipelineExecutionDTO(ChatPipelineExecutionDTO):
    course: ExtendedCourseDTO
    metrics: Optional[StudentMetricsDTO]
    event_payload: Optional[PyrisEventDTO[Any]] = Field(None, alias="eventPayload")
