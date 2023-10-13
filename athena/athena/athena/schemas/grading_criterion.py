from abc import ABC
from typing import List

from pydantic import Field

from .schema import Schema


class StructuredGradingInstruction(Schema, ABC):
    """Part of a grading criterion (called "GradingInstruction" in Artemis)."""
    credits: float = Field(ge=0, example=1.0)
    grading_scale: str = Field(example="Good")
    instruction_description: str = Field("", example="Some instructions")
    feedback: str = Field("", example="Nicely done!")
    usage_count: int = Field(ge=0, example=1)


class GradingCriterion(Schema, ABC):
    """A structured grading criterion for assessing an exercise."""
    title: str = Field("", example="Some instructions")
    structured_grading_instructions: List[StructuredGradingInstruction] = Field(
        [], example=[{"credits": 1.0, "gradingScale": "Good", "instructionDescription": "Some instructions", "feedback": "Nicely done!", "usageCount": 1},
                     {"credits": 0.0, "gradingScale": "Bad", "instructionDescription": "Some instructions", "feedback": "Try again!", "usageCount": 0}])
