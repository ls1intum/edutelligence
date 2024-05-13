from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

class ExerciseType(str, Enum):
    PROGRAMMING = "PROGRAMMING"
    QUIZ = "QUIZ"
    MODELING = "MODELING"
    TEXT = "TEXT"


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


class ExerciseDTO(BaseModel):
    id: int = Field(alias="id")
    title: str = Field(alias="title")
    type: ExerciseType = Field(alias="type")
    mode: ExerciseMode = Field(alias="mode")
    max_points: Optional[float] = Field(alias="maxPoints")
    bonus_points: Optional[float] = Field(alias="bonusPoints")
    difficulty_level: Optional[DifficultyLevel] = Field(alias="difficultyLevel")
    release_date: Optional[datetime] = Field(alias="releaseDate")
    due_date: Optional[datetime] = Field(alias="dueDate")
    inclusion_mode: Optional[IncludedInOverallScore] = Field(alias="inclusionMode")
    presentation_score_enabled: Optional[bool] = Field(alias="presentationScoreEnabled")
