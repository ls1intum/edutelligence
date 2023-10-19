from abc import ABC
from typing import Optional

from pydantic import Field

from .schema import Schema


class StructuredGradingInstruction(Schema, ABC):
    """A structured grading instruction that can be used as a feedback template to grade a text exercise."""

    id: int = Field(example=1)
    feedback_credits: float = Field(description="The number of credits assigned for this feedback.", example=1.0)
    feedback_description: str = Field(description="Description of the feedback to provide.", example="Good job on this part.")
    grading_outcome: str = Field(description="The grading outcome for this instruction.", example="Weak example")
    usage_limit: int = Field(description="The usage limit for this structured grading instruction. 0 means unlimited.", example=3)
    usage_description: str = Field(description="Description of how to use this grading instruction.", example="Use this for case X.")
    criterion_id: int = Field(description="The id of the criterion that this instruction belongs to.", example=1)

    def to_model(self):
        return type(self).get_model_class()(**self.dict())

    class Config:
        orm_mode = True
