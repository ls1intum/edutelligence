from abc import ABC

from pydantic import ConfigDict, Field

from .schema import Schema


class Submission(Schema, ABC):
    id: int = Field(examples=[1])
    exercise_id: int = Field(examples=[1])

    meta: dict = Field({}, examples=[{}])
    model_config = ConfigDict(from_attributes=True)
