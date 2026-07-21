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
    del callback

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
        5. For build or test diagnosis, use this repository evidence together
           with available build logs and automated feedback before advising.

        ## Key Points
        - Helps assess completeness of submission.
        - Useful for spotting potential issues (e.g., misplaced files).
        - Informs which files to examine in detail next.
        - The repository is already supplied by Artemis; do not ask the student
          to paste code that can be inspected with this tool and file lookup.

        Returns:
            str: List of files in the repository.
        """
        if not repository:
            return "No repository content available."
        file_list = "\n------------\n".join(
            [f"- {file_name}" for (file_name, _) in repository.items()]
        )
        return file_list

    return repository_files
