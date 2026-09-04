"""Tool for retrieving automated test feedback."""

from typing import Callable, Optional

from ..domain.data.programming_submission_dto import ProgrammingSubmissionDTO
from ..web.status.status_update import StatusCallback


def create_tool_get_feedbacks(
    submission: Optional[ProgrammingSubmissionDTO], callback: StatusCallback
) -> Callable[[], str]:
    """
    Create a tool that retrieves automated test feedback.

    Args:
        submission: Programming submission data.
        callback: Callback for status updates.

    Returns:
        Function that returns feedback analysis.
    """
    del callback

    def get_feedbacks() -> str:
        """
        # Get Feedbacks Tool
        ## Purpose
        Retrieve and analyze automated test feedback from the CI/CD pipeline.

        ## Retrieved Information
        For each feedback item:
        - Test case name
        - Credits awarded
        - Text feedback

        Returns:
            str: Formatted feedback information.
        """
        if not submission or not submission.latest_result:
            return "No feedbacks available."
        feedbacks = submission.latest_result.feedbacks

        def _format(feedback) -> str:
            if feedback.has_test_case is None:
                # Artemis did not send hasTestCase (every release before ls1intum/Artemis#13023).
                # Say nothing about the outcome rather than guess it: this reproduces the line
                # exactly as it read before the field existed.
                outcome = ""
            elif not feedback.has_test_case:
                outcome = " non-test feedback."
            elif feedback.positive is None:
                outcome = " NOT EXECUTED (test case)."
            else:
                outcome = (
                    " PASS (test case)." if feedback.positive else " FAIL (test case)."
                )
            return (
                f"Case: {feedback.test_case_name}.{outcome} "
                f"Credits: {feedback.credits}. Info: {feedback.text}"
            )

        feedback_list = (
            "\n".join([_format(feedback) for feedback in feedbacks])
            if feedbacks
            else "No feedbacks."
        )
        return feedback_list

    return get_feedbacks
