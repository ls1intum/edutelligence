from abc import ABC
from typing import Optional

from pydantic import ConfigDict, Field

from .schema import Schema


class Feedback(Schema, ABC):
    id: Optional[int] = Field(default=None, examples=[1])
    title: Optional[str] = Field(
        None,
        description="The title of the feedback that is shown to the student.",
        examples=["File src/pe1/MergeSort.java at line 12"],
    )
    description: Optional[str] = Field(
        None,
        description="The detailed feedback description that is shown to the student.",
        examples=["Your solution is correct."],
    )
    credits: float = Field(
        default=0.0,
        description="The number of points that the student received for this feedback.",
        examples=[1.0],
    )
    structured_grading_instruction_id: Optional[int] = Field(
        default=None,
        description="The id of the structured grading instruction that this feedback belongs to.",
        examples=[1],
    )
    is_graded: Optional[bool] = Field(
        None, description="Graded or non graded.", examples=[False]
    )

    meta: dict = Field({}, examples=[{}])

    exercise_id: int = Field(examples=[1])
    submission_id: int = Field(examples=[1])

    def to_model(
        self,
        is_suggestion: bool = False,
        lms_id: Optional[int] = None,
        lms_url: Optional[str] = None,
    ):
        return type(self).get_model_class()(
            **self.model_dump(), is_suggestion=is_suggestion, lms_id=lms_id, lms_url=lms_url
        )
    model_config = ConfigDict(from_attributes=True)
