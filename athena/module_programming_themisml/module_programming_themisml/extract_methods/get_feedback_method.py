from typing import Optional
from athena.programming import Feedback, Submission
from module_programming_themisml.extract_methods import extract_methods, MethodNode


def get_feedback_method(submission: Submission, feedback: Feedback) -> Optional[MethodNode]:
    """Find method that the feedback is on"""
    if feedback.file_path is None or feedback.line_start is None:
        return None
    code = submission.get_code(feedback.file_path)
    methods = extract_methods(code)
    feedback_method = None
    for m in methods:
        if m.line_start is None or m.line_end is None:
            continue
        # method has to contain all feedback lines
        if m.line_start <= feedback.line_start:
            if feedback.line_end is None or m.line_end >= feedback.line_end:
                return m
    return None
