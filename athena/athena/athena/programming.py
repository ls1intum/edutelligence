"""Import this to use schemas and decorators specific to programming exercises."""
import os

from .schemas import ProgrammingExercise, ProgrammingFeedback, ProgrammingSubmission

module_type = os.environ["MODULE_TYPE"]
if module_type != "programming":
    raise ImportError(f"Importing athena.programming from a module of type {module_type}. This is probably a mistake, "
                      f"you should only import the file related to the exercise type that your module handles")

# re-export with shorter names, because the module will only use these
Exercise = ProgrammingExercise
Submission = ProgrammingSubmission
Feedback = ProgrammingFeedback

__all__ = [
    "Exercise", "Submission", "Feedback"
]
