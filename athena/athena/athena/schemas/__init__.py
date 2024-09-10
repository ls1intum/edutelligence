"""Schemas are pydantic models for data transfer objects (DTOs)."""

from .exercise_type import ExerciseType
from .exercise import Exercise
from .feedback import Feedback
from .submission import Submission
from .structured_grading_instruction import StructuredGradingInstruction, StructuredGradingInstructionGroup, StructuredGradingInstructionCriterion
from .text_feedback import TextFeedback
from .text_exercise import TextExercise
from .text_submission import TextSubmission, TextLanguageEnum
from .programming_feedback import ProgrammingFeedback
from .programming_exercise import ProgrammingExercise
from .programming_submission import ProgrammingSubmission
from .modeling_feedback import ModelingFeedback
from .modeling_exercise import ModelingExercise
from .modeling_submission import ModelingSubmission
from .modeling_structured_grading_instruction import ModelingStructuredGradingInstruction