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
        callback.in_progress("Analyzing feedbacks ...")
        if not submission or not submission.latest_result:
            return "No feedbacks available."
        feedbacks = submission.latest_result.feedbacks
        feedback_list = (
            "\n".join(
                [
                    f"Case: {feedback.test_case_name}. Credits: {feedback.credits}. Info: {feedback.text}"
                    for feedback in feedbacks
                ]
            )
            if feedbacks
            else "No feedbacks."
        )
        return feedback_list

    return get_feedbacks
