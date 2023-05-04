from abc import ABC
from typing import Optional

from pydantic import Field

from .schema import Schema


class Feedback(Schema, ABC):
    id: int = Field(example=1)
    exercise_id: int = Field(example=1)
    submission_id: int = Field(example=1)
    detail_text: str = Field(description="The detailed feedback text that is shown to the student.",
                             example="Your solution is correct.")
    reference: Optional[str] = Field(description="A optional reference to the location in the submission where the feedback applies.",
                                     example="file:src/pe1/MergeSort.java_line:12")
    text: str = Field(description="The title of the feedback that is shown to the student.",
                      example="File src/pe1/MergeSort.java at line 12")
    credits: float = Field(description="The number of points that the student received for this feedback.",
                           example=1.0)

    meta: dict = Field(example={})

    class Config:
        orm_mode = True
