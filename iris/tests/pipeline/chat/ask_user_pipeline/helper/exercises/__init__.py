"""Exercise fixtures for the ask_user_pipeline / assess_user_answer_pipeline
LLM tests (test_ask_user_first_question.py, test_ask_user_multiple_questions.py,
assess_user_answer_pipeline/test_assess_user_answer_limits.py,
assess_user_answer_pipeline/test_assess_user_answer_verdict.py).

Each Exercise bundles everything those tests need for one programming
exercise: the task/template/submission (as before), plus the tutor question
and the hardcoded student answers the assess_user_answer tests grade. All
LLM tests import the single ACTIVE_EXERCISE below instead of exercise-specific
names, so pointing every test at a different exercise is a one-line change
here rather than edits scattered across every test file.
"""

from dataclasses import dataclass

from .history_exercise import HISTORY_EXERCISE
from .models import Exercise
from .sorting_exercise import SORTING_EXERCISE

__all__ = [
    "SORTING_EXERCISE",
    "HISTORY_EXERCISE",
    "ACTIVE_EXERCISE",
]


# Swap this to point every ask_user/assess_user_answer LLM test at a
# different exercise.
ACTIVE_EXERCISE: Exercise = SORTING_EXERCISE
