"""
This module provides a decorator for submission consumers.
"""
from functools import wraps
from typing import List, Callable

from .schemas import Exercise, Submission
from ..app import app
from athena.storage import store_submissions, store_exercise

def submissions_consumer(func: Callable[[Exercise, List[Submission]], None]):
    """
    Receive submissions from the Assessment Module Manager and automatically store them in the database.
    The submissions consumer is usually called whenever the deadline for an exercise is reached.
    """
    @app.post("/submissions")
    @wraps(func)
    def wrapper(exercise, submissions):
        store_exercise(exercise)
        store_submissions(submissions)
        return func(exercise, submissions)

    return wrapper
