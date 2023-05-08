"""Import this to use schemas and decorators specific to programming exercises."""
import functools
import os

from dotenv import load_dotenv

from .schemas import ProgrammingExercise, ProgrammingFeedback, ProgrammingSubmission
import athena.storage

load_dotenv(".env")
module_type = os.environ["MODULE_TYPE"]
if module_type != "programming":
    raise ImportError(f"Importing athena.programming from a module of type {module_type}. This is probably a mistake, "
                      f"you should only import the file related to the exercise type that your module handles")

# re-export with shorter names, because the module will only use these
Exercise = ProgrammingExercise
Submission = ProgrammingSubmission
Feedback = ProgrammingFeedback

# re-export without the need to give the type of the requested schema
get_stored_exercises = functools.partial(athena.storage.get_stored_exercises, Exercise)
get_stored_submissions = functools.partial(athena.storage.get_stored_submissions, Submission)
get_stored_feedback = functools.partial(athena.storage.get_stored_feedback, Feedback)
get_stored_feedback_suggestions = functools.partial(athena.storage.get_stored_feedback_suggestions, Feedback)

__all__ = [
    "Exercise", "Submission", "Feedback",
    "get_stored_exercises", "get_stored_submissions", "get_stored_feedback", "get_stored_feedback_suggestions"
]
