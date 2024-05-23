from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field

from app.domain.data.competency_dto import CompetencyDTO
from app.domain.data.exam_dto import ExamDTO
from app.domain.data.exercise_with_submissions_dto import ExerciseWithSubmissionsDTO
from app.domain.data.programming_exercise_dto import ProgrammingLanguage


class ExtendedCourseDTO(BaseModel):
    id: int = Field(alias="id")
    name: str = Field(alias="name")
    description: Optional[str] = Field(alias="description")
    start_time: Optional[datetime] = Field(alias="startTime")
    end_time: Optional[datetime] = Field(alias="endTime")
    default_programming_language: Optional[ProgrammingLanguage] = Field(alias="defaultProgrammingLanguage")
    max_complaints: Optional[int] = Field(alias="maxComplaints")
    max_team_complaints: Optional[int] = Field(alias="maxTeamComplaints")
    max_complaint_time_days: Optional[int] = Field(alias="maxComplaintTimeDays")
    max_request_more_feedback_time_days: Optional[int] = Field(alias="maxRequestMoreFeedbackTimeDays")
    max_points: Optional[int] = Field(alias="maxPoints")
    presentation_score: Optional[int] = Field(alias="presentationScore")
    exercises: List[ExerciseWithSubmissionsDTO] = Field(alias="exercises", default=[])
    exams: List[ExamDTO] = Field(alias="exams", default=[])
    competencies: List[CompetencyDTO] = Field(alias="competencies", default=[])
