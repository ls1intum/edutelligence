from typing import Optional
from enum import Enum

from pydantic import Field

from .submission import Submission


class TextLanguageEnum(str, Enum):
    ENGLISH = "ENGLISH"
    GERMAN = "GERMAN"


class TextSubmission(Submission):
    """Submission on a text exercise."""
    text: str = Field(example="Lorem ipsum dolor sit amet, consectetur adipiscing elit.")
    language: Optional[TextLanguageEnum] = Field(None, example=TextLanguageEnum.ENGLISH)
