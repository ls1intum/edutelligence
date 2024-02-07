from typing import Optional
from enum import Enum

from pydantic import Field

from .submission import Submission


class ModellingSubmission(Submission):
    """Submission on a modelling exercise."""
    model: str = Field()
