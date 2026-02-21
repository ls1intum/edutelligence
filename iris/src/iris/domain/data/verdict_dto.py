from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from ...domain.data.feedback_dto import FeedbackDTO


class VerdictDTO(BaseModel):
    verdict: Optional[str] = Field(alias="verdict", default=None)
    reasoning: Optional[str] = Field(alias="reasoning", default=None)
