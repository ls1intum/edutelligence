from typing import Optional, List

from pydantic import Field

from .feedback import Feedback


class ModellingFeedback(Feedback):
    """Feedback on a modelling exercise."""

    element_ids: Optional[List[str]] = Field([], description="referenced diagram element IDs", example=["id_1"])
