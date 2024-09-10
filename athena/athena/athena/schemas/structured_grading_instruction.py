from abc import ABC
import hashlib
from typing import List, Optional
from pydantic import BaseModel, Field

from .schema import Schema


class StructuredGradingInstructionCriterion(Schema, ABC):
    """Part of a grading criterion (called "GradingInstruction" in LMS)."""
    id: int = Field(example=1)
    credits: float = Field(description="The number of credits assigned for this feedback.", example=1.0)
    grading_scale: str = Field(description="The grading outcome for this instruction.", example="Weak example", default="")
    instruction_description: str = Field(description="Description of how to use this grading instruction.", example="Some instructions", default="")
    feedback: str = Field(description="Description of the feedback to provide.", example="Nicely done!", default="")
    usage_count: int = Field(ge=0, description="The usage limit for this structured grading instruction. 0 means unlimited.", example=3, default=0)


class StructuredGradingInstructionGroup(Schema, ABC):
    """A structured grading criterion for assessing an exercise."""
    id: int = Field(example=1)
    title: Optional[str] = Field(None, example="Some instructions")
    structured_grading_instructions: List[StructuredGradingInstructionCriterion] = Field(
        [], example=[{"credits": 1.0, "gradingScale": "Good", "instructionDescription": "Some instructions", "feedback": "Nicely done!", "usageCount": 1},
                     {"credits": 0.0, "gradingScale": "Bad", "instructionDescription": "Some instructions", "feedback": "Try again!", "usageCount": 0}])

class StructuredGradingInstruction(Schema, ABC):
    id: Optional[int] = Field(default=None, example=1)
    exercise_id: int = Field(..., example=1)
    cache_key: str = Field(..., example="exercise_1_criteria_v1")
    criteria: List[StructuredGradingInstructionGroup]
    
    @staticmethod
    def generate_cache_key(problem_statement: Optional[str] = None, example_solution: Optional[str] = None) -> str:
        """Generates a cache key using a hash of the problem statement and example solution (if present)."""
        data = (problem_statement or "") + (example_solution or "")
        return hashlib.md5(data.encode()).hexdigest()

    
    class Config:
        orm_mode = True

class StructuredGradingInstructionWrapper(BaseModel):
    criteria: List[StructuredGradingInstructionGroup]