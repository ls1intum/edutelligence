from functools import wraps
from typing import Callable, List

from .app import app
from .schemas import ExerciseTypeVar, Submission, Feedback


def feedback_provider(func: Callable[[ExerciseTypeVar, Submission], List[Feedback]]):
    """
    Provide feedback to the Assessment Module Manager.
    The feedback provider is usually called whenever the tutor requests feedback for a submission in the LMS.
    """
    @app.post("/feedback_suggestions")
    @wraps(func)
    def wrapper(exercise: ExerciseTypeVar, submission: Submission):
        return func(exercise, submission)

    return wrapper
