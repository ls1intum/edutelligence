"""Tool for retrieving submission details."""

from operator import attrgetter
from typing import Callable, Optional

from ..domain.data.programming_submission_dto import ProgrammingSubmissionDTO
from ..web.status.status_update import StatusCallback


def create_tool_get_submission_details(
    submission: Optional[ProgrammingSubmissionDTO], callback: StatusCallback
) -> Callable[[], dict]:
    """
    Create a tool that retrieves submission details.

    Args:
        submission: Programming submission data.
        callback: Callback for status updates.

    Returns:
        Function that returns submission details.
    """

    def get_submission_details() -> dict:
        """
        # Submission Details Retrieval Tool

        ## Purpose
        Fetch key information about a student's code submission for context and evaluation.

        ## Retrieved Information
        - submission_date: Submission timing
        - is_practice: Practice or graded attempt
        - build_failed: Build process status
        - latest_result: Most recent evaluation outcome

        Returns:
            dict: Dictionary containing submission details.
        """
        callback.in_progress("Reading submission details...")
        if not submission:
            return {
                field: f'No {field.replace("_", " ")} is provided'
                for field in [
                    "submission_date",
                    "is_practice",
                    "build_failed",
                    "latest_result",
                ]
            }

        getter = attrgetter("date", "is_practice", "build_failed", "latest_result")
        values = getter(submission)
        keys = [
            "submission_date",
            "is_practice",
            "build_failed",
            "latest_result",
        ]

        return {
            key: (
                str(value)
                if value is not None
                else f'No {key.replace("_", " ")} is provided'
            )
            for key, value in zip(keys, values)
        }

    return get_submission_details
