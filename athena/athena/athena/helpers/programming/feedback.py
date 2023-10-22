from typing import Optional


def format_feedback_title(file_path: Optional[str], line_start: Optional[int] = None, line_end: Optional[int] = None) -> str:
    """Returns a consistent feedback title for an optional file path and line number.

    Args:
        file_path (Optional[str]): Path to the file that the feedback is given on. Defaults to None.
        line_start (Optional[int]): The start line number of the feedback. Defaults to None.
        line_end (Optional[int]): The end line number of the feedback. Defaults to None. Cannot be None if line_start is not None.

    Returns:
        str: The formatted feedback title (not standardized, just if you don't have a better title)
    """
    if file_path is None:
        return "Feedback"
    if line_start is None:
        assert line_end is None, "line_end must be None if line_start is None"
        return f"File {file_path}"
    assert line_end is not None, "line_end must be specified if line_start is specified"
    if line_end == line_start:
        return f"File {file_path} at line {line_start}"
    return f"File {file_path} at lines {line_start}-{line_end}"
