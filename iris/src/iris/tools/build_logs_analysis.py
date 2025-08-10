"""Tool for analyzing build logs."""

from typing import Callable, Optional

from ..domain.data.programming_submission_dto import ProgrammingSubmissionDTO
from ..web.status.status_update import StatusCallback


def create_tool_get_build_logs_analysis(
    submission: Optional[ProgrammingSubmissionDTO], callback: StatusCallback
) -> Callable[[], str]:
    """
    Create a tool that analyzes build logs.

    Args:
        submission: Programming submission data.
        callback: Callback for status updates.

    Returns:
        Function that returns build logs analysis.
    """

    def get_build_logs_analysis_tool() -> str:
        """
        # Build Logs Analysis Tool

        ## Purpose
        Analyze CI/CD build logs for debugging and code quality feedback.

        ## Retrieved Information
        - Build status (successful or failed)
        - If failed:
          - Error messages
          - Warning messages
          - Timestamps for log entries

        Returns:
            str: Build logs analysis result.
        """
        callback.in_progress("Analyzing build logs ...")
        if not submission:
            return "No build logs available."
        build_failed = submission.build_failed
        build_logs = submission.build_log_entries
        logs = (
            "The build was successful."
            if not build_failed
            else (
                "\n".join(
                    str(log) for log in build_logs if "~~~~~~~~~" not in log.message
                )
            )
        )
        return logs

    return get_build_logs_analysis_tool
