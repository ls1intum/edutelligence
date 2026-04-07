"""Tool for listing repository files."""

from typing import Callable, Dict, Optional

from ..web.status.status_update import StatusCallback


def create_tool_repository_files(
    repository: Optional[Dict[str, str]], callback: StatusCallback
) -> Callable[[], str]:
    """
    Create a tool that lists repository files.

    Args:
        repository: Repository dictionary mapping file paths to content.
        callback: Callback for status updates.

    Returns:
        Function that returns repository file listing.
    """

    def repository_files() -> str:
        """
        # Repository Files Tool

        ## Purpose
        List files in the student's code submission repository.

        ## Retrieved Information
        - File names in the repository

        ## Usage Guidelines
        1. Use before examining file contents to understand submission structure.
        2. Check for expected files based on exercise requirements.
        3. Identify missing or unexpected files quickly.
        4. Guide discussions about file organization and project structure.

        ## Key Points
        - Helps assess completeness of submission.
        - Useful for spotting potential issues (e.g., misplaced files).
        - Informs which files to examine in detail next.

        Returns:
            str: List of files in the repository.
        """
        callback.in_progress("Checking repository content ...")
        if not repository:
            return "No repository content available."
        file_list = "\n------------\n".join(
            [f"- {file_name}" for (file_name, _) in repository.items()]
        )
        return file_list

    return repository_files
