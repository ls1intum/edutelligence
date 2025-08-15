"""Tool for looking up file content from repository."""

from typing import Callable, Dict, Optional

from ..web.status.status_update import StatusCallback


def create_tool_file_lookup(
    repository: Optional[Dict[str, str]], callback: StatusCallback
) -> Callable[[str], str]:
    """
    Create a tool that looks up file content.

    Args:
        repository: Repository dictionary mapping file paths to content.
        callback: Callback for status updates.

    Returns:
        Function that returns file content by path.
    """

    def file_lookup(file_path: str) -> str:
        """
        # File Lookup Tool

        ## Purpose
        Retrieve content of a specific file from the student's code repository.

        ## Input
        - file_path: Path of the file to retrieve

        ## Retrieved Information
        - File content if found, or "File not found" message

        ## Usage Guidelines
        1. Use after identifying relevant files with the repository_files tool.
        2. Examine file contents for code review, bug identification, or style assessment.
        3. Compare file content with exercise requirements or expected implementations.
        4. If a file is not found, consider if it's a required file or a naming issue.

        ## Key Points
        - This tool should only be used after the repository_files tool has been used to identify
        the files in the repository. That way, you can have the correct file path to look up the file content.
        - Essential for detailed code analysis and feedback.
        - Helps in assessing code quality, correctness, and adherence to specifications.
        - Use in conjunction with exercise details for context-aware evaluation.

        Args:
            file_path: Path of the file to retrieve.

        Returns:
            str: File content or error message.
        """
        callback.in_progress(f"Looking into file {file_path} ...")
        if not repository:
            return "No repository content available. File content cannot be retrieved."

        if file_path in repository:
            return f"{file_path}:\n{repository[file_path]}\n"
        return "File not found or does not exist in the repository."

    return file_lookup
