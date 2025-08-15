"""
LLM Tools for Iris pipelines.

Each tool is in its own file for better organization and maintainability.
"""

from .additional_exercise_details import create_tool_get_additional_exercise_details
from .build_logs_analysis import create_tool_get_build_logs_analysis
from .competency_list import create_tool_get_competency_list

# Course-related tools
from .course_details import create_tool_get_course_details
from .exercise_list import create_tool_get_exercise_list
from .exercise_problem_statement import create_tool_get_exercise_problem_statement
from .faq_content_retrieval import create_tool_faq_content_retrieval
from .feedbacks import create_tool_get_feedbacks
from .file_lookup import create_tool_file_lookup

# Retrieval tools
from .lecture_content_retrieval import create_tool_lecture_content_retrieval
from .repository_files import create_tool_repository_files
from .student_exercise_metrics import create_tool_get_student_exercise_metrics

# Exercise chat tools
from .submission_details import create_tool_get_submission_details

__all__ = [
    # Course-related tools
    "create_tool_get_course_details",
    "create_tool_get_exercise_list",
    "create_tool_get_exercise_problem_statement",
    "create_tool_get_competency_list",
    "create_tool_get_student_exercise_metrics",
    # Exercise chat tools
    "create_tool_get_submission_details",
    "create_tool_get_additional_exercise_details",
    "create_tool_get_build_logs_analysis",
    "create_tool_get_feedbacks",
    "create_tool_repository_files",
    "create_tool_file_lookup",
    # Retrieval tools
    "create_tool_lecture_content_retrieval",
    "create_tool_faq_content_retrieval",
]
