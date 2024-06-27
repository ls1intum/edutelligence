from typing import Optional

from pydantic import Field

from ..chat_pipeline_execution_dto import ChatPipelineExecutionDTO
from ...data.exercise_with_submissions_dto import ExerciseWithSubmissionsDTO
from ...data.extended_course_dto import ExtendedCourseDTO
from ...data.metrics.competency_jol_dto import CompetencyJolDTO
from ...data.metrics.student_metrics_dto import StudentMetricsDTO


class CourseChatPipelineExecutionDTO(ChatPipelineExecutionDTO):
    course: ExtendedCourseDTO
    metrics: Optional[StudentMetricsDTO]
    competency_jol: Optional[CompetencyJolDTO] = Field(None, alias="competencyJol")
    finished_exercise: Optional[ExerciseWithSubmissionsDTO] = Field(
        None, alias="finishedExercise"
    )
