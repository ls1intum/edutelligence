"""file_lookup variant that prefixes 1-based line numbers, for pipelines that
need precise line anchors (e.g. struggle intervention).

The stock ``file_lookup`` tool is intentionally left unchanged; this variant
delegates its not-found / no-repo error paths to it so the error messages stay
in sync, and only overrides the success path to add line-number prefixes.
"""

from typing import Callable, Dict, Optional

from ..web.status.status_update import StatusCallback
from .file_lookup import create_tool_file_lookup


def _number_lines(text: str) -> str:
    """Prefix each line with its 1-based number: ``NN| <line>``."""
    return "\n".join(
        f"{i:>4}| {line}" for i, line in enumerate(text.splitlines(), start=1)
    )


def create_tool_file_lookup_with_line_numbers(
    repository: Optional[Dict[str, str]], callback: StatusCallback
) -> Callable[[str], str]:
    """
    Create a file-lookup tool whose output is 1-based line-numbered.

    Same contract as ``create_tool_file_lookup`` (path -> content), but the
    returned content is prefixed with line numbers so the model can reference an
    exact line (e.g. ``anchor.line``) without counting lines itself.

    Args:
        repository: Repository dictionary mapping file paths to content.
        callback: Callback for status updates.

    Returns:
        Function that returns line-numbered file content by path.
    """
    base = create_tool_file_lookup(repository, callback)

    def file_lookup(file_path: str) -> str:
        """
        # File Lookup Tool (line-numbered)

        ## Purpose
        Retrieve content of a specific file from the student's code repository.

        ## Input
        - file_path: Path of the file to retrieve

        ## Output
        - The file content, with every line prefixed by its 1-based line number
          in the form ``NN| <code>``, or a "File not found" message.

        ## Key Points
        - Use the printed line-number prefixes for ANY line reference (e.g.
          ``anchor.line``). Do NOT count lines yourself.
        - Use after identifying the file with the repository_files tool.

        Args:
            file_path: Path of the file to retrieve.

        Returns:
            str: Line-numbered file content or an error message.
        """
        if repository and file_path in repository:
            callback.in_progress(f"Looking into file {file_path} ...")
            return f"{file_path}:\n{_number_lines(repository[file_path])}\n"
        return base(file_path)

    return file_lookup
