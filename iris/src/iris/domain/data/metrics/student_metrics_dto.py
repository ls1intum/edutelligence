from typing import Optional

from pydantic import BaseModel, Field

from iris.domain.data.metrics.competency_student_metrics_dto import (
    CompetencyStudentMetricsDTO,
)
from iris.domain.data.metrics.exercise_student_metrics_dto import (
    ExerciseStudentMetricsDTO,
)
from iris.domain.data.metrics.lecture_unit_student_metrics_dto import (
    LectureUnitStudentMetricsDTO,
)


class StudentMetricsDTO(BaseModel):
    """StudentMetricsDTO aggregates various student performance metrics, including exercise, lecture unit, and
    competency metrics."""

    exercise_metrics: Optional[ExerciseStudentMetricsDTO] = Field(
        None, alias="exerciseMetrics"
    )
    lecture_unit_student_metrics_dto: Optional[LectureUnitStudentMetricsDTO] = Field(
        None, alias="lectureUnitStudentMetricsDTO"
    )
    competency_metrics: Optional[CompetencyStudentMetricsDTO] = Field(
        None, alias="competencyMetrics"
    )

    class Config:
        populate_by_name = True
