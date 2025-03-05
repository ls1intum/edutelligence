from typing import Optional

from athena.programming import Submission, Feedback
from module_programming_apted.convert_code_to_ast.extract_method_and_ast import parse
from module_programming_apted.convert_code_to_ast.method_node import MethodNode
from athena.logger import logger


def get_feedback_method(submission: Submission, feedback: Feedback, programming_language: str) -> Optional[MethodNode]:
    """Find method that the feedback is on"""
    if feedback.file_path is None or feedback.line_start is None:
        return None
    try:
        code = submission.get_code(feedback.file_path)
    except UnicodeDecodeError:
        logger.warning("File %s in submission %d is not UTF-8 encoded.", feedback.file_path, submission.id)
        return None
    methods = parse(code, programming_language)
    for m in methods:
        if m.line_start is None or m.line_end is None:
            continue
        # method has to contain all feedback lines
        if m.line_start <= feedback.line_start:
            feedback_line_end = feedback.line_end if feedback.line_end is not None else feedback.line_start
            if m.line_end >= feedback_line_end:
                return m
    return None
