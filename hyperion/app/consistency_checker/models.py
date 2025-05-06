"""
Data models for the consistency checker module.
"""

from typing import Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class ProgrammingExercise(BaseModel):
    """
    Data model representing a programming exercise with problem statement and repository files.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: Optional[int] = Field(None, description="The identifier of the exercise")
    name: Optional[str] = Field(None, description="The name of the exercise")
    programming_language: Optional[str] = Field(None, description="The programming language of the exercise")
    problem_statement: str = Field(
        ..., description="The description of the exercise containing tasks"
    )
    template_repository: Dict[str, str] = Field(
        ...,
        description="Files in the template repository, mapping file paths to content",
    )
    solution_repository: Dict[str, str] = Field(
        ...,
        description="Files in the solution repository, mapping file paths to content",
    )
    test_repository: Optional[Dict[str, str]] = Field(
        default_factory=dict,
        description="Files in the test repository, mapping file paths to content",
    )
    start_date: Optional[datetime] = Field(None, description="The start date of the exercise")
    end_date: Optional[datetime] = Field(None, description="The end date of the exercise")
    max_points: Optional[float] = Field(None, description="The maximum points achievable for the exercise")
    bonus_points: Optional[float] = Field(0.0, description="The bonus points achievable for the exercise")


class ConsistencyIssue(BaseModel):
    """
    Data model representing a consistency issue found in the exercise.
    """

    file_path: str = Field(..., description="Path to the file with consistency issue")
    description: str = Field(..., description="Description of the consistency issue")


class ConsistencyCheckRequest(BaseModel):
    """
    Request model for consistency checking.
    """

    exercise: ProgrammingExercise = Field(
        ..., description="The programming exercise to check for consistency"
    )


class ConsistencyCheckResponse(BaseModel):
    """
    Response model for consistency checking.
    """

    issues: List[ConsistencyIssue] = Field(
        default_factory=list, description="List of consistency issues found"
    )
    summary: str = Field("", description="A summary of all consistency issues")
    status: str = Field("success", description="Status of the consistency check")
