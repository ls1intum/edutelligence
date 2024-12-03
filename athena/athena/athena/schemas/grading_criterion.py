from abc import ABC
from typing import List, Optional

from pydantic import BaseModel, Field

from .schema import Schema


class StructuredGradingInstruction(Schema, ABC):
    """Part of a grading criterion (called "GradingInstruction" in LMS)."""

    id: int = Field(example=1)
    credits: float = Field(description="The number of credits assigned for this feedback.", example=1.0)
    grading_scale: str = Field(description="The grading outcome for this instruction.", example="Weak example", default="")
    instruction_description: str = Field(description="Description of how to use this grading instruction.", example="Some instructions", default="")
    feedback: str = Field(description="Description of the feedback to provide.", example="Nicely done!", default="")
    usage_count: int = Field(ge=0, description="The usage limit for this structured grading instruction. 0 means unlimited.", example=3, default=0)


class GradingCriterion(Schema, ABC):
    """A structured grading criterion for assessing an exercise."""
    id: int = Field(example=1)
    title: Optional[str] = Field(None, example="Some instructions")
    structured_grading_instructions: List[StructuredGradingInstruction] = Field(
        [], example=[{"credits": 1.0, "gradingScale": "Good", "instructionDescription": "Some instructions", "feedback": "Nicely done!", "usageCount": 1},
                     {"credits": 0.0, "gradingScale": "Bad", "instructionDescription": "Some instructions", "feedback": "Try again!", "usageCount": 0}])