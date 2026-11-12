from typing import Optional
from enum import Enum

from pydantic import Field, field_validator

from .submission import Submission


class ModelingSubmission(Submission):
    """Submission on a modeling exercise."""
    model: str = Field()

    @field_validator("model", mode="before")
    @classmethod
    def normalize_empty_model(cls, value):
        """Treat a null model as an empty answer while retaining string validation."""
        return "" if value is None else value
