from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from iris.domain.data.competency_dto import CompetencyDTO
from iris.domain.data.exam_dto import ExamDTO
from iris.domain.data.exercise_with_submissions_dto import (
    ExerciseWithSubmissionsDTO,
)
from iris.domain.data.lecture_dto import PyrisLectureDTO


class CourseDTO(BaseModel):
    """
    Data Transfer Object representing a course and its configuration.
    """

    id: int
    name: Optional[str] = None
    description: Optional[str] = None
    start_time: Optional[datetime] = Field(alias="startTime", default=None)
    end_time: Optional[datetime] = Field(alias="endTime", default=None)
    # A plain string on purpose: Artemis adds programming languages over time, and the value
    # is only shown to the agent as course information. Validating it against a list would
    # reject the whole chat request for every course that uses a language missing from it.
    default_programming_language: Optional[str] = Field(
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
    lectures: List[PyrisLectureDTO] = Field(alias="lectures", default=[])
    student_analytics_dashboard_enabled: bool = Field(
        alias="studentAnalyticsDashboardEnabled", default=False
    )
