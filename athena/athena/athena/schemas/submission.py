from abc import ABC

from pydantic import Field

from .schema import Schema


class Submission(Schema, ABC):
    id: int = Field(example=1)
    exercise_id: int = Field(example=1)
    content: str = Field(example="https://lms.example.com/assignments/1/submissions/1/download")
    student_id: int = Field(example=1)

    meta: dict = Field(example={})

    class Config:
        orm_mode = True
