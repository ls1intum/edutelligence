from typing import Optional

from athena.programming import Feedback, Submission
from athena.logger import logger

from .extract_methods import extract_methods
from .method_node import MethodNode


def get_feedback_method(submission: Submission, feedback: Feedback) -> Optional[MethodNode]:
    """Find method that the feedback is on"""
    if feedback.file_path is None or feedback.line_start is None:
        return None
    try:
        code = submission.get_code(feedback.file_path)
    except UnicodeDecodeError:
        logger.warning("File %s in submission %d is not UTF-8 encoded.", feedback.file_path, submission.id)
        return None
    methods = extract_methods(code)
    for m in methods:
        if m.line_start is None or m.line_end is None:
            continue
        # method has to contain all feedback lines
        if m.line_start <= feedback.line_start:
            feedback_line_end = feedback.line_end if feedback.line_end is not None else feedback.line_start
            if m.line_end >= feedback_line_end:
                return m
    return None
