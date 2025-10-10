from abc import ABC
from typing import List, Optional

from pydantic import BaseModel, Field

from .schema import Schema


class StructuredGradingInstruction(Schema, ABC):
    """Part of a grading criterion (called "GradingInstruction" in LMS)."""
    id: int = Field(examples=[1])
    credits: float = Field(description="The number of credits assigned for this feedback.", examples=[1.0])
    grading_scale: str = Field(description="The grading outcome for this instruction.", examples=["Weak example"], default="")
    instruction_description: str = Field(description="Description of how to use this grading instruction.", examples=["Some instructions"], default="")
    feedback: str = Field(description="Description of the feedback to provide.", examples=["Nicely done!"], default="")
    usage_count: int = Field(ge=0, description="The usage limit for this structured grading instruction. 0 means unlimited.", examples=[3], default=0)


class GradingCriterion(Schema, ABC):
    """A structured grading criterion for assessing an exercise."""
    id: int = Field(examples=[1])
    title: Optional[str] = Field(None, examples=["Some instructions"])
    structured_grading_instructions: List[StructuredGradingInstruction] = Field(
        [], examples=[[{"credits": 1.0, "gradingScale": "Good", "instructionDescription": "Some instructions", "feedback": "Nicely done!", "usageCount": 1},
                     {"credits": 0.0, "gradingScale": "Bad", "instructionDescription": "Some instructions", "feedback": "Try again!", "usageCount": 0}]])

class StructuredGradingCriterion(BaseModel):
    criteria: List[GradingCriterion]
