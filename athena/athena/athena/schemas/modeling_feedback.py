from typing import List, Optional
from pydantic import Field
from .feedback import Feedback


class ModelingFeedback(Feedback):
    """Feedback on a modeling exercise."""

    element_ids: Optional[List[str]] = Field([], description="referenced diagram element IDs", examples=[["id_1"]]) # Todo: Remove after adding migrations to athena
    reference: Optional[str] = Field(None, description="reference to the diagram element", examples=["ClassAttribute:5a337bdf-da00-4bd0-a6f0-78ba5b84330e"])