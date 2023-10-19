from abc import ABC
from typing import List

from pydantic import Field

from .schema import Schema
from .structured_grading_instruction import StructuredGradingInstruction


class StructuredGradingCriterion(Schema, ABC):
    """A structured grading criterion grouping multiple structured grading instructions of the same criterion."""

    id: int = Field(example=1)
    title: str = Field(description="The title of the structured grading criterion.",
                       example="Assessment of the Code Quality")
    exercise_id: int = Field(
        description="The id of the exercise that this structured grading criterion belongs to.",
        example=1
    )

    structured_grading_instructions: List[StructuredGradingInstruction] = Field(
        description="List of structured grading instructions for this criterion."
    )

    def to_model(self):
        return type(self).get_model_class()(**self.dict())

    class Config:
        orm_mode = True
