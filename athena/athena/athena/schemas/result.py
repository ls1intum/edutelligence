from abc import ABC
from datetime import datetime
from typing import Optional, List

from pydantic import Field

from . import Feedback, TextSubmission
from .schema import Schema


class Result(Schema, ABC):
    id: Optional[int] = Field(None, example=1)
    completion_date: Optional[datetime] = Field(None, example=datetime.now())
    score: Optional[float] = Field(None, example=0.0)
    rated: Optional[bool] = Field(None, example=True)
    feedbacks: Optional[List[Feedback]] = Field(None, example=[])
    submission: Optional[TextSubmission] = Field(None)

    def submission_to_prompt(self) -> str:
        submission_text = "Not available"
        if self.submission:
            submission_text = f"{self.submission.text}\n"

        return submission_text

    def feedback_to_prompt(self) -> str:
        feedbacks_text = ""
        if self.feedbacks:
            for feedback in self.feedbacks:
                feedbacks_text += f"- {feedback.title}:\n"
                feedbacks_text += f"  Description: {feedback.description}\n"
                feedbacks_text += f"  Credits: {feedback.credits}\n\n"

        return feedbacks_text
