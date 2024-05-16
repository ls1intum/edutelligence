from typing import Optional

from pydantic import Field, BaseModel

from app.domain.data.metrics.competency_student_metrics_dto import CompetencyStudentMetricsDTO
from app.domain.data.metrics.exercise_student_metrics_dto import ExerciseStudentMetricsDTO
from app.domain.data.metrics.lecture_unit_student_metrics_dto import LectureUnitStudentMetricsDTO


class StudentMetricsDTO(BaseModel):
    exercise_metrics: Optional[ExerciseStudentMetricsDTO] = Field(alias="exerciseMetrics")
    lecture_unit_student_metrics_dto: LectureUnitStudentMetricsDTO = Field(alias="lectureUnitStudentMetricsDTO")
    competency_metrics: CompetencyStudentMetricsDTO = Field(alias="competencyMetrics")

