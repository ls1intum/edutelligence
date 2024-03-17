from typing import List

from pydantic import BaseModel, Field
from datetime import datetime

from ...domain.data.feedback_dto import FeedbackDTO


class ResultDTO(BaseModel):
    completion_date: datetime = Field(alias="completionDate")
    successful: bool
    feedbacks: List[FeedbackDTO] = []
