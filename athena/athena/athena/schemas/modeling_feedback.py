from typing import Optional
from pydantic import Field
from .feedback import Feedback


class ModelingFeedback(Feedback):
    """Feedback on a modeling exercise."""

    reference: Optional[str] = Field(None, description="reference to the diagram element", example="ClassAttribute:5a337bdf-da00-4bd0-a6f0-78ba5b84330e")