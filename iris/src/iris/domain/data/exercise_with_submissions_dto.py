from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from iris.domain.data.simple_submission_dto import SimpleSubmissionDTO


class ExerciseType(str, Enum):
    PROGRAMMING = "PROGRAMMING"
    QUIZ = "QUIZ"
    MODELING = "MODELING"
    TEXT = "TEXT"
    FILE_UPLOAD = "FILE_UPLOAD"

    @classmethod
    def _missing_(cls, value):
        """Allow case-insensitive lookup"""
        if isinstance(value, str):
            value = value.upper().replace("-", "_")
            for member in cls:
                if member.value == value:
                    return member
        return None


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


class ExerciseWithSubmissionsDTO(BaseModel):
    """ExerciseWithSubmissionsDTO represents an exercise along with its associated submissions and key metadata such as
    type, mode, points, dates, and difficulty level."""

    id: int = Field(alias="id")
    url: Optional[str] = Field(alias="url", default=None)
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
    problem_statement: Optional[str] = Field(alias="problemStatement", default=None)

    class Config:
        require_by_default = False
