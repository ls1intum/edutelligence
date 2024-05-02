from typing import Optional, List

from pydantic import Field

from .feedback import Feedback


class ModelingFeedback(Feedback):
    """Feedback on a modeling exercise."""

    element_ids: Optional[List[str]] = Field([], description="referenced diagram element IDs", example=["id_1"])
