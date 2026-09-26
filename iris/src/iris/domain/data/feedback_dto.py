from typing import Optional

from pydantic import BaseModel, Field


class FeedbackDTO(BaseModel):
    """One feedback item of a submission's latest result, as Artemis sends it."""

    text: Optional[str] = None
    test_case_name: Optional[str] = Field(alias="testCaseName", default=None)
    credits: float
    # positive is the authoritative outcome and is TRI-STATE: True=passed, False=failed, None=not executed.
    # has_test_case distinguishes a real test-case result from non-test feedback (otherwise indistinguishable
    # in test_case_name). It is TRI-STATE on purpose: None means Artemis did not send the field at all, which
    # every Artemis release before ls1intum/Artemis#13023 does. Defaulting that to False would tell the model
    # that genuine test results are non-test feedback, and get_feedbacks is shared with the exercise chat and
    # the tutor-suggestion pipeline, so the lie would not stay inside this feature.
    positive: Optional[bool] = None
    has_test_case: Optional[bool] = Field(alias="hasTestCase", default=None)

    def __str__(self):
        return f"{self.test_case_name}: {self.text} ({self.credits} credits)"
