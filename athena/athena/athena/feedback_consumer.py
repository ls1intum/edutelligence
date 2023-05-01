"""
This module provides a decorator for feedback consumers.
"""
from functools import wraps
from typing import Callable

from .app import app
from .schemas import ExerciseTypeVar, Submission, Feedback
from .storage import store_feedback


def feedback_consumer(func: Callable[[ExerciseTypeVar, Submission, Feedback], None]):
    """
    Receive feedback from the Assessment Module Manager and automatically store it in the database.
    The feedback consumer is usually called whenever the LMS gets feedback from a tutor.
    """
    @app.post("/feedback")
    @wraps(func)
    def wrapper(exercise: ExerciseTypeVar, submission: Submission, feedback: Feedback):
        store_feedback(feedback)
        return func(exercise, submission, feedback)

    return wrapper
