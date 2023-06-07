from typing import Optional


def format_feedback_text(file_path: Optional[str] = None, line: Optional[int] = None) -> str:
    """Returns a consistent feedback text for an optional file path and line number.

    Args:
        file_path (Optional[str]): Reference to a file path. Defaults to None.
        line (Optional[int]): Reference to a line number. Defaults to None.

    Returns:
        str: The formatted feedback text
    """
    if file_path is None:
        return "Feedback"
    if line is None:
        return f"File {file_path}"
    return f"File {file_path} at line {line}"


def format_feedback_reference(file_path: Optional[str], line: Optional[int]) -> Optional[str]:
    """Returns a consistent feedback reference for an optional file path and line number.

    Args:
        file_path (Optional[str]): Reference to a file path
        line (Optional[int]): Reference to a line number

    Returns:
        Optional[str]: The formatted feedback reference
    """
    if file_path is None:
        return None
    if line is None:
        return f"file://{file_path}"
    return f"file://{file_path}_line:{line}"
