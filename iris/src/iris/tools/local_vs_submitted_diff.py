"""Tool that diffs the student's live working copy against the last submitted code."""

import difflib
from typing import Callable, Optional

from ..domain.data.programming_submission_dto import ProgrammingSubmissionDTO
from ..web.status.status_update import StatusCallback

_NO_CHANGES = "No code changes since the last submission (current working copy == submitted code)."
_UNAVAILABLE = "The last submitted code could not be read, so a diff of the working copy against it is unavailable (do not assume the live code equals the submitted code)."


def create_tool_local_vs_submitted_diff(
    submission: Optional[ProgrammingSubmissionDTO], callback: StatusCallback
) -> Callable[[], str]:
    """
    Create a tool that shows a unified diff of the student's local changes since the last submission.

    Args:
        submission: Programming submission data. `submitted_repository` holds the committed (last
            submitted build) version of the code files the student changed locally; `repository` holds
            the current live working copy.
        callback: Callback for status updates.

    Returns:
        Function that returns the unified diff (submitted -> local) of the changed code files.
    """

    def local_vs_submitted_diff() -> str:
        """
        # Local vs Submitted Diff Tool

        ## Purpose
        Show what CODE the student changed in their CURRENT (live) working copy SINCE the last
        SUBMITTED build. `get_feedbacks` and `get_submission_details` reflect that last submitted
        build; this tool shows how the live code differs from it, so you can tell whether a fix is
        present in the current code even if it has not been submitted/re-tested yet.

        ## Key Points
        - "No code changes" means the current working copy equals the last submitted code -- but only
          when the submitted code was actually readable. If it could not be read, this tool says so
          explicitly; never treat that as proof the live code equals the submitted code.
        - Only content changes to code files are shown. File deletions and renames are NOT
          represented (the client sends only path -> current content).

        Returns:
            str: A unified diff (submitted -> local), a "no changes" note, or an "unavailable" note.
        """
        callback.in_progress("Diffing working copy against the last submission ...")
        if submission is None or not submission.submitted_repository_available:
            return _UNAVAILABLE
        if not submission.submitted_repository:
            return _NO_CHANGES
        live = submission.repository or {}
        parts = []
        for path, submitted in submission.submitted_repository.items():
            local = live.get(path, "")
            diff = difflib.unified_diff(
                submitted.splitlines(),
                local.splitlines(),
                fromfile=f"submitted/{path}",
                tofile=f"local/{path}",
                lineterm="",
            )
            diff_text = "\n".join(diff)
            if diff_text:
                parts.append(diff_text)
        return "\n\n".join(parts) if parts else _NO_CHANGES

    return local_vs_submitted_diff
