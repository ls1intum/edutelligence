from typing import Optional

from .feedback import Feedback
from ..helpers.programming import format_feedback_text, format_feedback_reference

class ProgrammingFeedback(Feedback):
    """Feedback on a programming exercise."""

    def __init__(self,
             exercise_id: int,
             submission_id: int,
             detail_text: str,
             credits: float,
             meta: dict,
             file_path: Optional[str] = None,
             line: Optional[int] = None,
             id: Optional[int] = None):
        super().__init__(
            id=id,
            exercise_id=exercise_id,
            submission_id=submission_id,
            detail_text=detail_text,
            reference=format_feedback_reference(file_path, line),
            text=format_feedback_text(file_path, line),
            credits=credits,
            meta=meta if meta is not None else {}
        )