"""
This module provides a decorator for submission consumers.
"""
from functools import wraps
from typing import List, Callable

from .app import app
from .schemas import ExerciseTypeVar, Submission
from .storage import store_submissions


def submissions_consumer(func: Callable[[ExerciseTypeVar, List[Submission]], None]):
    """
    Receive submissions from the Assessment Module Manager and automatically store them in the database.
    The submissions consumer is usually called whenever the deadline for an exercise is reached.
    """
    @app.post("/submissions")
    @wraps(func)
    def wrapper(exercise: ExerciseTypeVar, submissions: List[Submission]):
        store_submissions(submissions)
        return func(exercise, submissions)

    return wrapper
