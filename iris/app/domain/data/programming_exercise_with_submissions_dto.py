from datetime import datetime
from enum import Enum
from typing import Optional, List

from pydantic import BaseModel, Field

from app.domain.data.simple_submission_dto import SimpleSubmissionDTO


class ExerciseType(str, Enum):
    PROGRAMMING = "PROGRAMMING"
    QUIZ = "QUIZ"
    MODELING = "MODELING"
    TEXT = "TEXT"
    FILE_UPLOAD = "FILE_UPLOAD"


class ExerciseMode(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    TEAM = "TEAM"


class DifficultyLevel(str, Enum):
    EASY = "EASY"
    MEDIUM = "MEDIUM"
    HARD = "HARD"


class IncludedInOverallScore(str, Enum):
    INCLUDED_COMPLETELY = "INCLUDED_COMPLETELY"
    INCLUDED_AS_BONUS = "INCLUDED_AS_BONUS"
    NOT_INCLUDED = "NOT_INCLUDED"


class ProgrammingExerciseWithSubmissionsDTO(BaseModel):
    id: int = Field(alias="id")
    title: str = Field(alias="title")
    type: ExerciseType = Field(alias="type")
    mode: ExerciseMode = Field(alias="mode")
    max_points: Optional[float] = Field(alias="maxPoints", default=None)
    bonus_points: Optional[float] = Field(alias="bonusPoints", default=None)
    difficulty_level: Optional[DifficultyLevel] = Field(
        alias="difficultyLevel", default=None
    )
    release_date: Optional[datetime] = Field(alias="releaseDate", default=None)
    due_date: Optional[datetime] = Field(alias="dueDate", default=None)
    inclusion_mode: Optional[IncludedInOverallScore] = Field(
        alias="inclusionMode", default=None
    )
    presentation_score_enabled: Optional[bool] = Field(
        alias="presentationScoreEnabled", default=None
    )
    submissions: List[SimpleSubmissionDTO] = Field(default=[])

    class Config:
        require_by_default = False
