from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from ...domain.data.feedback_dto import FeedbackDTO


class ResultDTO(BaseModel):
    completion_date: Optional[datetime] = Field(alias="completionDate", default=None)
    successful: bool = Field(alias="successful", default=False)
    feedbacks: List[FeedbackDTO] = Field(alias="feedbacks", default=[])
