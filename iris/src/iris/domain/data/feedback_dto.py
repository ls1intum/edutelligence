from typing import Optional

from pydantic import BaseModel, Field


class FeedbackDTO(BaseModel):
    text: Optional[str] = None
    test_case_name: Optional[str] = Field(alias="testCaseName", default=None)
    credits: float

    def __str__(self):
        return f"{self.test_case_name}: {self.text} ({self.credits} credits)"
