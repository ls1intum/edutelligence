from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field

from app.domain.data.competency_dto import CompetencyDTO
from app.domain.data.exam_dto import ExamDTO
from app.domain.data.exercise_with_submissions_dto import ExerciseWithSubmissionsDTO
from app.domain.data.programming_exercise_dto import ProgrammingLanguage


class ExtendedCourseDTO(BaseModel):
    id: int = Field(alias="id")
    name: str = Field(alias="name", default=None)
    description: Optional[str] = Field(alias="description", default=None)
    start_time: Optional[datetime] = Field(alias="startTime", default=None)
    end_time: Optional[datetime] = Field(alias="endTime", default=None)
    default_programming_language: Optional[ProgrammingLanguage] = Field(
        alias="defaultProgrammingLanguage", default=None
    )
    max_complaints: Optional[int] = Field(alias="maxComplaints", default=None)
    max_team_complaints: Optional[int] = Field(alias="maxTeamComplaints", default=None)
    max_complaint_time_days: Optional[int] = Field(
        alias="maxComplaintTimeDays", default=None
    )
    max_request_more_feedback_time_days: Optional[int] = Field(
        alias="maxRequestMoreFeedbackTimeDays", default=None
    )
    max_points: Optional[int] = Field(alias="maxPoints", default=None)
    presentation_score: Optional[int] = Field(alias="presentationScore", default=None)
    exercises: List[ExerciseWithSubmissionsDTO] = Field(alias="exercises", default=[])
    exams: List[ExamDTO] = Field(alias="exams", default=[])
    competencies: List[CompetencyDTO] = Field(alias="competencies", default=[])
