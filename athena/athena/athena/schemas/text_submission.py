from typing import Optional
from enum import Enum

from pydantic import Field, field_validator

from .submission import Submission


class TextLanguageEnum(str, Enum):
    ENGLISH = "ENGLISH"
    GERMAN = "GERMAN"


class TextSubmission(Submission):
    """Submission on a text exercise."""
    text: str = Field(examples=["Lorem ipsum dolor sit amet, consectetur adipiscing elit."])
    language: Optional[TextLanguageEnum] = Field(None, examples=[TextLanguageEnum.ENGLISH])

    @field_validator("text", mode="before")
    @classmethod
    def normalize_empty_text(cls, value):
        return "" if value is None else value
