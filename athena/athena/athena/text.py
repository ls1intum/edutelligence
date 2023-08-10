"""Import this to use schemas and decorators specific to text exercises."""
import functools

import athena.storage
from .module_config import get_module_config
from .schemas import TextExercise, TextFeedback, TextSubmission, TextLanguageEnum

module_type = get_module_config().type
if module_type.name != "text":
    raise ImportError(f"Importing athena.text from a module of type {module_type}. This is probably a mistake, "
                      f"you should only import the file related to the exercise type that your module handles")

# re-export with shorter names, because the module will only use these
Exercise = TextExercise
Submission = TextSubmission
Feedback = TextFeedback

# re-export without the need to give the type of the requested schema
get_stored_exercises = functools.partial(athena.storage.get_stored_exercises, Exercise)
get_stored_submissions = functools.partial(athena.storage.get_stored_submissions, Submission)
get_stored_feedback = functools.partial(athena.storage.get_stored_feedback, Feedback)
get_stored_feedback_suggestions = functools.partial(athena.storage.get_stored_feedback_suggestions, Feedback)

__all__ = [
    "Exercise", "Submission", "Feedback", "TextLanguageEnum",
    "get_stored_exercises", "get_stored_submissions", "get_stored_feedback", "get_stored_feedback_suggestions",
]
