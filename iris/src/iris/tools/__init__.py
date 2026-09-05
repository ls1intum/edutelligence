"""
LLM Tools for Iris pipelines.

Each tool is in its own file for better organization and maintainability.
"""

from .additional_exercise_details import create_tool_get_additional_exercise_details
from .build_logs_analysis import create_tool_get_build_logs_analysis

# Course-related tools
from .course_details import create_tool_get_course_details
from .course_simple_details import create_tool_get_simple_course_details
from .exercise_example_solution import create_tool_get_example_solution
from .exercise_list import create_tool_get_exercise_list
from .exercise_problem_statement import create_tool_get_exercise_problem_statement
from .faq_content_retrieval import create_tool_faq_content_retrieval
from .feedbacks import create_tool_get_feedbacks
from .file_lookup import create_tool_file_lookup
from .last_artifact import create_tool_get_last_artifact

# Retrieval tools
from .lecture_content_retrieval import create_tool_lecture_content_retrieval
from .lecture_list import create_tool_get_lecture_list

# MCQ generation tool
from .mcq_generation import create_tool_generate_mcq_questions
from .repository_files import create_tool_repository_files
from .single_exercise_problem_statement import create_tool_get_problem_statement

# Exercise chat tools
from .submission_details import create_tool_get_submission_details

# Context switching tool
from .switch_chat_context import create_tool_switch_chat_context

__all__ = [
    # Course-related tools
    "create_tool_get_course_details",
    "create_tool_get_exercise_list",
    "create_tool_get_exercise_problem_statement",
    # Exercise chat tools
    "create_tool_get_submission_details",
    "create_tool_get_additional_exercise_details",
    "create_tool_get_build_logs_analysis",
    "create_tool_get_feedbacks",
    "create_tool_repository_files",
    "create_tool_file_lookup",
    # Retrieval tools
    "create_tool_lecture_content_retrieval",
    "create_tool_get_lecture_list",
    "create_tool_faq_content_retrieval",
    # Tutor Suggestion tools
    "create_tool_get_example_solution",
    "create_tool_get_last_artifact",
    "create_tool_get_problem_statement",
    "create_tool_get_simple_course_details",
    # MCQ generation tool
    "create_tool_generate_mcq_questions",
    # Context switching tool
    "create_tool_switch_chat_context",
]
