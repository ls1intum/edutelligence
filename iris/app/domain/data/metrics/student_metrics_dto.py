from typing import Optional
from pydantic import Field, BaseModel
from app.domain.data.metrics.competency_student_metrics_dto import CompetencyStudentMetricsDTO
from app.domain.data.metrics.exercise_student_metrics_dto import ExerciseStudentMetricsDTO
from app.domain.data.metrics.lecture_unit_student_metrics_dto import LectureUnitStudentMetricsDTO


class StudentMetricsDTO(BaseModel):
    exercise_metrics: Optional[ExerciseStudentMetricsDTO] = Field(None, alias="exerciseMetrics")
    lecture_unit_student_metrics_dto: Optional[LectureUnitStudentMetricsDTO] = Field(None,
                                                                                     alias="lectureUnitStudentMetricsDTO")
    competency_metrics: Optional[CompetencyStudentMetricsDTO] = Field(None, alias="competencyMetrics")

    class Config:
        allow_population_by_field_name = True
