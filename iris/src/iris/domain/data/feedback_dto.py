from typing import Optional

from pydantic import BaseModel, Field


class FeedbackDTO(BaseModel):
    text: Optional[str] = None
    test_case_name: Optional[str] = Field(alias="testCaseName", default=None)
    credits: float
    # positive is the authoritative outcome and is TRI-STATE: True=passed, False=failed, None=not executed.
    # has_test_case distinguishes a real test-case result from non-test feedback (otherwise indistinguishable
    # in test_case_name).
    positive: Optional[bool] = None
    has_test_case: bool = Field(alias="hasTestCase", default=False)

    def __str__(self):
        return f"{self.test_case_name}: {self.text} ({self.credits} credits)"
