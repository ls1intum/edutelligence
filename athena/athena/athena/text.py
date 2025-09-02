import functools
import athena.storage
from .schemas import TextExercise, TextFeedback, TextSubmission, TextLanguageEnum

# re-export with shorter names, because the module will only use these
Exercise = TextExercise
Submission = TextSubmission
Feedback = TextFeedback

# re-export without the need to give the type of the requested schema
get_stored_exercises = functools.partial(athena.storage.get_stored_exercises, Exercise)
count_stored_submissions = functools.partial(
    athena.storage.count_stored_submissions, Submission
)
get_stored_submissions = functools.partial(
    athena.storage.get_stored_submissions, Submission
)
get_stored_feedback = functools.partial(athena.storage.get_stored_feedback, Feedback)
get_stored_feedback_suggestions = functools.partial(
    athena.storage.get_stored_feedback_suggestions, Feedback
)

__all__ = [
    "Exercise",
    "Submission",
    "Feedback",
    "TextLanguageEnum",
    "get_stored_exercises",
    "get_stored_submissions",
    "get_stored_feedback",
    "get_stored_feedback_suggestions",
]
