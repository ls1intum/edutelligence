from typing import Optional

from pydantic import Field

from ..chat_pipeline_execution_base_data_dto import ChatPipelineExecutionBaseDataDTO
from ..chat_pipeline_execution_dto import ChatPipelineExecutionDTO
from ...data.extended_course_dto import ExtendedCourseDTO
from ...data.metrics.competency_jol_dto import CompetencyJolDTO
from ...data.metrics.student_metrics_dto import StudentMetricsDTO


class CourseChatPipelineExecutionDTO(ChatPipelineExecutionDTO):
    course: ExtendedCourseDTO
    metrics: Optional[StudentMetricsDTO]
    competency_jol: Optional[CompetencyJolDTO] = Field(None, alias="competencyJol")
