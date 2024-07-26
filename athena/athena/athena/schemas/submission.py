from abc import ABC

from pydantic import Field

from .schema import Schema


class Submission(Schema, ABC):
    id: int = Field(example=1)
    exercise_id: int = Field(example=1, alias="exercise_id")

    meta: dict = Field({}, example={})

    class Config:
        # from_attributes = True
        orm_mode=True
