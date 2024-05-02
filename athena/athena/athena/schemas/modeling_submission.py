from typing import Optional
from enum import Enum

from pydantic import Field

from .submission import Submission


class ModelingSubmission(Submission):
    """Submission on a modeling exercise."""
    model: str = Field()
