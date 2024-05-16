from typing import Optional

from ..chat_pipeline_execution_base_data_dto import ChatPipelineExecutionBaseDataDTO
from ..chat_pipeline_execution_dto import ChatPipelineExecutionDTO
from ...data.extended_course_dto import ExtendedCourseDTO
from ...data.metrics.student_metrics_dto import StudentMetricsDTO


class CourseChatPipelineExecutionDTO(ChatPipelineExecutionDTO):
    base: ChatPipelineExecutionBaseDataDTO
    course: ExtendedCourseDTO
    metrics: Optional[StudentMetricsDTO]
