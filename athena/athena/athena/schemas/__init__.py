"""Schemas are pydantic models for data transfer objects (DTOs)."""

from .exercise_type import ExerciseType
from .exercise import Exercise
from .feedback import Feedback
from .submission import Submission
from .text_feedback import TextFeedback
from .text_exercise import TextExercise
from .text_submission import TextSubmission, TextLanguageEnum
from .programming_feedback import ProgrammingFeedback
from .programming_exercise import ProgrammingExercise
from .programming_submission import ProgrammingSubmission
from .grading_criterion import GradingCriterion, StructuredGradingInstruction